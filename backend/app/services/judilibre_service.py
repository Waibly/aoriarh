"""Service de synchronisation avec l'API Judilibre (Cour de cassation).

Récupère les arrêts de la chambre sociale publiés au Bulletin
et les ingère comme documents communs dans le pipeline RAG.

Utilise l'endpoint /export qui retourne les décisions complètes
(texte intégral + zones + métadonnées) par batch.
"""

import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

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
# Throttle between consecutive Judilibre calls. PISTE allows ~20 req/s
# in burst — at 0.3s/call we use 3 req/s which is well under the limit.
_API_THROTTLE = 0.3

# Valid Cour de cassation chamber codes per Judilibre API
# (the API rejects anything else with 400). Source: live probe of /export
# error response → "[pl,mi,civ1,civ2,civ3,comm,soc,cr,creun,ordo,allciv,other]"
CC_CHAMBERS = {"pl", "mi", "civ1", "civ2", "civ3", "comm", "soc", "cr", "creun", "ordo", "allciv", "other"}

# Regex matching the chamber name of a Cour d'appel "social" decision.
# Judilibre stores CA chambers as free text ("Chambre sociale", "5e ch.
# sociale", "Pôle social", etc.) and its chamber filter does NOT work
# for jurisdiction=ca. We must fetch all CAs and filter in Python on
# this regex. Tested against a 30-day sample of 5758 CA results from
# the live API: matches ~1037 social chambers, 0 false positives on
# civil/commercial chambers.
_CA_SOCIAL_CHAMBER_RE = re.compile(
    r"\b(?:social\w*|soc\.?|prud\w*|p[oô]le\s+social)\b",
    re.IGNORECASE,
)

# Sources sélectionnables depuis l'UI admin pour la sync personnalisée.
# Chaque entrée porte tout ce dont l'API et le worker ont besoin pour
# router vers le bon service (Cass via /export, CA via sync_ca_chambre_sociale,
# Conseil constit via ConseilConstitService).
SOURCE_DEFINITIONS: dict[str, dict] = {
    "cass_soc": {
        "label": "Cass. soc (chambre sociale)",
        "service": "judilibre",
        "jurisdiction": "cc",
        "chamber": "soc",
        # Chambre sociale = cœur du droit du travail : on ingère TOUTES les
        # décisions (publiées au Bulletin ET inédites), pas seulement le Bulletin.
        # Les inédits représentent ~90% du volume et font jurisprudence
        # (ex. Cass. soc. 09/04/2026 n° 24-22.122, un inédit). Les autres
        # chambres restent limitées au Bulletin (publication="b").
        "publication": None,
        "source_type": "arret_cour_cassation",
    },
    "cass_cr": {
        "label": "Cass. crim (chambre criminelle)",
        "service": "judilibre",
        "jurisdiction": "cc",
        "chamber": "cr",
        "publication": "b",
        "source_type": "arret_cour_cassation",
    },
    "cass_comm": {
        "label": "Cass. com (chambre commerciale)",
        "service": "judilibre",
        "jurisdiction": "cc",
        "chamber": "comm",
        "publication": "b",
        "source_type": "arret_cour_cassation",
    },
    "cass_civ2": {
        "label": "Cass. civ2 (sécurité sociale / AT-MP)",
        "service": "judilibre",
        "jurisdiction": "cc",
        "chamber": "civ2",
        "publication": "b",
        "source_type": "arret_cour_cassation",
    },
    # Formations « supérieures » de la Cour de cassation : arrêts d'AP et
    # de chambre mixte. Volumes faibles (~10-15/an chacune toutes matières)
    # mais valeur jurisprudentielle maximale — leurs décisions s'imposent
    # à toutes les chambres simples, y compris en droit social.
    "cass_pl": {
        "label": "Cass. AP (Assemblée plénière)",
        "service": "judilibre",
        "jurisdiction": "cc",
        "chamber": "pl",
        "publication": "b",
        "source_type": "arret_cour_cassation",
    },
    "cass_mi": {
        "label": "Cass. mi (Chambre mixte)",
        "service": "judilibre",
        "jurisdiction": "cc",
        "chamber": "mi",
        "publication": "b",
        "source_type": "arret_cour_cassation",
    },
    "ca_soc": {
        "label": "Cour d'appel — chambre sociale",
        "service": "judilibre_ca",
        "jurisdiction": "ca",
        "chamber": None,
        "publication": None,
        "source_type": "arret_cour_appel",
    },
    "conseil_constit": {
        "label": "Conseil constitutionnel",
        "service": "conseil_constit",
        "jurisdiction": None,
        "chamber": None,
        "publication": None,
        "source_type": "decision_conseil_constitutionnel",
    },
}


