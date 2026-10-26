"""Add official summaries to historical public sources with identity/version checks."""

import hashlib
import json
import uuid
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update

from app.models.document import Document
from app.models.judilibre import JudilibreRecord
from app.rag.tasks import enqueue_ingestion
from app.services.dila_cass_service import canonical_number
from app.services.judilibre_service import JudilibreService
from app.services.judilibre_source import official_summaries, render_judilibre_source
from app.services.storage_service import StorageService


def same_identity(raw: dict, doc: Document) -> bool:
    if not doc.date_decision or not canonical_number(doc.numero_pourvoi or ""):
        return False
    numbers = [raw.get("number", ""), *(raw.get("numbers") or [])]
    return (raw.get("decision_date") == str(doc.date_decision)
            and canonical_number(doc.numero_pourvoi or "") in {
                canonical_number(value) for value in numbers if isinstance(value, str)
            })


async def refresh_judilibre_source(db, document_id, *, apply=False, service=None, storage=None):
    doc = await db.get(Document, document_id)
    if (doc is None or doc.organisation_id is not None or doc.private_conversation_id is not None
            or doc.private_dossier_id is not None or doc.retired_at is not None
            or doc.source_type != "arret_cour_cassation"
            or not doc.storage_path.startswith("common/judilibre/")):
        raise ValueError("judilibre_maintenance_outside_public_scope")
    service = service or JudilibreService()
    storage = storage or StorageService()
    old_path, old_hash = doc.storage_path, doc.file_hash
    source_id = await db.scalar(select(JudilibreRecord.source_id).where(
        JudilibreRecord.document_id == doc.id,
    ))
    url = urlparse(doc.source_url or "")
    if not source_id and url.hostname == "www.courdecassation.fr":
        source_id = (url.path.removeprefix("/decision/")
                     if url.path.startswith("/decision/") else None)
    async with httpx.AsyncClient(timeout=30) as client:
        if not source_id:
            found = await service._api_get(client, "/search", {
                "query": doc.numero_pourvoi, "jurisdiction": "cc", "page_size": 50,
            })
            candidates = [r for r in (found or {}).get("results", []) if same_identity(r, doc)]
            if len(candidates) != 1:
                raise ValueError("judilibre_maintenance_ambiguous_identity")
            source_id = candidates[0]["id"]
        raw = await service._api_get(client, "/decision", {"id": source_id})
    if not raw or not same_identity(raw, doc):
        raise ValueError("judilibre_maintenance_identity_mismatch")
    rendered = render_judilibre_source(raw).encode("utf-8")
    original = storage.get_file_bytes(old_path)
    if hashlib.sha256(original).hexdigest() != old_hash:
        raise ValueError("judilibre_maintenance_source_hash_mismatch")
    if original not in (raw["text"].encode("utf-8"), rendered):
        raise ValueError("judilibre_body_changed_requires_review")
    digest = hashlib.sha256(rendered).hexdigest()
    report = {"document_id": str(doc.id), "source_id": source_id,
              "official_summaries": len(official_summaries(raw)),
              "changed": rendered != original, "applied": False}
    if not apply or rendered == original:
        if apply and doc.indexation_status == "pending":
            await enqueue_ingestion(str(doc.id), expected_source=old_path)
        return report
    new_path = f"common/judilibre/{uuid.uuid4()}_{doc.numero_pourvoi.replace('/', '-')}.txt"
    storage.put_file_bytes(new_path, rendered, content_type="text/plain")
    storage.put_file_bytes(new_path + ".source.json", json.dumps(raw, ensure_ascii=False).encode(),
                           content_type="application/json")
    changed = await db.execute(update(Document).where(
        Document.id == doc.id, Document.storage_path == old_path, Document.file_hash == old_hash,
        Document.retired_at.is_(None), Document.organisation_id.is_(None),
        Document.private_dossier_id.is_(None), Document.private_conversation_id.is_(None),
    ).values(storage_path=new_path, file_hash=digest, file_size=len(rendered),
             indexation_status="pending", indexation_error=None,
             indexation_progress=None).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        await db.rollback()
        raise ValueError("judilibre_maintenance_source_version_changed")
    await db.commit()
    await db.refresh(doc)
    await enqueue_ingestion(str(doc.id), expected_source=new_path)
    return {**report, "applied": True}
