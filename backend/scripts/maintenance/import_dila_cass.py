"""Reconcile, ingest and verify an immutable social/Bulletin CASS package.

Default mode is a production read-only plan. --apply runs a bounded importer;
--verify checks every admitted document and every newly indexed source passage.
Work files must live in a persistent, private operator directory mounted in the
one-off worker container. No automatic LLM evaluation or generation is used.
"""

import argparse
import asyncio
import base64
import gzip
import hashlib
import json
import math
import re
import shutil
import sqlite3
import struct
import tarfile
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from lxml import etree
from sqlalchemy import select, text
from tokenizers import Tokenizer

from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.models.document import Document
from app.rag.config import EMBEDDING_MODEL
from app.rag.ingestion import IngestionPipeline
from app.rag.qdrant_store import COLLECTION_NAME, ensure_collection, get_qdrant_client
from app.services.cost_tracker import cost_tracker
from app.services.dila_cass_service import (
    SOURCE_PREFIX,
    number_aliases,
    parse_cass_xml,
    source_chunks,
    topic_scope,
)
from app.services.storage_service import StorageService


def dump(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    temporary.replace(path)


def state_db(folder):
    db = sqlite3.connect(folder / "import-state.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, xml BLOB, meta TEXT, "
        "document_id TEXT, disposition TEXT, status TEXT, error TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, reserved INTEGER, "
        "actual INTEGER, status TEXT, error TEXT)"
    )
    db.commit()
    return db


def identities(numbers, day):
    return {(str(day), key) for value in numbers for key in number_aliases(value)}


def decode_embedding(encoded):
    """Decode the provider's lossless float32 transport representation."""
    if not isinstance(encoded, str):
        raise ValueError("Expected a base64 float32 embedding")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) != 1024 * 4:
        raise ValueError("Invalid float32 embedding byte count")
    vector = list(struct.unpack("<1024f", raw))
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Non-finite float32 embedding")
    return vector


def doc_for(decision):
    return Document(
        id=uuid.uuid5(
            uuid.NAMESPACE_URL, "https://www.legifrance.gouv.fr/juri/id/" + decision.source_id
        ),
        organisation_id=None,
        source_type="arret_cour_cassation",
        norme_niveau=4,
        norme_poids=0.85,
        name=decision.title,
        storage_path=f"{SOURCE_PREFIX}{decision.source_id}/{decision.xml_sha256}.xml",
        file_format="xml",
        file_hash=decision.xml_sha256,
        juridiction="Cour de cassation",
        chambre="Chambre sociale",
        formation=None,
        numero_pourvoi=decision.numbers[0] if decision.numbers else None,
        date_decision=decision.decision_date,
        solution=decision.solution[:200],
        publication="Publié au Bulletin",
        indexation_status="pending",
        source_url="https://www.legifrance.gouv.fr/juri/id/" + decision.source_id,
    )


def prepared_chunks(decision, doc):
    header = IngestionPipeline._build_jurisprudence_header(doc) + "\n\n"
    bodies = source_chunks(decision.text)
    if "".join(bodies) != decision.text:
        raise ValueError("Source passages do not reconstruct the complete source")
    return [header + part for part in bodies]


