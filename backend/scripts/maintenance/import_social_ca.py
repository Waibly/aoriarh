"""Bounded, restartable import of a frozen, explicitly selected CA RH source lot.

--plan is read-only for application data; --apply archives and indexes admitted
sources; --verify checks every new passage, source byte and metadata field.
Embedding transport, caching, token reservation and pacing reuse the audited
DILA importer. There is no evaluation or rewriting of LLM generations.
"""

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from qdrant_client.models import FieldCondition, Filter, MatchAny
from sqlalchemy import select, text
from tokenizers import Tokenizer

from app.core.database import async_session_factory, engine
from app.models.document import Document
from app.rag.ingestion import IngestionPipeline
from app.rag.qdrant_store import COLLECTION_NAME, ensure_collection, get_qdrant_client
from app.services.social_ca_source import (
    parse_ca_source,
    prepared_ca_chunks,
    reference_aliases,
    verified_ca_source,
)
from app.services.storage_service import StorageService
from scripts.maintenance.import_dila_cass import Embeddings, dump, run_batches


def state_db(root):
    db = sqlite3.connect(root / "ca-import.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,path TEXT,sha TEXT,"
        "document_id TEXT,disposition TEXT,status TEXT,meta TEXT,error TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,reserved INTEGER,"
        "actual INTEGER,status TEXT,error TEXT)"
    )
    db.commit()
    return db


