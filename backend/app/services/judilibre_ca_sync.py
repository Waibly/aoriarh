"""Complete CA collection with durable /scan cursors and a transactional outbox.

No chamber/content classifier. Technical retries only: three scan failures per
run and three queue submissions per source version. Errors remain visible.
"""

import asyncio
import hashlib
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.judilibre import JudilibreRecord, JudilibreScan, JudilibreScanItem
from app.models.sync_log import SyncLog
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.services.judilibre_service import JudilibreService
from app.services.storage_service import StorageService

BATCH_SIZE = 100
MAX_PENDING_DOCUMENTS = 300
MAX_TECHNICAL_ATTEMPTS = 3
SOURCE_URL = "https://www.courdecassation.fr/decision/"
HISTORY_START = date(2026, 1, 1)


class IncompleteScanError(RuntimeError):
    """The source inventory changed or its pagination is incomplete."""


def next_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise IncompleteScanError("Curseur Judilibre invalide")
    # Only extract the opaque token, never follow a remote URL. The live API
    # uses searchAfter (camelCase), unlike the old OpenAPI description.
    query = urlsplit(value).query if "?" in value else value
    tokens = parse_qs(query).get("searchAfter", [])
    if len(tokens) != 1 or not tokens[0]:
        raise IncompleteScanError("Curseur searchAfter absent ou ambigu")
    return tokens[0]


async def schedule_scan(
    db: AsyncSession,
    *,
    key: str,
    start: date,
    end: date,
    date_type: str = "creation",
    user_id: uuid.UUID | None = None,
) -> JudilibreScan:
    if start > end or date_type not in {"creation", "update"}:
        raise ValueError("Plage ou type de date invalide")
    existing = await db.scalar(select(JudilibreScan).where(JudilibreScan.key == key))
    if existing:
        return existing
    try:
        async with db.begin_nested():
            log = SyncLog(sync_type="jurisprudence", status="running", started_at=datetime.now(UTC))
            db.add(log)
            await db.flush()
            scan = JudilibreScan(
                key=key,
                date_start=start,
                date_end=end,
                date_type=date_type,
                user_id=user_id,
                sync_log_id=log.id,
            )
            db.add(scan)
            await db.flush()
        return scan
    except IntegrityError:
        existing = await db.scalar(select(JudilibreScan).where(JudilibreScan.key == key))
        if existing is None:
            raise
        return existing


async def schedule_recurring(db: AsyncSession, today: date) -> None:
    """Catch up missed update windows, and reconcile the full history monthly."""
    yesterday = today - timedelta(days=1)
    latest = await db.scalar(
        select(func.max(JudilibreScan.date_end)).where(JudilibreScan.key.like("ca:updates:%"))
    )
    if latest is None or latest < yesterday:
        start = (latest - timedelta(days=2)) if latest else (today - timedelta(days=30))
        await schedule_scan(
            db, key=f"ca:updates:{yesterday}", start=start, end=yesterday, date_type="update"
        )
    # First run also starts the audited 2026 backfill. Later monthly runs
    # reconcile late publications, not just updates of the last 30 days.
    key = f"ca:history:{today:%Y-%m}:"
    active_history = await db.scalar(
        select(JudilibreScan.id)
        .where(
            JudilibreScan.key.like("ca:history:%"),
            JudilibreScan.status.in_(["pending", "awaiting_index"]),
        )
        .limit(1)
    )
    cycle_exists = await db.scalar(
        select(JudilibreScan.id).where(JudilibreScan.key.like(key + "%")).limit(1)
    )
    if not active_history and not cycle_exists and yesterday >= HISTORY_START:
        # Independent weeks avoid restarting months of work when a late
        # publication changes one inventory. No gaps or overlapping boundaries.
        start = HISTORY_START
        while start <= yesterday:
            end = min(start + timedelta(days=6), yesterday)
            await schedule_scan(db, key=key + start.isoformat(), start=start, end=end)
            start = end + timedelta(days=1)
    await db.commit()


