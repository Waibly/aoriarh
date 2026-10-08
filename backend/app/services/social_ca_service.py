"""CA maintenance by official NAC identity, with inventory separated from admission.

Unknown/mixed categories are retained for review, never silently called irrelevant.
The old all-matters collector stays disabled. No LLM classifier or full-site import.
"""

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.models.document import Document
from app.services.curated_source_service import CuratedSourceService
from app.services.judilibre_ca_sync import next_cursor
from app.services.judilibre_service import JudilibreService
from app.services.social_ca_scope import ADMITTED_NAC

PREFIX = "common/social_ca/"
MAX_PAGES = 20
MAX_NEW_DOCUMENTS = 20
MAX_TOKENS_PER_DAY = 250_000
MAX_DOCUMENT_TOKENS = 50_000
MAX_DETAIL_CHECKS = 100


def admitted(metadata):
    return metadata.get("jurisdiction") == "ca" and metadata.get("nac") in ADMITTED_NAC


def source_id(metadata):
    value = metadata.get("id")
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{24}", value):
        raise ValueError("Invalid Judilibre source identity")
    return value


class SocialCaService:
    def __init__(self, storage=None, api=None):
        self.archive = CuratedSourceService(storage)
        self.api = api or JudilibreService()

    async def inventory(self, client, start, end):
        records, cursor, expected = {}, None, None
        for _ in range(MAX_PAGES):
            params = {
                "jurisdiction": "ca",
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "date_type": "update",
                "abridged": "true",
                "batch_size": 1000,
            }
            if cursor:
                params["searchAfter"] = cursor
            data = await self.api._api_get(client, "/scan", params=params)
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError("Invalid Judilibre inventory response")
            total = data.get("total")
            if (
                not isinstance(total, int)
                or total < 0
                or (expected is not None and total != expected)
            ):
                raise ValueError("Judilibre inventory changed during pagination")
            expected = total
            for metadata in data["results"]:
                key = source_id(metadata)
                if key in records:
                    raise ValueError("Repeated Judilibre source across pages")
                records[key] = metadata
            following = next_cursor(data.get("next_batch"))
            if following is None:
                if len(records) != expected:
                    raise ValueError("Incomplete Judilibre inventory")
                return records
            if following == cursor or not data["results"]:
                raise ValueError("Judilibre cursor did not progress")
            cursor = following
        raise ValueError("Judilibre inventory page limit reached; no admission")

    async def sync(self, db, *, apply=True, today=None):
        today = today or datetime.now(timezone.utc).date()
        state = self.archive.read_json(PREFIX + "state.json") or {
            "pending": {},
            "last_complete_end": None,
        }
        # Source update dates include late publication of older decisions.
        start = (
            date.fromisoformat(state["last_complete_end"]) - timedelta(days=2)
            if state["last_complete_end"]
            else today - timedelta(days=30)
        )
        end = today - timedelta(days=1)
        result = {
            "window_start": str(start),
            "window_end": str(end),
            "inventoried": 0,
            "eligible": 0,
            "created": 0,
            "existing": 0,
            "review_pending": 0,
            "budget_pending": 0,
            "errors": [],
            "documents": [],
            "apply": apply,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            records = await self.inventory(client, start, end)
            inventory_hash = hashlib.sha256(
                json.dumps(records, sort_keys=True).encode()
            ).hexdigest()
            self.archive.save_json(
                PREFIX + f"inventories/{start}_{end}-{inventory_hash}.json", records
            )
            result["inventoried"] = len(records)
            for key, metadata in records.items():
                if admitted(metadata):
                    state["pending"][key] = metadata
                else:
                    result["review_pending"] += 1
            state["last_complete_end"] = end.isoformat()
            self.archive.save_json(PREFIX + "state.json", state)
            ledger_key = PREFIX + "budgets/" + today.isoformat() + ".json"
            ledger = self.archive.read_json(ledger_key) or {
                "tokens_reserved": 0,
                "documents_reserved": 0,
            }
            detail_checks = 0
            for key, metadata in list(state["pending"].items()):
                url = "https://www.courdecassation.fr/decision/" + key
                result["eligible"] += 1
                existing = (
                    await db.scalars(
                        select(Document).where(
                            Document.organisation_id.is_(None), Document.source_url == url
                        )
                    )
                ).all()
                if existing:
                    if (
                        len(existing) != 1
                        or existing[0].private_dossier_id
                        or existing[0].private_conversation_id
                    ):
                        result["errors"].append(key + ": ambiguous or private document identity")
                        continue
                    doc = existing[0]
                    # Existing frozen decisions are not overwritten automatically.
                    # Updated source metadata remains in the per-window evidence.
                    if doc.retired_at or doc.indexation_status != "indexed":
                        result["review_pending"] += 1
                        del state["pending"][key]
                        continue
                    if not apply:
                        result["existing"] += 1
                        continue
                    if detail_checks >= MAX_DETAIL_CHECKS:
                        result["budget_pending"] += 1
                        continue
                    detail_checks += 1
                    try:
                        raw = await self.api._api_get(client, "/decision", params={"id": key})
                        if (
                            not isinstance(raw, dict)
                            or source_id(raw) != key
                            or not isinstance(raw.get("text"), str)
                            or not raw["text"].strip()
                        ):
                            raise ValueError("Invalid current decision source")
                        sha = hashlib.sha256(raw["text"].encode()).hexdigest()
                        if sha != doc.file_hash:
                            self.archive.save_json(
                                PREFIX + "revisions/" + key + "/" + sha + ".json", raw
                            )
                            result["review_pending"] += 1
                        else:
                            result["existing"] += 1
                        del state["pending"][key]
                    except Exception as exc:
                        result["errors"].append(
                            key + ": " + type(exc).__name__ + ": " + str(exc)[:200]
                        )
                    continue
                try:
                    date.fromisoformat(metadata["decision_date"])
                except (KeyError, ValueError, TypeError):
                    result["errors"].append(key + ": invalid decision date")
                    continue
                parsed_metadata = self.api._parse_decision(
                    dict(metadata, text="metadata identity only")
                )
                if parsed_metadata:
                    legacy = (
                        await db.scalars(
                            select(Document).where(
                                Document.organisation_id.is_(None),
                                Document.source_type == "arret_cour_appel",
                                Document.juridiction == parsed_metadata.juridiction,
                                Document.numero_pourvoi == parsed_metadata.numero_pourvoi,
                                Document.date_decision == parsed_metadata.date_decision,
                            )
                        )
                    ).all()
                    if legacy:
                        result["review_pending"] += 1
                        del state["pending"][key]
                        continue
                if not apply:
                    result["documents"].append(
                        {"source_id": key, "nac": metadata.get("nac"), "status": "eligible_new"}
                    )
                    continue
                if (
                    detail_checks >= MAX_DETAIL_CHECKS
                    or ledger["documents_reserved"] >= MAX_NEW_DOCUMENTS
                    or ledger["tokens_reserved"] >= MAX_TOKENS_PER_DAY
                ):
                    result["budget_pending"] += 1
                    continue
                try:
                    detail_checks += 1
                    raw = await self.api._api_get(client, "/decision", params={"id": key})
                    if not isinstance(raw, dict) or source_id(raw) != key or not admitted(raw):
                        raise ValueError("Source identity or official NAC changed")
                    # Do not allow the legacy parser to invent a decision date.
                    date.fromisoformat(raw["decision_date"])
                    parsed = self.api._parse_decision(raw)
                    if not parsed or not parsed.text.strip():
                        raise ValueError("Empty decision source")
                    body = parsed.text.encode()
                    sha = hashlib.sha256(body).hexdigest()
                    self.archive.save_json(PREFIX + "decisions/" + key + "/" + sha + ".json", raw)
                    duplicates = (
                        await db.scalars(
                            select(Document).where(
                                Document.organisation_id.is_(None),
                                Document.source_type == "arret_cour_appel",
                                Document.juridiction == parsed.juridiction,
                                Document.numero_pourvoi == parsed.numero_pourvoi,
                                Document.date_decision == parsed.date_decision,
                            )
                        )
                    ).all()
                    if duplicates:
                        result["review_pending"] += 1
                        del state["pending"][key]
                        continue
                    from app.rag.ingestion import IngestionPipeline
                    from app.rag.text_cleaner import clean_text
                    import tiktoken

                    pipeline = IngestionPipeline()
                    doc = Document(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, url),
                        organisation_id=None,
                        name=f"{parsed.juridiction}, {parsed.chambre}, {parsed.date_decision:%d/%m/%Y}, n° {parsed.numero_pourvoi}",
                        source_type="arret_cour_appel",
                        norme_niveau=4,
                        norme_poids=0.85,
                        source_url=url,
                        juridiction=parsed.juridiction,
                        chambre=parsed.chambre,
                        numero_pourvoi=parsed.numero_pourvoi,
                        date_decision=parsed.date_decision,
                        solution=parsed.solution,
                        formation=parsed.formation,
                        publication=parsed.publication,
                        file_hash=sha,
                        file_format="txt",
                        file_size=len(body),
                        indexation_status="pending",
                        storage_path=PREFIX + "published/" + key + "/" + sha + ".txt",
                    )
                    chunks = pipeline.jurisprudence_chunker.chunk(
                        clean_text(parsed.text),
                        metadata_header=pipeline._build_jurisprudence_header(doc),
                    )
                    enc = tiktoken.get_encoding("cl100k_base")
                    tokens = sum(len(enc.encode(c, disallowed_special=())) for c in chunks)
                    if (
                        not chunks
                        or tokens > MAX_DOCUMENT_TOKENS
                        or ledger["tokens_reserved"] + tokens > MAX_TOKENS_PER_DAY
                    ):
                        result["budget_pending"] += 1
                        continue
                    # Reserve before the paid call; crashes/retries cannot bypass the daily cap.
                    ledger["tokens_reserved"] += tokens
                    ledger["documents_reserved"] += 1
                    self.archive.save_json(ledger_key, ledger)
                    self.archive.storage.put_file_bytes(
                        doc.storage_path, body, "text/plain; charset=utf-8"
                    )
                    if (
                        self.archive.storage.get_file_bytes_bounded(doc.storage_path, len(body) + 1)
                        != body
                    ):
                        raise ValueError("Decision source archive verification failed")
                    db.add(doc)
                    await db.commit()

                    async def plain_extract(document, file_bytes, session):
                        return file_bytes.decode("utf-8")

                    pipeline._extract_document_text = plain_extract
                    await pipeline.ingest(
                        doc.id, db, expected_source=doc.storage_path, max_embedding_tokens=tokens
                    )
                    await db.refresh(doc)
                    if doc.indexation_status != "indexed":
                        pipeline._cleanup_old_chunks(str(doc.id), set(), strict=True)
                        raise ValueError("Decision indexing failed: " + str(doc.indexation_error))
                    result["created"] += 1
                    result["documents"].append(
                        {
                            "source_id": key,
                            "document_id": str(doc.id),
                            "nac": metadata["nac"],
                            "chunks": doc.chunk_count,
                        }
                    )
                    del state["pending"][key]
                except Exception as exc:
                    await db.rollback()
                    result["errors"].append(key + ": " + type(exc).__name__ + ": " + str(exc)[:200])
                self.archive.save_json(PREFIX + "state.json", state)
                self.archive.save_json(PREFIX + "latest.json", result)
            self.archive.save_json(PREFIX + "state.json", state)
        result["remaining_eligible"] = len(state["pending"])
        result["daily_tokens_reserved"] = ledger["tokens_reserved"]
        self.archive.save_json(PREFIX + "latest.json", result)
        return result