def read_source(root, row):
    path = Path(row["path"])
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe source archive path")
    with gzip.open(root / path, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != row["sha"]:
        raise ValueError("Selected source archive hash mismatch")
    source = parse_ca_source(json.loads(raw))
    if source.source_id != row["id"] or source.source_bytes != raw:
        raise ValueError("Selected source identity or sealed serialization changed")
    return source


def case_keys(court, day, numbers):
    return {(court, str(day), alias) for alias in reference_aliases(numbers)}


def snapshot(doc):
    fields = [
        "id",
        "source_url",
        "file_hash",
        "storage_path",
        "chunk_count",
        "indexation_status",
        "date_decision",
        "juridiction",
        "chambre",
        "numero_pourvoi",
        "retired_at",
    ]
    return {k: str(getattr(doc, k)) if getattr(doc, k) is not None else None for k in fields}


async def public_documents(session):
    return (
        await session.scalars(
            select(Document).where(
                Document.source_type == "arret_cour_appel",
                Document.organisation_id.is_(None),
                Document.private_dossier_id.is_(None),
                Document.private_conversation_id.is_(None),
            )
        )
    ).all()


async def plan(root, db, tokenizer):
    download = json.loads((root / "download-report.json").read_text())
    if not download["complete"] or download["missing_selected_source_ids"]:
        raise ValueError("Full source download must be complete before planning")
    selection = [json.loads(line) for line in (root / "selection.jsonl").read_text().splitlines()]
    if len(selection) != 34926 or len({r["source_id"] for r in selection}) != len(selection):
        raise ValueError("Unexpected authorized lot identity count")
    selected = {r["source_id"]: r for r in selection}
    scan = sqlite3.connect(f"file:{root / 'fulltext-scan.sqlite3'}?mode=ro&immutable=1", uri=True)
    scan.row_factory = sqlite3.Row
    async with async_session_factory() as session:
        existing = await public_documents(session)
    if not (root / "baseline-documents.json").exists():
        dump(root / "baseline-documents.json", [snapshot(d) for d in existing])
    by_url = defaultdict(list)
    by_case = defaultdict(list)
    for doc in existing:
        if doc.source_url:
            by_url[doc.source_url.rstrip("/")].append(doc)
        if doc.retired_at is None:
            for key in case_keys(doc.juridiction, doc.date_decision, [doc.numero_pourvoi or ""]):
                by_case[key].append(doc)
    # The sealed census knows all joined source RG numbers for legacy documents.
    evidence = json.loads((root.parent / "reconciliation-details.json").read_text())
    original_meta = sqlite3.connect(
        f"file:{root.parent / 'inventory.sqlite3'}?mode=ro&immutable=1", uri=True
    )
    existing_by_id = {str(d.id): d for d in existing}
    for document_id, matches in evidence["production_matches"].items():
        owner = existing_by_id.get(document_id)
        if owner is None or owner.retired_at is not None or len(matches) != 1:
            continue
        row = original_meta.execute(
            "SELECT metadata FROM records WHERE id=?", (matches[0]["source_id"],)
        ).fetchone()
        if row:
            meta = json.loads(row[0])
            for key in case_keys(owner.juridiction, owner.date_decision, meta.get("numbers") or []):
                by_case[key].append(owner)
    counts = Counter()
    totals = Counter()
    seen = defaultdict(list)
    for index, row in enumerate(scan.execute("SELECT id,path,sha,error FROM selected ORDER BY id")):
        if row["id"] not in selected:
            raise ValueError("Downloaded source outside authorized selection")
        current = db.execute("SELECT * FROM items WHERE id=?", (row["id"],)).fetchone()
        if current:
            if current["sha"] != row["sha"]:
                raise ValueError("Planned source version changed")
            meta = json.loads(current["meta"])
            counts[current["disposition"]] += 1
            if current["disposition"] == "new":
                totals.update(tokens=meta["tokens"], passages=meta["chunks"])
            if meta.get("source_metadata"):
                for key in case_keys(meta["court"], meta["date"], meta["numbers"]):
                    seen[key].append((meta["source_metadata"]["source_text_sha256"], row["id"]))
            continue
        disposition, status, error = "new", "pending", row["error"]
        meta = {}
        document_id = None
        try:
            if error:
                raise ValueError(error)
            source = read_source(root, row)
            expected = selected[source.source_id]
            if source.day.year not in {2025, 2026} or str(source.day) != expected["decision_date"]:
                raise ValueError("Source outside authorized decision dates")
            if source.raw["nac"] != expected["nac"]:
                raise ValueError("Source official NAC changed")
            doc = source.document()
            document_id = str(doc.id)
            keys = case_keys(doc.juridiction, source.day, source.numbers)
            owners = {str(d.id): d for key in keys for d in by_case[key]}
            exact_url = by_url[source.url]
            if len(exact_url) > 1:
                raise ValueError("Multiple production documents share source URL")
            if exact_url:
                owner = exact_url[0]
                if owner.file_hash != source.text_sha256 or owner.retired_at is not None:
                    raise ValueError("Existing native source has a different body or is retired")
                disposition, status, document_id = "existing", "excluded", str(owner.id)
            elif owners:
                exact = [d for d in owners.values() if d.file_hash == source.text_sha256]
                if len(exact) == 1:
                    disposition, status, document_id = (
                        "duplicate_existing",
                        "excluded",
                        str(exact[0].id),
                    )
                else:
                    raise ValueError(
                        "Legacy court/date/RG identity requires original-version review"
                    )
            matching_sources = {
                sid for key in keys for sha, sid in seen[key] if sha == source.text_sha256
            }
            if disposition == "new" and matching_sources:
                disposition, status = "duplicate_source", "excluded"
                meta["duplicate_source_id"] = sorted(matching_sources)[0]
            chunks = prepared_ca_chunks(source, doc)
            sizes = [len(t.ids) for t in tokenizer.encode_batch(chunks)]
            if not sizes or max(sizes) > 16000:
                raise ValueError("Complete source passage exceeds embedding context")
            meta.update(
                date=str(source.day),
                numbers=list(source.numbers),
                court=doc.juridiction,
                source_metadata=source.metadata(),
                chunks=len(chunks),
                tokens=sum(sizes),
                chunk_sha256=[hashlib.sha256(c.encode()).hexdigest() for c in chunks],
            )
            for key in keys:
                seen[key].append((source.text_sha256, source.source_id))
        except Exception as exc:
            disposition, status, error = "technical_review", "held", f"{type(exc).__name__}: {exc}"
        db.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?,?)",
            (
                row["id"],
                row["path"],
                row["sha"],
                document_id,
                disposition,
                status,
                json.dumps(meta, ensure_ascii=False),
                error,
            ),
        )
        counts[disposition] += 1
        if disposition == "new":
            totals.update(tokens=meta["tokens"], passages=meta["chunks"])
        if index % 100 == 0:
            db.commit()
            print(json.dumps({"planned": index + 1, "counts": dict(counts)}), flush=True)
    db.commit()
    scan.close()
    original_meta.close()
    if sum(counts.values()) != len(selected):
        raise ValueError("Plan does not account for every authorized source")
    result = {
        "authorized_candidates": len(selected),
        "dispositions": dict(counts),
        "tokens": totals["tokens"],
        "passages": totals["passages"],
        "estimated_embedding_usd": totals["tokens"] * 0.12 / 1_000_000,
        "technical_holds": [
            dict(r) for r in db.execute("SELECT id,error FROM items WHERE status='held'")
        ],
        "application_data_mutations": 0,
        "paid_model_calls": 0,
    }
    dump(root / "plan.json", result)
    print(json.dumps(result), flush=True)