class JudilibreCaCollector:
    def __init__(self, api=None, storage=None):
        self.api = api or JudilibreService()
        self.storage = storage or StorageService()

    async def upsert(self, db: AsyncSession, raw: dict, user_id=None) -> str:
        source_id = raw.get("id", "")
        if not isinstance(source_id, str) or not re.fullmatch(r"[0-9a-f]{24}", source_id):
            raise ValueError("Identifiant Judilibre absent ou invalide")
        if raw.get("jurisdiction") != "ca":
            raise ValueError("Juridiction inattendue dans le flux CA")
        # Fail technical contracts; never invent a source date or empty text.
        date.fromisoformat(raw["decision_date"])
        if not isinstance(raw.get("text"), str) or not raw["text"].strip():
            raise ValueError(f"Texte Judilibre vide : {source_id}")
        parsed = self.api._parse_decision(raw)
        if parsed is None:
            raise ValueError(f"Décision inexploitable : {source_id}")
        updated = date.fromisoformat(raw["update_date"]) if raw.get("update_date") else None
        body = raw["text"].encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        url = SOURCE_URL + source_id
        record = await db.get(JudilibreRecord, source_id)
        doc = (
            await db.scalar(
                select(Document).where(Document.id == record.document_id).with_for_update()
            )
            if record
            else None
        )
        adopted = False
        if doc is None:
            # Attach legacy documents only with identical content AND full
            # court/number/date identity. Never merge different RG decisions.
            candidates = (
                await db.scalars(
                    select(Document)
                    .where(
                        Document.organisation_id.is_(None),
                        Document.retired_at.is_(None),
                        Document.source_type == "arret_cour_appel",
                        Document.juridiction == parsed.juridiction,
                        Document.numero_pourvoi == parsed.numero_pourvoi,
                        Document.date_decision == parsed.date_decision,
                        Document.file_hash == digest,
                        Document.source_url.is_(None),
                        ~Document.id.in_(select(JudilibreRecord.document_id)),
                    )
                    .with_for_update()
                )
            ).all()
            if len(candidates) == 1:
                doc = candidates[0]
                adopted = True
        new = doc is None
        if new:
            hierarchy = DOCUMENT_TYPE_HIERARCHY["arret_cour_appel"]
            doc = Document(
                id=uuid.uuid5(uuid.NAMESPACE_URL, url),
                organisation_id=None,
                source_type="arret_cour_appel",
                uploaded_by=user_id,
                norme_niveau=hierarchy["niveau"],
                norme_poids=hierarchy["poids"],
            )
            db.add(doc)
        if doc.organisation_id is not None or doc.source_type != "arret_cour_appel":
            raise ValueError("Identité Judilibre liée à un document hors corpus public CA")
        metadata = {
            "name": (
                f"{parsed.juridiction}, {parsed.chambre}, "
                f"{parsed.date_decision:%d/%m/%Y}, n° {parsed.numero_pourvoi}"
            ),
            "juridiction": parsed.juridiction,
            "chambre": parsed.chambre,
            "numero_pourvoi": parsed.numero_pourvoi,
            "date_decision": parsed.date_decision,
            "formation": parsed.formation,
            "solution": parsed.solution,
            "publication": parsed.publication,
        }
        content_changed = new or doc.file_hash != digest
        metadata_changed = any(getattr(doc, k) != v for k, v in metadata.items())
        if content_changed:
            # Immutable, deterministic version keys survive retries/crashes.
            # Keep previous objects; in-flight ingestion uses its pinned version.
            path = f"common/judilibre/{source_id}/{digest}.txt"
            await asyncio.to_thread(
                self.storage.put_file_bytes, path, body, content_type="text/plain"
            )
            doc.storage_path, doc.file_hash = path, digest
            doc.file_size, doc.file_format = len(body), "txt"
        for key, value in metadata.items():
            setattr(doc, key, value)
        doc.source_url, doc.source_updated_date = url, updated
        if record is None:
            record = JudilibreRecord(source_id=source_id, document_id=doc.id)
            db.add(record)
        if content_changed or metadata_changed:
            doc.indexation_status, doc.indexation_error = "pending", None
            doc.indexation_progress = None
            record.needs_indexing, record.enqueue_attempts = True, 0
            record.last_enqueued_at = None
        elif adopted:
            record.needs_indexing = doc.indexation_status != "indexed"
        # SQL ordering must persist Document before its identity FK.
        await db.flush([doc])
        await db.flush()
        return (
            "created" if new else "updated" if content_changed or metadata_changed else "existing"
        )

    async def page(self, db: AsyncSession, scan: JudilibreScan, client) -> None:
        params = {
            "jurisdiction": "ca",
            "date_start": scan.date_start.isoformat(),
            "date_end": scan.date_end.isoformat(),
            "date_type": scan.date_type,
            "batch_size": BATCH_SIZE,
        }
        if scan.cursor:
            params["searchAfter"] = scan.cursor
        data = await self.api._api_get(client, "/scan", params=params)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise RuntimeError("Réponse /scan Judilibre absente ou invalide")
        total = data.get("total")
        if not isinstance(total, int) or total < 0:
            raise IncompleteScanError("Total Judilibre absent ou invalide")
        if scan.expected_total is not None and scan.expected_total != total:
            raise IncompleteScanError("Inventaire source modifié pendant le scan")
        scan.expected_total = total
        cursor = next_cursor(data.get("next_batch"))
        if cursor is not None and (cursor == scan.cursor or not data["results"]):
            raise IncompleteScanError("Pagination Judilibre sans progression")
        log = await db.get(SyncLog, scan.sync_log_id)
        for raw in data["results"]:
            source_id = raw.get("id")
            if await db.get(JudilibreScanItem, (scan.id, source_id)):
                raise IncompleteScanError("Identifiant répété entre deux pages Judilibre")
            outcome = await self.upsert(db, raw, scan.user_id)
            db.add(JudilibreScanItem(scan_id=scan.id, source_id=source_id))
            if outcome == "created":
                log.items_created += 1
            elif outcome == "updated":
                log.items_updated += 1
            else:
                log.items_skipped += 1
        await db.flush()
        seen = await db.scalar(
            select(func.count())
            .select_from(JudilibreScanItem)
            .where(JudilibreScanItem.scan_id == scan.id)
        )
        if seen > total or (cursor is None and seen != total):
            raise IncompleteScanError(f"Scan incomplet : {seen} identifiants uniques sur {total}")
        scan.cursor, scan.last_error = cursor, None
        scan.status = "pending" if cursor else "awaiting_index"
        log.items_fetched, log.error_message, log.status = seen, None, "running"
        # Atomic page: document identities, outbox, inventory and cursor.
        await db.commit()


