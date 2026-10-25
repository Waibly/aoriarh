"""Enrich existing social decisions from cached official B/R metadata.

Default: immutable read-only plan with source, PostgreSQL and Qdrant snapshots.
Apply: publication labels only, resumable after a partial dual-store update.
No document insertion, source write, embedding or model request is performed.
"""

import argparse
import asyncio
import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select, text

from app.core.database import async_session_factory, engine
from app.models.document import Document
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
from app.services.dila_cass_service import number_aliases
from app.services.jurisprudence_publication import judilibre_publication_label
from app.services.storage_service import StorageService


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def dump(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    temporary.replace(path)


def document_digest(doc):
    return digest(
        {
            column.key: getattr(doc, column.key)
            for column in Document.__table__.columns
            if column.key not in {"publication", "updated_at"}
        }
    )


def require_public_social(doc):
    if (
        doc is None
        or doc.organisation_id is not None
        or doc.private_dossier_id
        or doc.private_conversation_id
        or doc.retired_at is not None
        or doc.source_type != "arret_cour_cassation"
        or doc.chambre != "Chambre sociale"
        or doc.juridiction != "Cour de cassation"
        or doc.indexation_status != "indexed"
    ):
        raise ValueError("Document is not an active indexed public social decision")


def official_sources(path):
    source = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        complete = source.execute("SELECT value FROM state WHERE key='complete'").fetchone()
        if complete != ("1",):
            raise ValueError("Official inventory is incomplete")
        rows = []
        for identifier, metadata in source.execute("SELECT id,meta FROM items WHERE chamber='soc'"):
            raw = json.loads(metadata)
            codes = raw.get("publication") or []
            if "r" not in codes:
                continue
            if raw.get("jurisdiction") != "cc" or raw.get("chamber") != "soc":
                raise ValueError("Official record is outside social Cassation")
            date.fromisoformat(raw["decision_date"])
            rows.append(
                dict(
                    id=identifier,
                    date=raw["decision_date"],
                    publication=codes,
                    numbers=list(raw.get("numbers") or []) + [raw.get("number") or ""],
                )
            )
        return rows
    finally:
        source.close()


def match_sources(sources, docs):
    by_url, by_case = defaultdict(set), defaultdict(set)
    for doc in docs:
        require_public_social(doc)
        if doc.source_url:
            by_url[doc.source_url.rstrip("/")].add(str(doc.id))
        for alias in number_aliases(doc.numero_pourvoi or ""):
            by_case[(str(doc.date_decision), alias)].add(str(doc.id))
    matched = {}
    for source in sources:
        candidates = set(by_url.get("https://www.courdecassation.fr/decision/" + source["id"], ()))
        for number in source["numbers"]:
            for alias in number_aliases(number):
                candidates.update(by_case.get((source["date"], alias), ()))
        if len(candidates) != 1:
            raise ValueError("Official R identity is missing or ambiguous: " + source["id"])
        identifier = next(iter(candidates))
        resolved = next(doc for doc in docs if str(doc.id) == identifier)
        if str(resolved.date_decision) != source["date"]:
            raise ValueError("Official and stored decision dates differ")
        if identifier in matched:
            raise ValueError("Several official R records resolve to the same document")
        matched[identifier] = source
    return matched


def point_snapshot(points, doc):
    if len(points) != doc.chunk_count or not points:
        raise ValueError("Incomplete decision index")
    records = sorted(points, key=lambda p: p.payload["chunk_index"])
    if [p.payload["chunk_index"] for p in records] != list(range(len(records))):
        raise ValueError("Missing or duplicate decision passages")
    unchanged, publications = [], {}
    for point in records:
        payload = point.payload
        if (
            payload.get("document_id") != str(doc.id)
            or payload.get("organisation_id") != "common"
            or payload.get("private")
            or payload.get("source_type") != "arret_cour_cassation"
            or not point.vector
        ):
            raise ValueError("Invalid public decision point")
        record = point.model_dump(mode="json")
        publications[str(point.id)] = record["payload"].pop("publication", None)
        unchanged.append(record)
    return dict(unchanged_sha256=digest(unchanged), publications=publications, count=len(records))


def read_points(client, doc):
    points, cursor = [], None
    while True:
        page, cursor = client.scroll(
            COLLECTION_NAME,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=str(doc.id)))]
            ),
            limit=256,
            offset=cursor,
            with_payload=True,
            with_vectors=True,
        )
        points.extend(page)
        if cursor is None:
            return points


def source_digest(storage, doc):
    raw = storage.get_file_bytes_bounded(doc.storage_path, 16 * 1024 * 1024)
    checksum = hashlib.sha256(raw).hexdigest()
    if doc.file_hash and checksum != doc.file_hash:
        raise ValueError("Source object differs from its recorded hash")
    return checksum