async def lock_source(session, source):
    if session.get_bind().dialect.name == "postgresql":
        digest = hashlib.sha256(("ca:" + source.source_id).encode()).digest()
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(digest[:8], signed=True)},
        )


async def apply(root, db, tokenizer, args):
    if not (root / "plan.json").exists():
        raise ValueError("A complete plan is required")
    storage = StorageService()
    qdrant = get_qdrant_client()
    ensure_collection(qdrant)
    embedder = Embeddings(
        root, db, tokenizer, args.tokens_per_minute, args.max_total_tokens, input_type="document"
    )
    if shutil.disk_usage(root).free < 20 * 2**30:
        raise ValueError("Insufficient free disk reserve")
    rows = db.execute("SELECT id FROM items WHERE disposition='new' ORDER BY id").fetchall()
    groups = [rows[i : i + 32] for i in range(0, len(rows), 32)]
    if args.limit_groups:
        groups = groups[: args.limit_groups]
    publish_slots = asyncio.Semaphore(6)
    async with engine.begin() as connection:
        if not await connection.scalar(text("SELECT pg_try_advisory_xact_lock(20261026,2)")):
            raise ValueError("Another CA import is active")
        try:

            async def process(group):
                group = [
                    db.execute("SELECT * FROM items WHERE id=?", (r["id"],)).fetchone()
                    for r in group
                ]
                if all(r["status"] == "indexed" for r in group):
                    return
                if (root / "STOP").exists():
                    raise ValueError("Operator stop; paid in-flight groups will settle")
                if shutil.disk_usage(root).free < 20 * 2**30:
                    raise ValueError("Import paused at disk reserve")
                prepared = []
                for row in group:
                    source = read_source(root, row)
                    doc = source.document()
                    chunks = prepared_ca_chunks(source, doc)
                    expected = json.loads(row["meta"])
                    if [hashlib.sha256(c.encode()).hexdigest() for c in chunks] != expected[
                        "chunk_sha256"
                    ]:
                        raise ValueError("Source passages changed after plan")
                    async with async_session_factory() as session:
                        await lock_source(session, source)
                        current = await session.get(Document, doc.id)
                        if current is None:
                            same_url = (
                                await session.scalars(
                                    select(Document).where(Document.source_url == source.url)
                                )
                            ).all()
                            candidates = (
                                await session.scalars(
                                    select(Document).where(
                                        Document.source_type == "arret_cour_appel",
                                        Document.organisation_id.is_(None),
                                        Document.private_dossier_id.is_(None),
                                        Document.private_conversation_id.is_(None),
                                        Document.retired_at.is_(None),
                                        Document.date_decision == source.day,
                                        Document.juridiction == doc.juridiction,
                                    )
                                )
                            ).all()
                            keys = set(reference_aliases(source.numbers))
                            # Different full texts may be distinct decisions in the same case.
                            duplicates = [
                                d
                                for d in candidates
                                if d.file_hash == source.text_sha256
                                and keys.intersection(reference_aliases([d.numero_pourvoi or ""]))
                            ]
                            if same_url or duplicates:
                                raise ValueError(
                                    "Concurrent duplicate discovered; "
                                    "source requires reconciliation"
                                )
                            body = source.text.encode()
                            storage.put_file_bytes(
                                doc.storage_path, body, "text/plain; charset=utf-8"
                            )
                            storage.put_file_bytes(
                                doc.storage_path + ".source.json",
                                source.source_bytes,
                                "application/json",
                            )
                            if (
                                storage.get_file_bytes_bounded(doc.storage_path, len(body) + 1)
                                != body
                            ):
                                raise ValueError("Original CA text archive mismatch")
                            if (
                                storage.get_file_bytes_bounded(
                                    doc.storage_path + ".source.json", len(source.source_bytes) + 1
                                )
                                != source.source_bytes
                            ):
                                raise ValueError("Original CA JSON archive mismatch")
                            session.add(doc)
                            await session.commit()
                        else:
                            verified_ca_source(current, source.text.encode(), source.source_bytes)
                            if current.retired_at is not None:
                                raise ValueError("CA source was retired during import")
                    prepared.append((row, chunks, []))
                texts, owners, places, token_count = [], [], [], 0
                requests = []
                for pos, (row, chunks, _) in enumerate(prepared):
                    for chunk in chunks:
                        size = len(tokenizer.encode(chunk).ids)
                        if texts and (len(texts) == 128 or token_count + size > 80000):
                            requests.append((texts, owners, places))
                            texts, owners, places, token_count = [], [], [], 0
                        texts.append(chunk)
                        owners.append(row["document_id"])
                        places.append(pos)
                        token_count += size
                if texts:
                    requests.append((texts, owners, places))
                for texts, owners, places in requests:
                    vectors = await embedder.get(texts, owners)
                    for vector, pos in zip(vectors, places, strict=True):
                        prepared[pos][2].append(vector)

                async def publish(item):
                    row, chunks, vectors = item
                    if row["status"] == "indexed":
                        return

                    async def cached(texts, api_key, doc, session, **kwargs):
                        if texts != chunks or len(vectors) != len(chunks):
                            raise ValueError("Cached CA embeddings differ from exact source")
                        return vectors

                    async with publish_slots, async_session_factory() as session:
                        doc = await session.get(Document, uuid.UUID(row["document_id"]))
                        await IngestionPipeline(
                            embedding_provider=cached, storage=storage, qdrant_client=qdrant
                        ).ingest(doc.id, session, expected_source=doc.storage_path)
                        await session.refresh(doc)
                        if doc.indexation_status != "indexed" or doc.chunk_count != len(chunks):
                            raise ValueError("CA indexing failed: " + str(doc.indexation_error))

                results = await asyncio.gather(
                    *(publish(item) for item in prepared), return_exceptions=True
                )
                errors = []
                for (row, _, _), result in zip(prepared, results, strict=True):
                    if isinstance(result, Exception):
                        db.execute(
                            "UPDATE items SET status='error',error=? WHERE id=?",
                            (str(result), row["id"]),
                        )
                        errors.append(str(result))
                    else:
                        db.execute(
                            "UPDATE items SET status='indexed',error=NULL WHERE id=?", (row["id"],)
                        )
                db.commit()
                progress = {
                    "phase": "indexing",
                    "statuses": dict(
                        db.execute(
                            "SELECT status,count(*) FROM items "
                            "WHERE disposition='new' GROUP BY status"
                        )
                    ),
                    "confirmed_tokens": db.execute(
                        "SELECT coalesce(sum(actual),0) FROM requests WHERE status='success'"
                    ).fetchone()[0],
                }
                dump(root / "import-progress.json", progress)
                print(json.dumps(progress), flush=True)
                if errors:
                    raise ValueError("CA indexing failures; paid cache retained: " + errors[0])

            await run_batches(groups, process, args.concurrency)
        finally:
            await embedder.client.aclose()