async def plan(folder, package, db, tokenizer):
    async with async_session_factory() as session:
        existing = (
            await session.scalars(
                select(Document).where(
                    Document.organisation_id.is_(None),
                    Document.private_dossier_id.is_(None),
                    Document.private_conversation_id.is_(None),
                    Document.source_type == "arret_cour_cassation",
                    Document.chambre == "Chambre sociale",
                )
            )
        ).all()
    by_url = defaultdict(set)
    by_alias = defaultdict(set)
    by_id = {str(doc.id): doc for doc in existing}
    for doc in existing:
        if doc.source_url:
            by_url[doc.source_url.rstrip("/")].add(str(doc.id))
        for key in identities([doc.numero_pourvoi or ""], doc.date_decision):
            by_alias[key].add(str(doc.id))
    dump(
        folder / "baseline-documents.json",
        [
            {
                "id": str(doc.id),
                "date": str(doc.date_decision),
                "number": doc.numero_pourvoi,
                "source_url": doc.source_url,
                "file_hash": doc.file_hash,
                "status": doc.indexation_status,
                "chunk_count": doc.chunk_count,
                "retired": doc.retired_at is not None,
            }
            for doc in existing
        ],
    )
    counts = Counter()
    topics = Counter()
    tokens = 0
    seen_aliases = {}
    for identifier, metadata in db.execute("SELECT id,meta FROM items WHERE disposition='new'"):
        previous = json.loads(metadata)
        for key in identities(previous["numbers"], previous["date"]):
            seen_aliases[key] = identifier
    source_ids = set()
    parser_errors = []
    with tarfile.open(package, mode="r|gz") as archive:
        for member in archive:
            if not member.isfile():
                raise ValueError("Selected package must contain regular XML files only")
            raw = archive.extractfile(member).read()
            try:
                decision = parse_cass_xml(raw)
            except Exception as exc:
                if isinstance(exc, ValueError) and str(exc) == "dila_empty_decision_body":
                    root = etree.fromstring(
                        raw,
                        etree.XMLParser(
                            resolve_entities=False,
                            no_network=True,
                            load_dtd=False,
                        ),
                    )
                    identifier = root.findtext("META/META_COMMUN/ID") or ""
                    if (
                        not re.fullmatch(r"JURITEXT\d{12}", identifier)
                        or member.name != identifier + ".xml"
                        or identifier in source_ids
                    ):
                        raise ValueError("Invalid technical-review source identity") from exc
                    source_ids.add(identifier)
                    metadata = {
                        "source_id": identifier,
                        "date": root.findtext("META/META_SPEC/META_JURI/DATE_DEC"),
                        "numbers": [],
                        "technical_error": str(exc),
                        "xml_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                    db.execute(
                        "INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?)",
                        (
                            identifier,
                            raw,
                            json.dumps(metadata),
                            str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    "https://www.legifrance.gouv.fr/juri/id/" + identifier,
                                )
                            ),
                            "review_source_body_missing",
                            "error",
                            str(exc),
                        ),
                    )
                    counts["review_source_body_missing"] += 1
                    continue
                parser_errors.append({"member": member.name, "error": str(exc)})
                continue
            if member.name != decision.source_id + ".xml" or decision.source_id in source_ids:
                raise ValueError("Invalid or repeated package identity")
            source_ids.add(decision.source_id)
            previous = db.execute(
                "SELECT xml FROM items WHERE id=?", (decision.source_id,)
            ).fetchone()
            if previous:
                if previous[0] != raw:
                    raise ValueError("Source version changed; prepare a separate immutable plan")
                counts["already_planned"] += 1
                continue
            doc = doc_for(decision)
            aliases = identities(decision.numbers, decision.decision_date)
            matches = set(by_url.get(doc.source_url, set()))
            for key in aliases:
                matches.update(by_alias.get(key, set()))
            scope = topic_scope(decision.topics)
            conflicts = {seen_aliases[key] for key in aliases if key in seen_aliases}
            if len(matches) > 1:
                disposition = "review_existing_identity_conflict"
            elif matches:
                match_id = next(iter(matches))
                matched = by_id[match_id]
                if matched.retired_at is None and matched.indexation_status == "indexed":
                    disposition = "existing"
                elif (
                    matched.retired_at is None
                    and matched.id == doc.id
                    and matched.file_hash == decision.xml_sha256
                    and matched.storage_path == doc.storage_path
                ):
                    disposition = "new"
                else:
                    disposition = "review_existing_state"
                doc.id = matched.id
            elif conflicts:
                disposition = "review_archive_identity_conflict"
            elif scope.startswith("admitted"):
                disposition = "new"
            else:
                disposition = scope
            chunks = prepared_chunks(decision, doc)
            chunk_tokens = [len(item.ids) for item in tokenizer.encode_batch(chunks)]
            if any(count > 16000 for count in chunk_tokens):
                raise ValueError("A complete source passage exceeds Voyage context")
            estimate = sum(chunk_tokens)
            metadata = {
                "source_id": decision.source_id,
                "date": str(decision.decision_date),
                "numbers": decision.numbers,
                "topics": decision.topics,
                "scope": scope,
                "xml_sha256": decision.xml_sha256,
                "text_sha256": decision.text_sha256,
                "visible_source_sha256": decision.visible_source_sha256,
                "table_count": decision.table_count,
                "chunk_count": len(chunks),
                "estimated_tokens": estimate,
                "chunk_sha256": [hashlib.sha256(c.encode()).hexdigest() for c in chunks],
                "alias_conflicts": sorted(conflicts),
            }
            db.execute(
                "INSERT INTO items VALUES (?,?,?,?,?,?,NULL)",
                (
                    decision.source_id,
                    raw,
                    json.dumps(metadata, ensure_ascii=False),
                    str(doc.id),
                    disposition,
                    "existing" if disposition == "existing" else "pending",
                ),
            )
            counts[disposition] += 1
            if disposition == "new":
                tokens += estimate
                for key in aliases:
                    seen_aliases[key] = decision.source_id
            if disposition.startswith("review"):
                topics.update(decision.topics[:1] or ["(no topic)"])
            if sum(counts.values()) % 1000 == 0:
                db.commit()
                print(
                    json.dumps({"planned": sum(counts.values()), "counts": dict(counts)}),
                    flush=True,
                )
    db.commit()
    actual_counts = dict(db.execute("SELECT disposition,count(*) FROM items GROUP BY disposition"))
    tokens = db.execute(
        "SELECT coalesce(sum(json_extract(meta,'$.estimated_tokens')),0) "
        "FROM items WHERE disposition='new'"
    ).fetchone()[0]
    summary = {
        "counts": actual_counts,
        "new_estimated_provider_tokens": tokens,
        "new_estimated_usd": round(tokens * 0.12 / 1_000_000, 4),
        "review_topics": topics.most_common(),
        "parser_errors": parser_errors,
        "package_sha256": hashlib.file_digest(package.open("rb"), "sha256").hexdigest(),
        "model": EMBEDDING_MODEL,
    }
    dump(folder / "plan.json", summary)
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "review_topics"},
            ensure_ascii=False,
        ),
        flush=True,
    )
    if parser_errors:
        raise ValueError("Source parsing errors require investigation")


