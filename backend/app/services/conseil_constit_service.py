"""Synchronisation des décisions du Conseil constitutionnel via PISTE Légifrance.

Réutilise les credentials PISTE déjà configurés (mêmes que LegiService /
JudilibreService). Pas de nouvelle clé à provisionner.

Endpoints validés en phase A :
- POST /search avec fond=CONSTIT pour lister les décisions par date
- POST /consult/juri avec {"textId": cid} pour récupérer le texte intégral
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.tasks import enqueue_ingestion

logger = logging.getLogger(__name__)


# --- Constants ---------------------------------------------------------------

_REQUEST_TIMEOUT = 60.0
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_TOKEN_REFRESH_MARGIN = 60  # seconds before expiry to refresh proactively
_PAGE_SIZE = 50  # /search results per page
_MAX_PAGES = 5  # safety cap (5 × 50 = 250 max decisions per sync call)

_FOND = "CONSTIT"  # validé en phase A — fond Légifrance Conseil constitutionnel


# --- Types ------------------------------------------------------------------


@dataclass
class CcDecision:
    """A single Conseil constitutionnel decision parsed from PISTE."""
    cid: str  # CONSTEXT...
    title: str
    nature: str  # qpc, dc, lp, etc.
    text: str  # full plain text
    decision_date: date | None = None
    nor: str | None = None


@dataclass
class CcSyncResult:
    total_fetched: int = 0
    new_ingested: int = 0
    already_exists: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


# --- Service -----------------------------------------------------------------


class ConseilConstitService:
    """Sync Conseil constitutionnel decisions from PISTE Légifrance.

    Auth is shared with LegiService — same PISTE app, same client_id.
    """

    # Module-level token cache (shared across instances)
    _cached_token: str | None = None
    _token_expires_at: float = 0.0
    _token_lock: asyncio.Lock | None = None

    def __init__(self) -> None:
        self.base_url = settings.legifrance_base_url.rstrip("/")
        self._client_id = (
            settings.legifrance_client_id or settings.judilibre_client_id
        )
        self._client_secret = (
            settings.legifrance_client_secret or settings.judilibre_client_secret
        )
        self._oauth_url = settings.legifrance_oauth_url

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._token_lock is None:
            cls._token_lock = asyncio.Lock()
        return cls._token_lock

    async def _get_access_token(self) -> str:
        now = time.monotonic()
        if ConseilConstitService._cached_token and now < ConseilConstitService._token_expires_at:
            return ConseilConstitService._cached_token

        async with self._get_lock():
            now = time.monotonic()
            if ConseilConstitService._cached_token and now < ConseilConstitService._token_expires_at:
                return ConseilConstitService._cached_token

            if not self._client_id or not self._client_secret:
                raise RuntimeError(
                    "PISTE credentials missing (legifrance_client_id / _secret)"
                )

            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    self._oauth_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": "openid",
                    },
                )
                r.raise_for_status()
                token_data = r.json()
                ConseilConstitService._cached_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                ConseilConstitService._token_expires_at = (
                    time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN
                )
                return ConseilConstitService._cached_token

    async def _api_post(
        self, client: httpx.AsyncClient, path: str, json_body: dict
    ) -> dict | None:
        url = f"{self.base_url}{path}"
        for attempt in range(_MAX_RETRIES):
            try:
                token = await self._get_access_token()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                response = await client.post(url, headers=headers, json=json_body)
                if response.status_code == 401 and attempt < _MAX_RETRIES - 1:
                    ConseilConstitService._cached_token = None
                    ConseilConstitService._token_expires_at = 0.0
                    continue
                if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY * (2**attempt))
                    continue
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                logger.error("CC API timeout for %s", path)
                return None
        return None

    # ---- Public sync API ----

    async def sync(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        date_start: date | None = None,
        date_end: date | None = None,
        max_decisions: int | None = None,
    ) -> CcSyncResult:
        """Fetch and ingest recent Conseil constitutionnel decisions.

        Strategy :
        1. POST /search?fond=CONSTIT with date filter to list decisions
        2. For each new decision : POST /consult/juri to fetch the full text
        3. Create a Document with source_type=decision_conseil_constitutionnel
        4. Enqueue ingestion
        """
        result = CcSyncResult()

        if not self._client_id or not self._client_secret:
            result.errors = 1
            result.error_messages = ["PISTE credentials non configurés"]
            return result

        if date_end is None:
            date_end = date.today()
        if date_start is None:
            from datetime import timedelta
            date_start = date_end - timedelta(days=30)

        # Load existing CIDs to avoid re-ingestion
        existing_cids = await self._get_existing_cids(db)

        from app.services.storage_service import StorageService
        storage = StorageService()

        def _build_search_payload(page_number: int) -> dict:
            return {
                "fond": _FOND,
                "recherche": {
                    "champs": [
                        {
                            "typeChamp": "ALL",
                            "criteres": [
                                {
                                    "typeRecherche": "EXACTE",
                                    "valeur": "*",
                                    "operateur": "ET",
                                }
                            ],
                            "operateur": "ET",
                        }
                    ],
                    "filtres": [
                        {
                            "facette": "DATE_DECISION",
                            "dates": {
                                "start": date_start.isoformat(),
                                "end": date_end.isoformat(),
                            },
                        }
                    ],
                    "pageNumber": page_number,
                    "pageSize": _PAGE_SIZE,
                    "sort": "DATE_DESC",
                    "typePagination": "DEFAUT",
                },
            }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            # --- Step 1 : list decisions across pages (capped) ---
            results_list: list[dict] = []
            for page_number in range(1, _MAX_PAGES + 1):
                search_data = await self._api_post(
                    client, "/search", _build_search_payload(page_number)
                )
                if not search_data:
                    if page_number == 1:
                        result.errors = 1
                        result.error_messages.append("Échec /search CONSTIT")
                        return result
                    break
                page_results = search_data.get("results", [])
                if page_number == 1:
                    result.total_fetched = search_data.get(
                        "totalResultNumber", 0
                    )
                if not page_results:
                    break
                results_list.extend(page_results)
                # Stop if we've fetched everything available
                if len(results_list) >= result.total_fetched:
                    break
                # Stop early if we already have enough for the cap
                if max_decisions and len(results_list) >= max_decisions * 2:
                    break

            logger.info(
                "ConseilConstit sync: %d decisions found total (%d collected, %s → %s)",
                result.total_fetched, len(results_list), date_start, date_end,
            )

            # --- Step 2 : fetch each decision text ---
            for raw in results_list:
                if max_decisions and result.new_ingested >= max_decisions:
                    break
                try:
                    titles = raw.get("titles") or []
                    if not titles:
                        continue
                    cid = titles[0].get("cid") or titles[0].get("id")
                    title = titles[0].get("title", "")
                    if not cid:
                        continue

                    if cid in existing_cids:
                        result.already_exists += 1
                        continue

                    # Fetch full text via /consult/juri
                    consult_data = await self._api_post(
                        client, "/consult/juri", {"textId": cid}
                    )
                    if not consult_data:
                        result.errors += 1
                        continue

                    text_obj = consult_data.get("text") or {}
                    full_text = text_obj.get("texte") or ""
                    if not full_text or len(full_text) < 100:
                        # No usable content — count as skipped, not error
                        # (happens for very old or in-progress decisions)
                        result.already_exists += 1
                        continue

                    # Parse meta
                    nature = (raw.get("nature") or "").lower()
                    nor = raw.get("nor")
                    decision_date = self._parse_date_from_title(title)

                    decision = CcDecision(
                        cid=cid,
                        title=title,
                        nature=nature,
                        text=full_text,
                        decision_date=decision_date,
                        nor=nor,
                    )

                    doc = await self._create_document(db, decision, user_id, storage)
                    await enqueue_ingestion(str(doc.id))
                    existing_cids.add(cid)
                    result.new_ingested += 1
                except Exception as exc:
                    result.errors += 1
                    msg = f"Erreur décision {raw.get('titles', [{}])[0].get('cid', '?')}: {exc}"
                    result.error_messages.append(msg[:200])
                    logger.warning(msg)

        logger.info(
            "ConseilConstit sync completed: %d total, %d new, %d existing, %d errors",
            result.total_fetched, result.new_ingested,
            result.already_exists, result.errors,
        )
        return result

    # ---- Helpers ----

    @staticmethod
    def _parse_date_from_title(title: str) -> date | None:
        """Extract decision date from a title like 'Décision 2025-1175 QPC - 05 décembre 2025 - …'."""
        import re
        # Match patterns: '05 décembre 2025', '5 janvier 2024', etc.
        months = {
            "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5,
            "juin": 6, "juillet": 7, "août": 8, "septembre": 9, "octobre": 10,
            "novembre": 11, "décembre": 12,
        }
        m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", title)
        if m:
            day, month_str, year = m.groups()
            month = months.get(month_str.lower())
            if month:
                try:
                    return date(int(year), month, int(day))
                except ValueError:
                    return None
        return None

    async def _get_existing_cids(self, db: AsyncSession) -> set[str]:
        """Set of already-ingested CC decision CIDs (stored as numero_pourvoi)."""
        result = await db.execute(
            select(Document.numero_pourvoi).where(
                Document.source_type == "decision_conseil_constitutionnel",
                Document.organisation_id.is_(None),
                Document.numero_pourvoi.isnot(None),
            )
        )
        return {row[0] for row in result.all()}

    async def _create_document(
        self,
        db: AsyncSession,
        decision: CcDecision,
        user_id: uuid.UUID,
        storage,
    ) -> Document:
        source_type = "decision_conseil_constitutionnel"
        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]

        # Build display name : Cons. const., DD/MM/YYYY, n° 2025-1175 QPC
        # Robust to missing date / missing number — never produces double commas
        # or trailing 'n°' fragments. Falls back to the raw PISTE title.
        import re
        num_match = re.search(r"(\d{4}-\d{1,4})\s*(QPC|DC|LP|FNR|L|I|D)?", decision.title)
        num_str = ""
        if num_match:
            num_part = num_match.group(1)
            type_part = num_match.group(2) or decision.nature.upper()
            num_str = f"{num_part} {type_part}".strip()

        parts = ["Cons. const."]
        if decision.decision_date:
            parts.append(decision.decision_date.strftime("%d/%m/%Y"))
        if num_str:
            parts.append(f"n° {num_str}")
        name = ", ".join(parts)
        # If we have only the prefix (no date AND no num), fall back to raw title
        if name == "Cons. const." and decision.title:
            name = decision.title[:200]

        file_id = uuid.uuid4()
        safe_cid = decision.cid.replace(" ", "_")
        storage_path = f"common/conseil_constit/{file_id}_{safe_cid}.txt"
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
            juridiction="Conseil constitutionnel",
            chambre=None,
            formation=None,
            numero_pourvoi=decision.cid,  # we use cid as the dedup key
            date_decision=decision.decision_date,
            solution=None,
            publication=decision.nature.upper() if decision.nature else None,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc
