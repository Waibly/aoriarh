"""Service de synchronisation avec l'API Judilibre (Cour de cassation).

Récupère les arrêts de la chambre sociale publiés au Bulletin
et les ingère comme documents communs dans le pipeline RAG.

Utilise l'endpoint /export qui retourne les décisions complètes
(texte intégral + zones + métadonnées) par batch.
"""

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.tasks import enqueue_ingestion

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_REQUEST_TIMEOUT = 60.0
_RETRY_DELAY = 2.0
_MAX_RETRIES = 3
# Refresh token 5 minutes before expiry
_TOKEN_REFRESH_MARGIN = 300

_CHAMBER_MAP = {
    # Cour de cassation
    "soc": "Chambre sociale",
    "civ1": "Chambre civile 1",
    "civ2": "Chambre civile 2",
    "civ3": "Chambre civile 3",
    "com": "Chambre commerciale",
    "crim": "Chambre criminelle",
    "mi": "Chambre mixte",
    "pl": "Assemblée plénière",
    # Cour d'appel — codes Judilibre les plus courants (best-effort, le code
    # brut est gardé en fallback si non mappé)
    "ch_soc": "Chambre sociale",
    "ch_civ_1": "Chambre civile 1",
    "ch_civ_2": "Chambre civile 2",
    "ch_civ_3": "Chambre civile 3",
    "ch_com": "Chambre commerciale",
    "ch_crim": "Chambre criminelle",
    "ch_corr": "Chambre correctionnelle",
}


@dataclass
class JudilibreDecision:
    """Parsed decision from the Judilibre API."""

    numero_pourvoi: str
    date_decision: date
    juridiction: str
    chambre: str
    formation: str | None
    solution: str
    publication: str
    text: str
    themes: list[str]
    sommaire: str | None
    textes_appliques: list[str]


@dataclass
class SyncResult:
    """Result of a synchronisation run."""

    total_fetched: int = 0
    new_ingested: int = 0
    already_exists: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