async def record_scan_failure(db: AsyncSession, scan_id: uuid.UUID, exc: Exception) -> None:
    await db.rollback()
    scan = await db.get(JudilibreScan, scan_id)
    scan.attempts += 1
    scan.last_error = f"{type(exc).__name__}: {str(exc)[:400]}"
    scan.status = "error" if scan.attempts >= MAX_TECHNICAL_ATTEMPTS else "pending"
    if isinstance(exc, IncompleteScanError):
        # A changed inventory needs a fresh technical scan. Existing documents
        # remain, matched by source ID; no editorial repair or generated output.
        scan.cursor, scan.expected_total = None, None
        await db.execute(delete(JudilibreScanItem).where(JudilibreScanItem.scan_id == scan.id))
    log = await db.get(SyncLog, scan.sync_log_id)
    if isinstance(exc, IncompleteScanError):
        log.items_fetched = log.items_created = log.items_updated = log.items_skipped = 0
    log.status, log.errors, log.error_message = "error", scan.attempts, scan.last_error
    await db.commit()


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def dispatch_indexing(db: AsyncSession, pool, now: datetime) -> None:
    rows = (
        await db.execute(
            select(JudilibreRecord, Document)
            .join(Document, Document.id == JudilibreRecord.document_id)
            .where(JudilibreRecord.needs_indexing.is_(True))
            .order_by(
                JudilibreRecord.last_enqueued_at.asc().nullsfirst(), JudilibreRecord.created_at
            )
            .limit(MAX_PENDING_DOCUMENTS + BATCH_SIZE)
        )
    ).all()
    for record, doc in rows:
        if doc.indexation_status == "indexed":
            record.needs_indexing = False
            continue
        # A running job can last up to worker.job_timeout (4 h). Pending jobs
        # are retried only after the same grace period, with deterministic IDs.
        if record.last_enqueued_at and now - as_utc(record.last_enqueued_at) < timedelta(
            hours=4, minutes=5
        ):
            continue
        if record.enqueue_attempts >= MAX_TECHNICAL_ATTEMPTS:
            doc.indexation_status = "error"
            doc.indexation_error = (
                "Indexation Judilibre non terminée après 3 soumissions techniques"
            )
            continue
        attempt = record.enqueue_attempts + 1
        await pool.enqueue_job(
            "run_ingestion",
            str(doc.id),
            expected_source=doc.storage_path,
            _job_id=f"judilibre:{record.source_id}:{doc.file_hash}:{attempt}",
        )
        record.enqueue_attempts, record.last_enqueued_at = attempt, now
        await db.commit()
    await db.commit()