_CHAMBER_MAP = {
    # Cour de cassation — codes API → libellés humains
    "soc": "Chambre sociale",
    "civ1": "Chambre civile 1",
    "civ2": "Chambre civile 2",
    "civ3": "Chambre civile 3",
    "comm": "Chambre commerciale",  # Judilibre code is 'comm' (not 'com')
    "cr": "Chambre criminelle",      # Judilibre code is 'cr' (not 'crim')
    "mi": "Chambre mixte",
    "pl": "Assemblée plénière",
    "creun": "Chambres réunies",
    "ordo": "Ordonnances",
    "allciv": "Toutes chambres civiles",
    # Aliases ascendants pour la rétro-compat (anciennes données en BDD)
    "com": "Chambre commerciale",
    "crim": "Chambre criminelle",
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
    # Decisions returned by the API but rejected by an in-process filter
    # (e.g. CA arrêts that are not chambre sociale). Tracked separately
    # from already_exists so the SyncBanner can report honest counts.
    filtered_out: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


@dataclass
class DeletedDecision:
    """Une décision qu'on détient mais qui a disparu de Judilibre."""

    doc_id: str
    source_type: str
    numero_pourvoi: str
    name: str
    date_decision: str | None


@dataclass
class DeletedScanResult:
    """Résultat du scan de présence (lecture seule, ne supprime rien)."""

    checked: int = 0
    present: int = 0
    # Décisions confirmées disparues de Judilibre.
    gone: list[DeletedDecision] = field(default_factory=list)
    # Décisions qu'on n'a pas pu vérifier (export d'un jour en échec, pas
    # de date…) : on ne conclut JAMAIS à une suppression sur un doute.
    unknown: int = 0


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

        # Validate chamber early so we don't burn an API call to discover
        # a typo. Judilibre rejects unknown chamber codes with HTTP 400.
        if jurisdiction == "cc" and chamber not in CC_CHAMBERS:
            result.errors = 1
            result.error_messages = [
                f"Code de chambre invalide pour Cass : '{chamber}'. "
                f"Valides : {sorted(CC_CHAMBERS)}"
            ]
            return result
        if jurisdiction not in {"cc", "ca", "tj", "tcom"}:
            # Judilibre v1.0 supports only these four jurisdictions.
            result.errors = 1
            result.error_messages = [
                f"Juridiction non supportée par Judilibre : '{jurisdiction}'. "
                f"Valides : cc, ca, tj, tcom"
            ]
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
                    "date_start": date_start.isoformat(),
                    "date_end": date_end.isoformat(),
                    "batch": batch_num,
                    "batch_size": _BATCH_SIZE,
                }
                # Filtre de publication (ex. "b" = Bulletin). On l'OMET quand
                # il vaut None : passer publication=None/vide à l'API la fait
                # renvoyer 0 résultat. Absent = toutes publications (inédits inclus).
                if publication:
                    api_params["publication"] = publication
                # Chamber filter only applies to Cour de cassation in Judilibre.
                # For other jurisdictions we omit it (Judilibre returns all
                # chambers of that jurisdiction).
                if jurisdiction == "cc":
                    api_params["chamber"] = chamber
                data = await self._api_get(client, "/export", params=api_params)
                if data is None:
                    # _api_get returns None for 404 / 416 / exhausted retries.
                    # If we've already received at least one batch, treat it
                    # as end of pagination (no error). If batch_num == 0, the
                    # source is genuinely unreachable → report it.
                    if batch_num == 0:
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

    async def sync_ca_chambre_sociale(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        date_start: date | None = None,
        date_end: date | None = None,
        max_decisions: int | None = None,
    ) -> SyncResult:
        """Synchronise Cour d'appel chambre sociale decisions only.

        Judilibre's chamber filter does NOT work for jurisdiction='ca'
        (it returns 0 results when set). We must therefore fetch ALL CA
        arrêts in the time window and filter in Python on the chamber
        free-text field using ``_CA_SOCIAL_CHAMBER_RE``.

        - source_type is always 'arret_cour_appel'
        - decisions are sorted by date desc by Judilibre, so capping
          via max_decisions keeps the most recent ones
        - filtered_out tracks how many CA arrêts were rejected by the
          chamber regex (≈ 80% of all CA results historically)
        """
        result = SyncResult()

        if not self._client_id or not self._client_secret:
            result.errors = 1
            result.error_messages = ["JUDILIBRE_CLIENT_ID / JUDILIBRE_CLIENT_SECRET non configurés"]
            return result

        if date_end is None:
            date_end = date.today()
        if date_start is None:
            date_start = date(date_end.year - 1, date_end.month, date_end.day)

        existing_pourvois = await self._get_existing_pourvois(
            db, source_type="arret_cour_appel"
        )

        from app.services.storage_service import StorageService
        storage = StorageService()

        batch_num = 0
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            while True:
                api_params: dict = {
                    "jurisdiction": "ca",
                    "date_start": date_start.isoformat(),
                    "date_end": date_end.isoformat(),
                    "batch": batch_num,
                    "batch_size": _BATCH_SIZE,
                }
                data = await self._api_get(client, "/export", params=api_params)
                if data is None:
                    # See comment in sync(): None on batch 0 = real error,
                    # None on later batches = end of pagination (e.g. 416
                    # when we hit Judilibre's 10 000-result hard cap on CA).
                    if batch_num == 0:
                        result.errors += 1
                        result.error_messages.append(f"Erreur API batch {batch_num}")
                    break

                if batch_num == 0:
                    result.total_fetched = data.get("total", 0)
                    logger.info(
                        "Judilibre CA chambre sociale: %d total CA arrêts in window %s → %s",
                        result.total_fetched, date_start, date_end,
                    )

                items = data.get("results", [])
                if not items:
                    break

                for raw in items:
                    if max_decisions and result.new_ingested >= max_decisions:
                        break

                    # Filter on chamber free-text
                    chamber_str = (raw.get("chamber") or "")
                    if not _CA_SOCIAL_CHAMBER_RE.search(chamber_str):
                        result.filtered_out += 1
                        continue

                    try:
                        decision = self._parse_decision(raw)
                        if decision is None:
                            result.errors += 1
                            continue
                        if not decision.numero_pourvoi:
                            result.errors += 1
                            continue
                        if decision.numero_pourvoi in existing_pourvois:
                            result.already_exists += 1
                            continue

                        doc = await self._create_document(
                            db, decision, user_id, storage,
                            source_type="arret_cour_appel",
                        )
                        await enqueue_ingestion(str(doc.id))
                        existing_pourvois.add(decision.numero_pourvoi)
                        result.new_ingested += 1
                    except Exception as exc:
                        result.errors += 1
                        pourvoi = raw.get("number", raw.get("id", "?"))
                        msg = f"Erreur décision CA {pourvoi}: {exc}"
                        result.error_messages.append(msg)
                        logger.warning(msg)

                if max_decisions and result.new_ingested >= max_decisions:
                    break
                if not data.get("next_batch"):
                    break
                batch_num += 1

        logger.info(
            "CA chambre sociale: total=%d filtered_out=%d already=%d new=%d errors=%d",
            result.total_fetched, result.filtered_out,
            result.already_exists, result.new_ingested, result.errors,
        )
        return result

    async def preview_count(
        self,
        *,
        jurisdiction: str,
        chamber: str | None,
        publication: str | None,
        date_start: date,
        date_end: date,
    ) -> int:
        """Interroge Judilibre pour le nombre total d'arrêts sur la plage,
        sans rien ingérer. Utilisé par le formulaire admin pour afficher
        un preview avant de lancer la sync.
        """
        if not self._client_id or not self._client_secret:
            raise RuntimeError("JUDILIBRE_CLIENT_ID / JUDILIBRE_CLIENT_SECRET non configurés")

        params: dict = {
            "jurisdiction": jurisdiction,
            "date_start": date_start.isoformat(),
            "date_end": date_end.isoformat(),
            "batch": 0,
            "batch_size": 1,
        }
        if jurisdiction == "cc" and chamber:
            params["chamber"] = chamber
        if publication:
            params["publication"] = publication

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            data = await self._api_get(client, "/export", params=params)
        if data is None:
            raise RuntimeError("Erreur ou aucune donnée retournée par Judilibre /export")
        return int(data.get("total", 0))

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

    async def find_deleted_decisions(self, db: AsyncSession) -> DeletedScanResult:
        """Scan LECTURE SEULE : repère les arrêts qu'on détient mais qui ont
        disparu de Judilibre (retirés en amont par la Cour de cassation).

        Ne supprime rien — sert au contrôle de présence mensuel qui SIGNALE
        les décisions à examiner.

        Deux méthodes selon la source, car les numéros ne se cherchent pas
        de la même façon :
        - Cass : ``/search`` par numéro de pourvoi (indexé, recherche exacte).
        - CA   : les numéros de rôle ne sont PAS cherchables à l'exact ; on
                 exporte les décisions CA du jour et on teste la présence du
                 numéro dans ce jour-là.
        Conseil constitutionnel : hors Judilibre, ignoré.

        En cas de doute (export d'un jour en échec, pas de date), la décision
        est comptée ``unknown`` — jamais ``gone``.
        """
        from collections import defaultdict

        result = DeletedScanResult()
        if not self._client_id or not self._client_secret:
            logger.warning("find_deleted_decisions: credentials PISTE absents")
            return result

        rows = (
            await db.execute(
                select(
                    Document.id,
                    Document.source_type,
                    Document.numero_pourvoi,
                    Document.name,
                    Document.date_decision,
                    Document.juridiction,
                ).where(
                    Document.organisation_id.is_(None),
                    Document.source_type.in_(
                        ["arret_cour_cassation", "arret_cour_appel"]
                    ),
                    Document.numero_pourvoi.isnot(None),
                    Document.numero_pourvoi != "",
                )
            )
        ).all()

        cass = [r for r in rows if r.source_type == "arret_cour_cassation"]
        ca = [r for r in rows if r.source_type == "arret_cour_appel"]
        logger.info(
            "find_deleted_decisions: %d Cass + %d CA à vérifier", len(cass), len(ca)
        )

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            # === Cour de cassation : recherche par numéro de pourvoi ===
            for r in cass:
                result.checked += 1
                data = await self._api_get(
                    client,
                    "/search",
                    {"query": r.numero_pourvoi, "jurisdiction": ["cc"], "page_size": 10},
                )
                if data is None:
                    result.unknown += 1
                    continue
                if self._number_in_results(r.numero_pourvoi, data.get("results", [])):
                    result.present += 1
                else:
                    result.gone.append(self._to_deleted(r))

            # === Cours d'appel : export jour par jour, test de présence ===
            by_day: dict[str, list] = defaultdict(list)
            for r in ca:
                if r.date_decision:
                    by_day[r.date_decision.isoformat()].append(r)
                else:
                    result.checked += 1
                    result.unknown += 1  # sans date, on ne peut pas vérifier

            for day, docs in by_day.items():
                day_index = await self._export_ca_day_numbers(client, day)
                for r in docs:
                    result.checked += 1
                    if day_index is None:
                        result.unknown += 1  # export du jour en échec → doute
                        continue
                    pairs, locations = day_index
                    num = self._norm_number(r.numero_pourvoi)
                    loc = self._location_code_from_label(r.juridiction)
                    if loc is not None and (loc, num) in pairs:
                        result.present += 1
                    elif loc is not None and loc in locations:
                        # La cour a publié d'autres arrêts ce jour-là (export
                        # sain) mais pas celui-ci → vraiment disparu.
                        result.gone.append(self._to_deleted(r))
                    elif loc is None and num in {n for _, n in pairs}:
                        # Pas de code cour exploitable : repli sur le numéro seul.
                        result.present += 1
                    else:
                        # Cour absente du jour (ou libellé non mappable) :
                        # on ne conclut pas pour éviter un faux positif.
                        result.unknown += 1

        logger.info(
            "find_deleted_decisions terminé : %d vérifiées, %d présentes, "
            "%d disparues, %d indéterminées",
            result.checked, result.present, len(result.gone), result.unknown,
        )
        return result

    # --- Private methods ---

    @staticmethod
    def _norm_number(s: str) -> str:
        """Normalise un numéro pour comparaison robuste (retire ponctuation)."""
        return re.sub(r"[^0-9a-z]", "", (s or "").lower())

    @classmethod
    def _number_in_results(cls, numero: str, results: list[dict]) -> bool:
        """Vrai si ``numero`` figure exactement parmi les résultats /search."""
        target = cls._norm_number(numero)
        for res in results:
            nums = list(res.get("numbers") or [])
            if res.get("number"):
                nums.append(res["number"])
            if any(cls._norm_number(n) == target for n in nums):
                return True
        return False

    @staticmethod
    def _to_deleted(row) -> "DeletedDecision":
        return DeletedDecision(
            doc_id=str(row.id),
            source_type=row.source_type,
            numero_pourvoi=row.numero_pourvoi,
            name=row.name,
            date_decision=row.date_decision.isoformat() if row.date_decision else None,
        )

    @staticmethod
    def _location_code_from_label(juridiction: str | None) -> str | None:
        """Retrouve le code 'location' Judilibre (ex. ``ca_reims``) depuis le
        libellé stocké (ex. ``Cour d'appel de Reims``).

        Le libellé a été construit DEPUIS ce code à l'ingestion via une
        transformation déterministe (``location.replace('ca_','').replace
        ('_',' ').title()``), donc l'inverse est fiable. Renvoie ``None`` si
        le libellé ne suit pas ce schéma (on retombera sur le numéro seul).
        """
        if not juridiction:
            return None
        rest = juridiction
        for prefix in (
            "Cour d'appel de ", "Cour d'appel d'", "Cour d'appel du ",
            "Cour d'appel des ", "Cour d'appel ",
        ):
            if rest.startswith(prefix):
                rest = rest[len(prefix):]
                break
        else:
            return None  # libellé inattendu
        rest = rest.strip().lower()
        if not rest:
            return None
        return "ca_" + rest.replace(" ", "_")

    async def _export_ca_day_numbers(
        self, client: httpx.AsyncClient, day: str
    ) -> tuple[set[tuple[str, str]], set[str]] | None:
        """Index des arrêts CA présents sur Judilibre un jour donné.

        Retourne ``(pairs, locations)`` où ``pairs`` est l'ensemble des couples
        ``(location, numéro_normalisé)`` et ``locations`` l'ensemble des cours
        ayant publié ce jour-là. Les numéros de rôle CA n'étant pas uniques
        entre cours, le couple (cour, numéro) est nécessaire pour décider.

        Retourne ``None`` si l'export a échoué (ou jour anormalement vide),
        pour ne JAMAIS conclure à une suppression sur un export incomplet —
        c'est ce qui causait les faux positifs lors du diagnostic initial.
        """
        pairs: set[tuple[str, str]] = set()
        locations: set[str] = set()
        date_end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        batch = 0
        while batch < 200:  # garde-fou (CA ~1000/jour, bien sous la limite)
            data = await self._api_get(
                client,
                "/export",
                {
                    "jurisdiction": "ca",
                    "date_start": day,
                    "date_end": date_end,
                    "batch": batch,
                    "batch_size": _BATCH_SIZE,
                },
            )
            if data is None:
                # _api_get renvoie None sur 404/416/échec réseau. À batch 0,
                # c'est un échec dur → on ne conclut pas.
                if batch == 0:
                    return None
                break
            # Un jour ouvré a toujours des centaines d'arrêts CA : total 0 au
            # premier batch est suspect (anomalie API) → on ne conclut pas.
            if batch == 0 and data.get("total", 0) == 0:
                return None
            items = data.get("results", [])
            if not items:
                break
            for x in items:
                loc = (x.get("location") or "").lower()
                if loc:
                    locations.add(loc)
                nums = list(x.get("numbers") or [])
                if x.get("number"):
                    nums.append(x["number"])
                for n in nums:
                    pairs.add((loc, self._norm_number(n)))
            if not data.get("next_batch"):
                break
            batch += 1
        return pairs, locations

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

        # Throttle to stay safely below the PISTE burst limit (~20 req/s).
        await asyncio.sleep(_API_THROTTLE)

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

                # Judilibre returns 416 (Range Not Satisfiable) when the
                # caller paginates past the API's hard cap (~10 000 results
                # = batch=200 × batch_size=50). Treat it as end-of-pagination
                # rather than a real error : the data already collected is
                # valid, only the next page is unavailable.
                if response.status_code == 416:
                    logger.info(
                        "Judilibre 416 — pagination cap reached at %s, stopping",
                        params.get("batch") if params else "?",
                    )
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