def reconcile_exact_duplicates(folder, db):
    """Hold redundant publications, retaining distinct case references or dates.

    Keep their slots in paid batch ordering so a resumed batch has the same
    inputs. Never remove or silently rewrite a previously indexed document.
    """
    seen = {}
    duplicates = []
    rows = db.execute(
        "SELECT id,meta,status,disposition FROM items "
        "WHERE disposition IN ('new','review_exact_duplicate') ORDER BY id"
    ).fetchall()
    for row in rows:
        meta = json.loads(row["meta"])
        references = tuple(
            sorted({alias for number in meta["numbers"] for alias in number_aliases(number)})
        )
        key = (meta["date"], references, meta["text_sha256"])
        previous = seen.get(key)
        if previous is None:
            seen[key] = row["id"]
            continue
        if row["status"] == "indexed":
            raise ValueError("An indexed exact duplicate requires explicit investigation")
        duplicates.append({"source_id": row["id"], "same_text_and_identity_as": previous})
        db.execute(
            "UPDATE items SET disposition='review_exact_duplicate',status='excluded' WHERE id=?",
            (row["id"],),
        )
    db.commit()
    dump(folder / "exact-duplicates.json", duplicates)
    return duplicates


class Embeddings:
    def __init__(self, folder, state, tokenizer, tokens_per_minute, max_total_tokens):
        self.folder, self.state, self.tokenizer = folder, state, tokenizer
        self.tokens_per_minute = tokens_per_minute
        self.max_total_tokens = max_total_tokens
        self.next_request = 0.0
        self.pacing_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(timeout=90)
        (folder / "embedding-cache").mkdir(exist_ok=True)

    async def get(self, texts, owners):
        digest = hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()
        cache = self.folder / "embedding-cache" / (digest + ".json.gz")
        if cache.exists():
            with gzip.open(cache, "rt") as handle:
                saved = json.load(handle)
            if saved.get("input_digest") != digest or saved.get("model") != EMBEDDING_MODEL:
                raise ValueError("Paid embedding cache source mismatch")
            vectors = saved["vectors"]
            if len(vectors) != len(texts) or any(
                len(vector) != 1024 or not all(math.isfinite(v) for v in vector)
                for vector in vectors
            ):
                raise ValueError("Invalid cached embeddings")
            self.state.execute(
                "UPDATE requests SET actual=?,status='success' WHERE id=?",
                (saved["usage_tokens"], saved["request_id"]),
            )
            self.state.commit()
            return vectors
        estimated = sum(len(item.ids) for item in self.tokenizer.encode_batch(texts))
        if len(texts) > 128 or estimated > 80000:
            raise ValueError("Embedding request exceeds the importer batch contract")
        for attempt in range(3):
            reserved = self.state.execute(
                "SELECT coalesce(sum(reserved),0) FROM requests"
            ).fetchone()[0]
            if reserved + estimated > self.max_total_tokens:
                raise ValueError("Explicit import token budget reached; state is preserved")
            async with self.pacing_lock:
                while self.next_request > time.monotonic():
                    await asyncio.sleep(self.next_request - time.monotonic())
                self.next_request = time.monotonic() + max(
                    2, 60 * estimated / self.tokens_per_minute
                )
                # Other concurrent groups may have reserved their request while
                # this group waited for its provider slot.
                reserved = self.state.execute(
                    "SELECT coalesce(sum(reserved),0) FROM requests"
                ).fetchone()[0]
                if reserved + estimated > self.max_total_tokens:
                    raise ValueError("Explicit import token budget reached; state is preserved")
            request_id = digest + ":" + str(attempt)
            previous = self.state.execute(
                "SELECT status FROM requests WHERE id=?", (request_id,)
            ).fetchone()
            if previous is not None:
                if previous[0] in {"in_flight", "success", "uncertain"}:
                    raise ValueError("Uncached or uncertain paid request requires investigation")
                continue
            self.state.execute(
                "INSERT INTO requests VALUES (?,?,NULL,'in_flight',NULL)", (request_id, estimated)
            )
            self.state.commit()
            try:
                response = await self.client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={"Authorization": "Bearer " + settings.voyage_api_key},
                    json={
                        "input": texts,
                        "model": EMBEDDING_MODEL,
                        "truncation": False,
                        "encoding_format": "base64",
                    },
                )
                if response.status_code == 429:
                    self.state.execute(
                        "UPDATE requests SET status='rate_limited',reserved=0 WHERE id=?",
                        (request_id,),
                    )
                    self.state.commit()
                    try:
                        delay = float(response.headers.get("Retry-After", 60 * (attempt + 1)))
                    except ValueError:
                        delay = 60 * (attempt + 1)
                    self.next_request = max(self.next_request, time.monotonic() + max(1, delay))
                    print(
                        json.dumps({"provider_rate_limited": True, "retry_after_seconds": delay}),
                        flush=True,
                    )
                    continue
                response.raise_for_status()
                data = response.json()
                entries = sorted(data["data"], key=lambda entry: entry["index"])
                if [entry["index"] for entry in entries] != list(range(len(texts))):
                    raise ValueError("Incomplete or duplicated embedding response")
                vectors = [decode_embedding(entry["embedding"]) for entry in entries]
                if any(
                    len(vector) != 1024 or not all(math.isfinite(v) for v in vector)
                    for vector in vectors
                ):
                    raise ValueError("Invalid embedding dimensions or values")
                actual = data["usage"]["total_tokens"]
                temporary = cache.with_suffix(".tmp")
                with gzip.open(temporary, "wt") as handle:
                    json.dump(
                        {
                            "vectors": vectors,
                            "usage_tokens": actual,
                            "input_digest": digest,
                            "model": EMBEDDING_MODEL,
                            "request_id": request_id,
                        },
                        handle,
                    )
                temporary.replace(cache)
                self.state.execute(
                    "UPDATE requests SET actual=?,status='success' WHERE id=?", (actual, request_id)
                )
                self.state.commit()
                weights = Counter()
                for owner, count in zip(owners, self.tokenizer.encode_batch(texts), strict=True):
                    weights[owner] += len(count.ids)
                remaining = actual
                for i, (owner, weight) in enumerate(weights.items()):
                    allocated = (
                        remaining
                        if i == len(weights) - 1
                        else actual * weight // sum(weights.values())
                    )
                    remaining -= allocated
                    await cost_tracker.log(
                        provider="voyageai",
                        model=EMBEDDING_MODEL,
                        operation_type="embedding",
                        tokens_input=allocated,
                        context_type="ingestion",
                        context_id=owner,
                    )
                quota_headers = {
                    key: value
                    for key, value in response.headers.items()
                    if "ratelimit" in key.lower() or "rate-limit" in key.lower()
                }
                print(
                    json.dumps(
                        {
                            "embedded_passages": len(texts),
                            "actual_tokens": actual,
                            "quota_headers": quota_headers,
                        }
                    ),
                    flush=True,
                )
                return vectors
            except Exception as exc:
                self.state.execute(
                    "UPDATE requests SET status=?,error=? WHERE id=?",
                    (
                        "error" if isinstance(exc, httpx.HTTPStatusError) else "uncertain",
                        type(exc).__name__,
                        request_id,
                    ),
                )
                self.state.commit()
                raise
        raise RuntimeError("Voyage rate limit persisted after three bounded attempts")