async def plan(folder, inventory, expected_count):
    if (folder / "plan.json").exists():
        raise ValueError("Plan already exists; reuse it or prepare a separate work directory")
    sources = official_sources(inventory)
    async with async_session_factory() as session:
        docs = (
            await session.scalars(
                select(Document).where(
                    Document.source_type == "arret_cour_cassation",
                    Document.chambre == "Chambre sociale",
                    Document.organisation_id.is_(None),
                    Document.private_dossier_id.is_(None),
                    Document.private_conversation_id.is_(None),
                    Document.retired_at.is_(None),
                    Document.indexation_status == "indexed",
                )
            )
        ).all()
    matched = match_sources(sources, docs)
    if len(matched) != expected_count:
        raise ValueError(f"Expected {expected_count} R documents, found {len(matched)}")
    storage, client = StorageService(), get_qdrant_client()
    items = []
    for doc in docs:
        if str(doc.id) not in matched:
            continue
        source = matched[str(doc.id)]
        items.append(
            dict(
                document_id=str(doc.id),
                official_source=source,
                before_publication=doc.publication,
                target_publication=judilibre_publication_label(source["publication"]),
                document_sha256=document_digest(doc),
                source_sha256=source_digest(storage, doc),
                points=point_snapshot(read_points(client, doc), doc),
            )
        )
    result = dict(
        expected_count=expected_count,
        source_inventory_sha256=hashlib.file_digest(inventory.open("rb"), "sha256").hexdigest(),
        items=items,
    )
    dump(folder / "plan.json", result)
    print(
        json.dumps(
            dict(
                planned_documents=len(items),
                planned_passages=sum(item["points"]["count"] for item in items),
                external_model_calls=0,
            )
        ),
        flush=True,
    )


def check_snapshot(doc, points, item, storage, *, final=False):
    require_public_social(doc)
    current = point_snapshot(points, doc)
    if (
        document_digest(doc) != item["document_sha256"]
        or current["unchanged_sha256"] != item["points"]["unchanged_sha256"]
        or source_digest(storage, doc) != item["source_sha256"]
    ):
        raise ValueError("Source, vectors or metadata other than publication changed")
    allowed = (
        {item["target_publication"]}
        if final
        else {item["before_publication"], item["target_publication"]}
    )
    if doc.publication not in allowed:
        raise ValueError("Concurrent document publication change")
    for identifier, value in current["publications"].items():
        labels = (
            {item["target_publication"]}
            if final
            else {item["points"]["publications"][identifier], item["target_publication"]}
        )
        if value not in labels:
            raise ValueError("Concurrent point publication change")


async def apply(folder, plan_data):
    storage, client = StorageService(), get_qdrant_client()
    completed = []
    async with engine.begin() as lock:
        if not await lock.scalar(text("SELECT pg_try_advisory_xact_lock(20261025,1)")):
            raise ValueError("Another Cassation maintenance operation is active")
        for item in plan_data["items"]:
            async with async_session_factory() as session:
                doc = await session.scalar(
                    select(Document)
                    .where(Document.id == uuid.UUID(item["document_id"]))
                    .with_for_update()
                )
                require_public_social(doc)
                points = read_points(client, doc)
                check_snapshot(doc, points, item, storage)
                client.set_payload(
                    COLLECTION_NAME,
                    payload={"publication": item["target_publication"]},
                    points=[point.id for point in points],
                    wait=True,
                )
                doc.publication = item["target_publication"]
                check_snapshot(doc, read_points(client, doc), item, storage, final=True)
                await session.commit()
            completed.append(item["document_id"])
            dump(folder / "progress.json", dict(completed=completed, external_model_calls=0))
    print(json.dumps(dict(updated_documents=len(completed), external_model_calls=0)), flush=True)


async def verify(folder, plan_data):
    storage, client = StorageService(), get_qdrant_client()
    passages = 0
    async with async_session_factory() as session:
        for item in plan_data["items"]:
            doc = await session.get(Document, uuid.UUID(item["document_id"]))
            require_public_social(doc)
            points = read_points(client, doc)
            check_snapshot(doc, points, item, storage, final=True)
            passages += len(points)
    result = dict(
        verified_documents=len(plan_data["items"]),
        verified_passages=passages,
        unchanged_source_bytes=True,
        unchanged_vectors=True,
        unchanged_passage_text=True,
        unchanged_other_metadata=True,
        external_model_calls=0,
        embedding_usd=0,
    )
    dump(folder / "verification.json", result)
    print(json.dumps(result), flush=True)


async def main(args):
    folder = Path(args.workdir)
    folder.mkdir(parents=True, exist_ok=True)
    if args.apply or args.verify:
        saved = json.loads((folder / "plan.json").read_text())
        if (
            len(saved["items"]) != args.expected_count
            or saved["expected_count"] != args.expected_count
        ):
            raise ValueError("Unexpected publication update scope")
        if len({item["document_id"] for item in saved["items"]}) != args.expected_count:
            raise ValueError("Duplicate planned document identity")
        for item in saved["items"]:
            codes = item["official_source"]["publication"]
            if (
                "r" not in codes
                or item["target_publication"] != judilibre_publication_label(codes)
                or len(item["target_publication"]) > 50
            ):
                raise ValueError("Invalid official R publication target")
        if args.apply:
            await apply(folder, saved)
        await verify(folder, saved)
    else:
        await plan(folder, Path(args.inventory), args.expected_count)
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--inventory")
    parser.add_argument("--expected-count", type=int, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.expected_count < 1 or (not args.apply and not args.verify and not args.inventory):
        parser.error("A positive count and an inventory for planning are required")
    asyncio.run(main(args))