async def finish_scans(db: AsyncSession) -> None:
    scans = (
        await db.scalars(
            select(JudilibreScan).where(JudilibreScan.status.in_(["awaiting_index", "index_error"]))
        )
    ).all()
    for scan in scans:
        statuses = (
            await db.execute(
                select(Document.indexation_status, func.count())
                .join(JudilibreRecord, JudilibreRecord.document_id == Document.id)
                .join(JudilibreScanItem, JudilibreScanItem.source_id == JudilibreRecord.source_id)
                .where(JudilibreScanItem.scan_id == scan.id)
                .group_by(Document.indexation_status)
            )
        ).all()
        counts = dict(statuses)
        log = await db.get(SyncLog, scan.sync_log_id)
        missing = scan.expected_total - sum(counts.values())
        if counts.get("indexed", 0) == scan.expected_total:
            scan.status, scan.last_error = "complete", None
            log.status, log.errors, log.error_message = "success", 0, None
            log.completed_at = datetime.now(UTC)
        elif counts.get("error", 0) or missing:
            scan.status = "index_error"
            log.status = "error"
            log.errors = counts.get("error", 0) + missing
            log.error_message = (
                f"Collecte complète ; {counts.get('error', 0)} indexations en erreur, "
                f"{missing} documents supprimés ou absents"
            )
    await db.commit()


async def collect_tick(session_factory, pool) -> dict:
    """Run under the worker's dedicated PostgreSQL advisory lock."""
    collector = JudilibreCaCollector()
    async with session_factory() as db:
        await schedule_recurring(db, datetime.now(UTC).date())
        await dispatch_indexing(db, pool, datetime.now(UTC))
        await finish_scans(db)
        backlog = await db.scalar(
            select(func.count())
            .select_from(Document)
            .join(JudilibreRecord, JudilibreRecord.document_id == Document.id)
            .where(Document.indexation_status.in_(["pending", "indexing"]))
        )
        if backlog >= MAX_PENDING_DOCUMENTS:
            return {"status": "waiting_for_indexing", "pending": backlog}
        # Give recent updates a page, then history a page; neither can starve.
        chosen = []
        for date_type in ("update", "creation"):
            scan_id = await db.scalar(
                select(JudilibreScan.id)
                .where(JudilibreScan.status == "pending", JudilibreScan.date_type == date_type)
                .order_by(JudilibreScan.date_end.desc(), JudilibreScan.created_at)
                .limit(1)
            )
            if scan_id:
                chosen.append(scan_id)
        async with httpx.AsyncClient(timeout=60) as client:
            for scan_id in chosen:
                try:
                    scan = await db.get(JudilibreScan, scan_id)
                    await collector.page(db, scan, client)
                except Exception as exc:
                    await record_scan_failure(db, scan_id, exc)
        await dispatch_indexing(db, pool, datetime.now(UTC))
        await finish_scans(db)
        return {"status": "processed", "scans": len(chosen)}