async def run_batches(groups, handler, concurrency):
    """Stop taking work after an error, allowing paid in-flight work to settle."""
    pending = iter(groups)
    failed = asyncio.Event()

    async def worker():
        while not failed.is_set():
            group = next(pending, None)
            if group is None:
                return
            try:
                await handler(group)
            except Exception:
                failed.set()
                raise

    results = await asyncio.gather(*(worker() for _ in range(concurrency)), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            raise result


async def apply(folder, db, tokenizer, args):
    storage = StorageService()
    qdrant = get_qdrant_client()
    ensure_collection(qdrant)
    embedder = Embeddings(folder, db, tokenizer, args.tokens_per_minute, args.max_total_tokens)
    stats = Counter()
    if shutil.disk_usage(folder).free < 20 * 2**30:
        raise ValueError("Insufficient disk reserve for import")
    async with engine.begin() as lock_connection:
        locked = await lock_connection.scalar(text("SELECT pg_try_advisory_xact_lock(20261025, 1)"))
        if not locked:
            raise ValueError("A CASS backfill is already active")
        try:
            reconcile_exact_duplicates(folder, db)
            # Keep paid batches stable across restarts, including a partially
            # published group. Completed groups are skipped without paid calls.
            rows = db.execute(
                "SELECT * FROM items WHERE disposition IN "
                "('new','review_exact_duplicate','review_scope',"
                "'duplicate_existing','review_alias_collision') "
                "ORDER BY id"
            ).fetchall()
            if args.limit:
                rows = rows[: args.limit]
            semaphore = asyncio.Semaphore(6)

            async def process_group(group):
                if (folder / "STOP").exists():
                    raise ValueError("Operator stop requested; in-flight batches will settle")
                if all(row["status"] in {"indexed", "excluded"} for row in group):
                    return
                prepared = []
                for row in group:
                    if row["disposition"] != "new":
                        continue
                    decision = parse_cass_xml(row["xml"])
                    doc = doc_for(decision)
                    if str(doc.id) != row["document_id"]:
                        raise ValueError("Planned document identity changed")
                    chunks = prepared_chunks(decision, doc)
                    expected = json.loads(row["meta"])
                    if [hashlib.sha256(c.encode()).hexdigest() for c in chunks] != expected[
                        "chunk_sha256"
                    ]:
                        raise ValueError("Source representation changed after planning")
                    async with async_session_factory() as session:
                        current = await session.get(Document, doc.id)
                        if current is None:
                            # Recheck exact source and case/date against current public documents.
                            candidates = (
                                await session.scalars(
                                    select(Document).where(
                                        Document.organisation_id.is_(None),
                                        Document.source_type == "arret_cour_cassation",
                                        Document.chambre == "Chambre sociale",
                                        Document.date_decision == decision.decision_date,
                                    )
                                )
                            ).all()
                            keys = identities(decision.numbers, decision.decision_date)
                            if any(
                                candidate.source_url == doc.source_url
                                or keys
                                & identities(
                                    [candidate.numero_pourvoi or ""], candidate.date_decision
                                )
                                for candidate in candidates
                            ):
                                raise ValueError("Concurrent or unresolved duplicate identity")
                            storage.put_file_bytes(doc.storage_path, row["xml"], "application/xml")
                            if (
                                storage.get_file_bytes_bounded(
                                    doc.storage_path, len(row["xml"]) + 1
                                )
                                != row["xml"]
                            ):
                                raise ValueError("Original XML archive verification failed")
                            doc.file_size = len(row["xml"])
                            session.add(doc)
                            await session.commit()
                        else:
                            if (
                                current.file_hash != decision.xml_sha256
                                or current.retired_at is not None
                            ):
                                raise ValueError("Existing source changed or retired")
                    prepared.append((row, chunks, []))
                # Provider batches are limited by its tokenizer as well as input count.
                requests = []
                flat = []
                owners = []
                count = 0
                locations = []
                for item_index, (row, chunks, _) in enumerate(prepared):
                    for chunk in chunks:
                        size = len(tokenizer.encode(chunk).ids)
                        if flat and (len(flat) >= 128 or count + size > 80000):
                            requests.append((flat, owners, locations))
                            flat, owners, locations, count = [], [], [], 0
                        flat.append(chunk)
                        owners.append(row["document_id"])
                        locations.append(item_index)
                        count += size
                if flat:
                    requests.append((flat, owners, locations))
                for texts, owners, locations in requests:
                    vectors = await embedder.get(texts, owners)
                    for vector, location in zip(vectors, locations, strict=True):
                        prepared[location][2].append(vector)

                async def publish(item):
                    row, chunks, vectors = item
                    if row["status"] == "indexed":
                        return row["id"]

                    async def cached(texts, api_key, doc, session, **kwargs):
                        if texts != chunks or len(vectors) != len(texts):
                            raise ValueError("Paid embeddings do not match current source passages")
                        return vectors

                    async with semaphore, async_session_factory() as session:
                        pipeline = IngestionPipeline(
                            embedding_provider=cached, storage=storage, qdrant_client=qdrant
                        )
                        doc = await session.get(Document, uuid.UUID(row["document_id"]))
                        await pipeline.ingest(doc.id, session, expected_source=doc.storage_path)
                        await session.refresh(doc)
                        if doc.indexation_status != "indexed" or doc.chunk_count != len(chunks):
                            raise ValueError(
                                "Document indexing failed: " + str(doc.indexation_error)
                            )
                        return row["id"]

                results = await asyncio.gather(
                    *(publish(item) for item in prepared), return_exceptions=True
                )
                for (row, _, _), result in zip(prepared, results, strict=True):
                    if isinstance(result, Exception):
                        db.execute(
                            "UPDATE items SET status='error',error=? WHERE id=?",
                            (str(result), row["id"]),
                        )
                        stats["errors"] += 1
                    else:
                        db.execute(
                            "UPDATE items SET status='indexed',error=NULL WHERE id=?", (row["id"],)
                        )
                        stats["indexed"] += 1
                db.commit()
                remaining = db.execute(
                    "SELECT count(*) FROM items WHERE disposition='new' AND status!='indexed'"
                ).fetchone()[0]
                dump(
                    folder / "progress.json",
                    {"counts": dict(stats), "remaining": remaining},
                )
                print(
                    json.dumps({"published": dict(stats), "remaining": remaining}),
                    flush=True,
                )
                if stats["errors"]:
                    raise ValueError(
                        "Indexing errors require investigation; paid embeddings are cached"
                    )
                if shutil.disk_usage(folder).free < 20 * 2**30:
                    raise ValueError("Import paused before disk reserve was exhausted")

            groups = [rows[offset : offset + 32] for offset in range(0, len(rows), 32)]
            await run_batches(groups, process_group, args.concurrency)
        finally:
            await embedder.client.aclose()


async def verify(folder, db, limit=None):
    storage = StorageService()
    qdrant = get_qdrant_client()
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    counts = Counter()
    failures = []
    rows = db.execute(
        "SELECT * FROM items WHERE disposition IN ('new','existing','duplicate_existing') "
        "ORDER BY id"
    ).fetchall()
    if limit is not None:
        rows = [row for row in rows if row["disposition"] == "new" and row["status"] == "indexed"][
            :limit
        ]
    for offset in range(0, len(rows), 64):
        group = rows[offset : offset + 64]
        ids = [row["document_id"] for row in group]
        async with async_session_factory() as session:
            docs = (
                await session.scalars(
                    select(Document).where(Document.id.in_([uuid.UUID(i) for i in ids]))
                )
            ).all()
        by_id = {str(doc.id): doc for doc in docs}
        points = defaultdict(list)
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
                points[point.payload["document_id"]].append(point.payload)
            if cursor is None:
                break
        for row in group:
            doc = by_id.get(row["document_id"])
            found = sorted(points[row["document_id"]], key=lambda point: point["chunk_index"])
            error = None
            if doc is None or doc.indexation_status != "indexed" or doc.retired_at is not None:
                error = "missing_or_unindexed_document"
            elif (
                doc.organisation_id is not None
                or doc.private_dossier_id
                or doc.private_conversation_id
            ):
                error = "invalid_public_scope"
            elif len(found) != doc.chunk_count or [point["chunk_index"] for point in found] != list(
                range(doc.chunk_count)
            ):
                error = "missing_or_duplicate_passages"
            elif any(
                point.get("organisation_id") != "common" or point.get("private") for point in found
            ):
                error = "invalid_vector_scope"
            elif row["disposition"] == "new":
                expected = json.loads(row["meta"])
                if [
                    hashlib.sha256(point["text"].encode()).hexdigest() for point in found
                ] != expected["chunk_sha256"]:
                    error = "source_passage_content_mismatch"
                elif (
                    storage.get_file_bytes_bounded(doc.storage_path, len(row["xml"]) + 1)
                    != row["xml"]
                ):
                    error = "original_xml_content_mismatch"
            if error:
                failures.append(
                    {"id": row["id"], "document_id": row["document_id"], "error": error}
                )
            else:
                counts[row["disposition"]] += 1
        if offset % 1024 == 0:
            print(
                json.dumps({"verified": sum(counts.values()), "errors": len(failures)}), flush=True
            )
    report = {
        "verified": dict(counts),
        "failures": failures,
        "dispositions": dict(
            db.execute("SELECT disposition,count(*) FROM items GROUP BY disposition")
        ),
        "provider_tokens": db.execute(
            "SELECT coalesce(sum(actual),0) FROM requests WHERE status='success'"
        ).fetchone()[0],
    }
    report["embedding_usd"] = round(report["provider_tokens"] * 0.12 / 1_000_000, 6)
    report["unconfirmed_provider_tokens_upper_bound"] = db.execute(
        "SELECT coalesce(sum(reserved),0) FROM requests WHERE actual IS NULL"
    ).fetchone()[0]
    report["embedding_usd_upper_bound"] = round(
        (report["provider_tokens"] + report["unconfirmed_provider_tokens_upper_bound"])
        * 0.12
        / 1_000_000,
        6,
    )
    report["pilot_only"] = limit is not None
    dump(folder / ("verification-pilot.json" if limit is not None else "verification.json"), report)
    print(json.dumps(report), flush=True)
    if failures:
        raise ValueError("Import verification failed")


async def main(args):
    folder = Path(args.workdir)
    folder.mkdir(parents=True, exist_ok=True)
    db = state_db(folder)
    tokenizer = Tokenizer.from_file(str(folder / "voyage-law-2-tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    if EMBEDDING_MODEL != "voyage-law-2":
        raise ValueError("Import plan requires the current production embedding model")
    if args.verify:
        await verify(folder, db, args.limit)
    elif args.apply:
        if not (folder / "plan.json").exists():
            raise ValueError("A reconciled import plan is required")
        import_plan = json.loads((folder / "plan.json").read_text())
        if import_plan.get("parser_errors"):
            raise ValueError("Source parsing errors must be resolved before importing")
        await apply(folder, db, tokenizer, args)
    else:
        if db.execute("SELECT 1 FROM requests LIMIT 1").fetchone():
            raise ValueError("The source plan is immutable once paid indexing has begun")
        await plan(folder, folder / "selected-social-bulletin.tar.gz", db, tokenizer)
    db.close()
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--tokens-per-minute", type=int, default=300_000)
    parser.add_argument("--max-total-tokens", type=int, default=250_000_000)
    args = parser.parse_args()
    if (
        not 1 <= args.concurrency <= 4
        or args.tokens_per_minute < 1
        or args.max_total_tokens < 1
        or (args.limit is not None and args.limit < 1)
    ):
        parser.error("Budgets and limits must be positive")
    asyncio.run(main(args))