class JudilibreService:
    """Connects to the Judilibre API, fetches decisions, and ingests them."""

    # Class-level token cache (shared across instances within the same process)
    _cached_token: str | None = None
    _token_expires_at: float = 0.0
    _token_lock: asyncio.Lock | None = None

    def __init__(self) -> None:
        self.base_url = settings.judilibre_base_url.rstrip("/")
        self._client_id = settings.judilibre_client_id
        self._client_secret = settings.judilibre_client_secret
        self._oauth_url = settings.judilibre_oauth_url

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._token_lock is None:
            cls._token_lock = asyncio.Lock()
        return cls._token_lock

    async def _get_access_token(self) -> str:
        """Get a valid OAuth2 Bearer token, fetching/refreshing as needed."""
        now = time.monotonic()
        if (
            JudilibreService._cached_token
            and now < JudilibreService._token_expires_at
        ):
            return JudilibreService._cached_token

        async with self._get_lock():
            # Double-check after acquiring lock
            now = time.monotonic()
            if (
                JudilibreService._cached_token
                and now < JudilibreService._token_expires_at
            ):
                return JudilibreService._cached_token

            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.post(
                    self._oauth_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": "openid",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                token_data = response.json()

            JudilibreService._cached_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            JudilibreService._token_expires_at = (
                time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN
            )
            logger.info("PISTE OAuth2 token obtained (expires in %ds)", expires_in)
            return JudilibreService._cached_token

    # --- Public API ---

    async def sync(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        date_start: date | None = None,
        date_end: date | None = None,
        jurisdiction: str = "cc",
        chamber: str = "soc",
        publication: str = "b",
        source_type: str = "arret_cour_cassation",
        max_decisions: int | None = None,
    ) -> SyncResult:
        """Synchronise decisions from Judilibre into the documents table.

        Uses the /export endpoint which returns full decisions by batch.

        - jurisdiction : 'cc' (Cour de cassation), 'ca' (Cour d'appel),
                         'ce' (Conseil d'État), 'cc_ag' (CA admin), etc.
        - chamber      : only used for 'cc' (soc, crim, com, civ1, civ2, civ3, mi, pl).
                         For 'ca', the API filters using its own chamber codes.
        - source_type  : DB source_type to assign to ingested decisions
                         (arret_cour_cassation / arret_cour_appel / arret_conseil_etat).
        """
        result = SyncResult()

        if not self._client_id or not self._client_secret:
            result.errors = 1
            result.error_messages = ["JUDILIBRE_CLIENT_ID / JUDILIBRE_CLIENT_SECRET non configurés"]
            return result

        if date_end is None:
            date_end = date.today()
        if date_start is None:
            date_start = date(date_end.year - 3, date_end.month, date_end.day)

        # Load existing pourvois for deduplication (per source_type)
        existing_pourvois = await self._get_existing_pourvois(db, source_type=source_type)

        # Lazy-init storage service once
        from app.services.storage_service import StorageService

        storage = StorageService()

        batch_num = 0
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            while True:
                api_params: dict = {
                    "jurisdiction": jurisdiction,
                    "publication": publication,
                    "date_start": date_start.isoformat(),
                    "date_end": date_end.isoformat(),
                    "batch": batch_num,
                    "batch_size": _BATCH_SIZE,
                }
                # Chamber filter only applies to Cour de cassation in Judilibre.
                # For other jurisdictions we omit it (Judilibre returns all
                # chambers of that jurisdiction).
                if jurisdiction == "cc":
                    api_params["chamber"] = chamber
                data = await self._api_get(client, "/export", params=api_params)
                if data is None:
                    result.errors += 1
                    result.error_messages.append(f"Erreur API batch {batch_num}")
                    break

                total = data.get("total", 0)
                if batch_num == 0:
                    result.total_fetched = total
                    if jurisdiction == "cc":
                        logger.info(
                            "Judilibre sync: %d decisions found (%s → %s, juri=cc, chamber=%s, pub=%s)",
                            total, date_start, date_end, chamber, publication,
                        )
                    else:
                        logger.info(
                            "Judilibre sync: %d decisions found (%s → %s, juri=%s, pub=%s)",
                            total, date_start, date_end, jurisdiction, publication,
                        )

                items = data.get("results", [])
                if not items:
                    break

                for raw in items:
                    if max_decisions and result.new_ingested >= max_decisions:
                        break

                    try:
                        decision = self._parse_decision(raw)
                        if decision is None:
                            result.errors += 1
                            continue

                        # Skip decisions without an identifier — they can't be
                        # deduplicated reliably and would pollute the set with
                        # an empty string.
                        if not decision.numero_pourvoi:
                            result.errors += 1
                            continue

                        if decision.numero_pourvoi in existing_pourvois:
                            result.already_exists += 1
                            continue

                        doc = await self._create_document(
                            db, decision, user_id, storage, source_type=source_type
                        )
                        await enqueue_ingestion(str(doc.id))
                        existing_pourvois.add(decision.numero_pourvoi)
                        result.new_ingested += 1

                    except Exception as exc:
                        result.errors += 1
                        pourvoi = raw.get("number", raw.get("id", "?"))
                        msg = f"Erreur décision {pourvoi}: {exc}"
                        result.error_messages.append(msg)
                        logger.warning(msg)

                if max_decisions and result.new_ingested >= max_decisions:
                    break

                # Check if there are more batches
                if not data.get("next_batch"):
                    break
                batch_num += 1

        logger.info(
            "Judilibre sync completed: %d total, %d new, %d existing, %d errors",
            result.total_fetched, result.new_ingested,
            result.already_exists, result.errors,
        )
        return result

    async def get_stats(self, db: AsyncSession) -> dict:
        """Return statistics about ingested jurisprudence."""
        from sqlalchemy import func

        juris_types = [
            "arret_cour_cassation",
            "arret_cour_appel",
            "arret_conseil_etat",
            "decision_conseil_constitutionnel",
        ]

        row = (
            await db.execute(
                select(
                    func.count(Document.id).label("total"),
                    func.count(Document.id)
                    .filter(Document.indexation_status == "indexed")
                    .label("indexed"),
                    func.count(Document.id)
                    .filter(Document.indexation_status == "pending")
                    .label("pending"),
                    func.count(Document.id)
                    .filter(Document.indexation_status == "indexing")
                    .label("indexing"),
                    func.count(Document.id)
                    .filter(Document.indexation_status == "error")
                    .label("errors"),
                    func.min(Document.date_decision).label("oldest_decision"),
                    func.max(Document.date_decision).label("newest_decision"),
                    func.max(Document.created_at).label("last_sync"),
                ).where(
                    Document.source_type.in_(juris_types),
                    Document.organisation_id.is_(None),
                )
            )
        ).one()

        return {
            "total": row.total,
            "indexed": row.indexed,
            "pending": row.pending,
            "indexing": row.indexing,
            "errors": row.errors,
            "oldest_decision": row.oldest_decision.isoformat() if row.oldest_decision else None,
            "newest_decision": row.newest_decision.isoformat() if row.newest_decision else None,
            "last_sync": row.last_sync.isoformat() if row.last_sync else None,
        }

    # --- Private methods ---

    @staticmethod
    def _parse_decision(raw: dict) -> JudilibreDecision | None:
        """Parse a single decision from /export results into a JudilibreDecision."""
        text = raw.get("text", "")
        if not text:
            return None

        # Parse date (field is "decision_date" in export)
        date_str = raw.get("decision_date", "")
        try:
            decision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            decision_date = date.today()

        # Map publication codes
        pub_raw = raw.get("publication", [])
        if isinstance(pub_raw, list):
            pub_str = "Publié au Bulletin" if "b" in pub_raw else "Inédit"
        else:
            pub_str = str(pub_raw)

        # Map chamber code to label
        chambre_raw = raw.get("chamber", "")
        chambre = _CHAMBER_MAP.get(chambre_raw, chambre_raw)

        # Build juridiction label depending on the raw 'jurisdiction' field
        # returned by Judilibre. For CA, fall back to the location label
        # (eg 'Cour d'appel de Paris') so the document name is meaningful.
        jurisdiction_raw = (raw.get("jurisdiction") or "cc").lower()
        location_raw = raw.get("location") or ""
        if jurisdiction_raw == "cc":
            juridiction_label = "Cour de cassation"
        elif jurisdiction_raw == "ca":
            # Judilibre location codes look like "ca_paris", "ca_versailles"…
            location_label = location_raw.replace("ca_", "").replace("_", " ").title()
            juridiction_label = (
                f"Cour d'appel de {location_label}" if location_label else "Cour d'appel"
            )
        elif jurisdiction_raw == "ce":
            juridiction_label = "Conseil d'État"
        else:
            juridiction_label = jurisdiction_raw.upper()

        # Extract summary from titlesAndSummaries or summary field
        sommaire = raw.get("summary")
        if not sommaire:
            tas = raw.get("titlesAndSummaries", [])
            if tas and isinstance(tas, list) and tas[0].get("summary"):
                sommaire = tas[0]["summary"]

        # Extract visa texts
        textes_appliques = []
        for v in raw.get("visa", []):
            if isinstance(v, dict) and v.get("title"):
                # Strip HTML tags from visa
                import re
                textes_appliques.append(re.sub(r"<[^>]+>", "", v["title"]))

        # Use the Judilibre 'id' as fallback if 'number' is missing
        # (for some old or unpublished decisions)
        return JudilibreDecision(
            numero_pourvoi=raw.get("number", "") or raw.get("id", ""),
            date_decision=decision_date,
            juridiction=juridiction_label,
            chambre=chambre,
            formation=raw.get("formation"),
            solution=raw.get("solution", ""),
            publication=pub_str,
            text=text,
            themes=raw.get("themes", []),
            sommaire=sommaire,
            textes_appliques=textes_appliques,
        )

    async def _create_document(
        self,
        db: AsyncSession,
        decision: JudilibreDecision,
        user_id: uuid.UUID,
        storage: "StorageService",
        *,
        source_type: str = "arret_cour_cassation",
    ) -> Document:
        """Create a Document record from a Judilibre decision."""
        from app.services.storage_service import StorageService  # noqa: F811

        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]

        # Build display name based on source type
        if source_type == "arret_cour_cassation":
            name = (
                f"Cass. {decision.chambre}, "
                f"{decision.date_decision.strftime('%d/%m/%Y')}, "
                f"n° {decision.numero_pourvoi}"
            )
        elif source_type == "arret_cour_appel":
            location = decision.juridiction or "Cour d'appel"
            name = (
                f"{location}, "
                f"{decision.chambre}, "
                f"{decision.date_decision.strftime('%d/%m/%Y')}, "
                f"n° {decision.numero_pourvoi}"
            )
        elif source_type == "arret_conseil_etat":
            name = (
                f"CE, "
                f"{decision.date_decision.strftime('%d/%m/%Y')}, "
                f"n° {decision.numero_pourvoi}"
            )
        else:
            name = (
                f"{decision.juridiction}, "
                f"{decision.date_decision.strftime('%d/%m/%Y')}, "
                f"n° {decision.numero_pourvoi}"
            )

        file_id = uuid.uuid4()
        safe_pourvoi = decision.numero_pourvoi.replace(" ", "_").replace("/", "-")
        storage_path = f"common/judilibre/{file_id}_{safe_pourvoi}.txt"
        text_bytes = decision.text.encode("utf-8")
        storage.put_file_bytes(storage_path, text_bytes, content_type="text/plain")

        file_hash = hashlib.sha256(text_bytes).hexdigest()

        doc = Document(
            organisation_id=None,
            name=name,
            source_type=source_type,
            norme_niveau=hierarchy["niveau"],
            norme_poids=hierarchy["poids"],
            storage_path=storage_path,
            indexation_status="pending",
            uploaded_by=user_id,
            file_size=len(text_bytes),
            file_format="txt",
            file_hash=file_hash,
            juridiction=decision.juridiction,
            chambre=decision.chambre,
            formation=decision.formation,
            numero_pourvoi=decision.numero_pourvoi,
            date_decision=decision.date_decision,
            solution=decision.solution,
            publication=decision.publication,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    async def _get_existing_pourvois(
        self, db: AsyncSession, *, source_type: str = "arret_cour_cassation"
    ) -> set[str]:
        """Get set of already-ingested pourvoi numbers to avoid duplicates,
        scoped to a single source_type so different jurisdictions don't
        cross-contaminate the dedup."""
        result = await db.execute(
            select(Document.numero_pourvoi).where(
                Document.source_type == source_type,
                Document.organisation_id.is_(None),
                Document.numero_pourvoi.isnot(None),
            )
        )
        return {row[0] for row in result.all()}

    async def _api_get(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict | None = None,
    ) -> dict | None:
        """Make a GET request to the Judilibre API with OAuth2 Bearer auth."""
        url = f"{self.base_url}{path}"

        for attempt in range(_MAX_RETRIES):
            try:
                token = await self._get_access_token()
                headers = {"Authorization": f"Bearer {token}"}
                response = await client.get(url, headers=headers, params=params)

                # Token expired mid-session — clear cache and retry
                if response.status_code == 401 and attempt < _MAX_RETRIES - 1:
                    JudilibreService._cached_token = None
                    JudilibreService._token_expires_at = 0.0
                    continue

                if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_DELAY * (2 ** attempt)
                    logger.warning("Judilibre rate limit (429), retry in %.1fs", delay)
                    await asyncio.sleep(delay)
                    continue

                if response.status_code == 404:
                    return None

                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                logger.error("Judilibre API timeout for %s", path)
                return None

        return None