async def verify(root, db, limit=None):
    storage = StorageService()
    qdrant = get_qdrant_client()
    rows = db.execute("SELECT * FROM items WHERE disposition='new' ORDER BY id").fetchall()
    if limit:
        rows = [r for r in rows if r["status"] == "indexed"][:limit]
    failures = []
    counts = Counter()
    for offset in range(0, len(rows), 64):
        group = rows[offset : offset + 64]
        ids = [r["document_id"] for r in group]
        async with async_session_factory() as session:
            docs = (
                await session.scalars(
                    select(Document).where(Document.id.in_([uuid.UUID(i) for i in ids]))
                )
            ).all()
        by_id = {str(d.id): d for d in docs}
        found = defaultdict(list)
        cursor = None
        while True:
            page, cursor = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(
                    must=[FieldCondition(key="document_id", match=MatchAny(any=ids))]
                ),
                limit=256,
                offset=cursor,
                with_payload=True,
                with_vectors=False,
            )
            for point in page:
                found[point.payload["document_id"]].append(point.payload)
            if cursor is None:
                break
        for row in group:
            try:
                source = read_source(root, row)
                doc = by_id.get(row["document_id"])
                if not doc or doc.indexation_status != "indexed" or doc.retired_at is not None:
                    raise ValueError("Missing, retired or unindexed CA document")
                body = storage.get_file_bytes_bounded(
                    doc.storage_path, len(source.text.encode()) + 1
                )
                sidecar = storage.get_file_bytes_bounded(
                    doc.storage_path + ".source.json", len(source.source_bytes) + 1
                )
                verified_ca_source(doc, body, sidecar)
                points = sorted(found[row["document_id"]], key=lambda p: p["chunk_index"])
                meta = json.loads(row["meta"])
                if len(points) != doc.chunk_count or [p["chunk_index"] for p in points] != list(
                    range(meta["chunks"])
                ):
                    raise ValueError("Missing or duplicate CA passages")
                if [hashlib.sha256(p["text"].encode()).hexdigest() for p in points] != meta[
                    "chunk_sha256"
                ]:
                    raise ValueError("CA passage text differs from full original source")
                if any(p.get(k) != value for p in points for k, value in source.metadata().items()):
                    raise ValueError("CA retrieval metadata differs from source")
                if any(
                    p.get("organisation_id") != "common"
                    or p.get("private")
                    or p.get("date_decision") != str(source.day)
                    or p.get("juridiction") != doc.juridiction
                    or p.get("chambre") != doc.chambre
                    for p in points
                ):
                    raise ValueError("CA source scope or decision metadata mismatch")
                counts.update(documents=1, passages=len(points))
            except Exception as exc:
                failures.append({"id": row["id"], "error": str(exc)})
        if offset % 1024 == 0:
            print(json.dumps({"verified": dict(counts), "failures": len(failures)}), flush=True)
    async with async_session_factory() as session:
        current = await public_documents(session)
    by_id = {str(d.id): d for d in current}
    baseline = json.loads((root / "baseline-documents.json").read_text())
    baseline_changes = [
        r["id"] for r in baseline if r["id"] not in by_id or snapshot(by_id[r["id"]]) != r
    ]
    urls = Counter(d.source_url for d in current if d.source_url and d.retired_at is None)
    duplicates = {url: n for url, n in urls.items() if n > 1}
    actual = db.execute(
        "SELECT coalesce(sum(actual),0) FROM requests WHERE status='success'"
    ).fetchone()[0]
    uncertain = db.execute(
        "SELECT coalesce(sum(reserved),0) FROM requests WHERE actual IS NULL"
    ).fetchone()[0]
    report = {
        "verified": dict(counts),
        "failures": failures,
        "baseline_documents_changed": baseline_changes,
        "duplicate_active_source_urls": duplicates,
        "dispositions": dict(
            db.execute("SELECT disposition,count(*) FROM items GROUP BY disposition")
        ),
        "statuses": dict(db.execute("SELECT status,count(*) FROM items GROUP BY status")),
        "confirmed_provider_tokens": actual,
        "unconfirmed_tokens_upper_bound": uncertain,
        "embedding_usd": actual * 0.12 / 1_000_000,
        "embedding_usd_upper_bound": (actual + uncertain) * 0.12 / 1_000_000,
    }
    dump(root / ("verify-sample.json" if limit else "verification.json"), report)
    print(json.dumps(report), flush=True)
    if failures or baseline_changes or duplicates:
        raise ValueError("CA verification failed; exact audit preserved")


async def main(args):
    os.umask(0o007)
    if args.tokens_per_minute < 1 or args.max_total_tokens < 1:
        raise ValueError("Provider pacing and total token budget must be positive")
    root = args.folder.resolve()
    db = state_db(root)
    tokenizer = Tokenizer.from_file(str(args.tokenizer))
    tokenizer.no_padding()
    tokenizer.no_truncation()
    try:
        if args.plan:
            await plan(root, db, tokenizer)
        if args.apply:
            await apply(root, db, tokenizer, args)
        if args.verify:
            await verify(root, db, args.verify_limit)
    finally:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--verify-limit", type=int)
    parser.add_argument("--limit-groups", type=int)
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--tokens-per-minute", type=int, default=2_000_000)
    parser.add_argument("--max-total-tokens", type=int, default=416_666_666)
    asyncio.run(main(parser.parse_args()))
