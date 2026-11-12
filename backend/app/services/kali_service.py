"""Service d'intégration avec l'API KALI (Légifrance / PISTE).

Gère l'authentification OAuth2, la récupération du référentiel IDCC,
le fetch des textes de conventions collectives, et l'ingestion dans le pipeline RAG.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ccn import CcnReference, OrganisationConvention
from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.tasks import enqueue_ingestion

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 60.0
_RETRY_DELAY = 2.0
_MAX_RETRIES = 3
_TOKEN_REFRESH_MARGIN = 300
_API_THROTTLE = 0.2  # 5 req/s max
_LIST_PAGE_SIZE = 1000  # /list/conventions accepts 1000 texts per page
_LIST_WINDOW = 10_000  # results reachable per query (later pages repeat)


@dataclass
class KaliInstallResult:
    """Result of a CCN installation."""

    articles_count: int = 0
    documents_created: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


@dataclass
class KaliSyncResult:
    """Result of a CCN sync operation."""

    idcc: str = ""
    update_needed: bool = False
    content_hash: str = ""
    new_document_id: str | None = None
    old_document_ids: list[str] = field(default_factory=list)
    articles_count: int = 0
    error: str | None = None


@dataclass
class KaliBulkSyncResult:
    """Result of a bulk CCN sync."""

    total_idcc: int = 0
    updates_needed: int = 0
    skipped_identical: int = 0
    errors: int = 0
    details: list[KaliSyncResult] = field(default_factory=list)


@dataclass
class CcnReferenceRefreshResult:
    """Result of a CCN reference refresh from KALI."""

    listed_texts: int = 0
    containers: int = 0
    created: int = 0
    updated: int = 0
    not_installable: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    created_idcc: list[str] = field(default_factory=list)


@dataclass
class AniSyncResult:
    """Result of an ANI (accords nationaux interprofessionnels) sync."""

    fetched: int = 0  # textes ANI listés dans KALI
    created: int = 0  # nouveaux documents ingérés
    skipped: int = 0  # déjà ingérés / hors périmètre / sans contenu
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    titles_created: list[str] = field(default_factory=list)


class KaliService:
    """Connects to the KALI API on PISTE to fetch conventions collectives."""

    _cached_token: str | None = None
    _token_expires_at: float = 0.0
    _token_lock: asyncio.Lock | None = None

    def __init__(self) -> None:
        self.base_url = settings.legifrance_base_url.rstrip("/")
        self._client_id = settings.legifrance_client_id or settings.judilibre_client_id
        self._client_secret = settings.legifrance_client_secret or settings.judilibre_client_secret
        self._oauth_url = settings.legifrance_oauth_url

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._token_lock is None:
            cls._token_lock = asyncio.Lock()
        return cls._token_lock

    async def _get_access_token(self) -> str:
        """Get a valid OAuth2 Bearer token, fetching/refreshing as needed."""
        now = time.monotonic()
        if KaliService._cached_token and now < KaliService._token_expires_at:
            return KaliService._cached_token

        async with self._get_lock():
            now = time.monotonic()
            if KaliService._cached_token and now < KaliService._token_expires_at:
                return KaliService._cached_token

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

            KaliService._cached_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            KaliService._token_expires_at = time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN
            logger.info("PISTE/Légifrance OAuth2 token obtained (expires in %ds)", expires_in)
            return KaliService._cached_token

    # --- Public API ---

    @staticmethod
    async def seed_ccn_reference(db: AsyncSession) -> int:
        """Seed the CCN reference table from static data (no API call).

        Uses the ~50 most common CCN from @socialgouv/kali-data.
        Safe to call multiple times (upsert).
        """
        from app.services.ccn_seed import CCN_SEED

        count = 0
        for idcc, kali_id, titre, titre_court in CCN_SEED:
            existing = await db.get(CcnReference, idcc)
            if existing:
                existing.titre = titre
                existing.titre_court = titre_court or None
                existing.kali_id = kali_id
            else:
                db.add(
                    CcnReference(
                        idcc=idcc,
                        titre=titre,
                        titre_court=titre_court or None,
                        kali_id=kali_id,
                        etat="VIGUEUR_ETEN",
                        last_api_check=datetime.now(UTC),
                    )
                )
            count += 1

        await db.commit()
        logger.info("CCN reference seeded: %d conventions from static data", count)
        return count

    async def refresh_ccn_reference(self, db: AsyncSession) -> CcnReferenceRefreshResult:
        """Refresh the CCN reference table from KALI (all conventions in force).

        KALI's /list/conventions lists TEXTS (base, avenants, accords), each
        carrying its IDCC and container id; pages start at 1. Every container
        is then read to get the convention's own title and status and to check
        that it holds at least one text in force — the same condition as
        installation, so no empty convention is offered to users.

        Extended and non-extended conventions are both kept. Existing rows are
        updated (title, KALI id, status) but their curated short title is
        preserved; a convention absent from KALI is left untouched. Any listing
        failure aborts before writing anything.
        """
        if not self._client_id or not self._client_secret:
            raise RuntimeError("Identifiants Légifrance absents")

        result = CcnReferenceRefreshResult()
        containers: dict[str, set[str]] = {}
        seen_texts: set[str] = set()

        def collect(texts: list[dict]) -> None:
            for text in texts:
                seen_texts.add(text.get("id") or "")
                idcc = str(text.get("idcc") or "").strip()
                container_id = text.get("cidConteneur") or ""
                if idcc.isdigit() and len(idcc) <= 4 and container_id.startswith("KALICONT"):
                    containers.setdefault(idcc.zfill(4), set()).add(container_id)

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            # KALI paging is lossy on large result sets (at most _LIST_WINDOW
            # results, and pages overlap). A broad sweep only DISCOVERS the IDCC;
            # each IDCC is then listed on its own — a small, complete answer —
            # to find all its containers.
            for status_ in ("VIGUEUR", "VIGUEUR_ETEN", "VIGUEUR_NON_ETEN"):
                collect(await self._list_texts(client, {"legalStatus": [status_]}))
            discovered = set(containers)
            known = set((await db.execute(select(CcnReference.idcc))).scalars())
            for idcc in sorted(discovered | known):
                collect(
                    await self._list_texts(
                        client,
                        {
                            "idcc": idcc.lstrip("0") or "0",
                            "legalStatus": ["VIGUEUR", "VIGUEUR_ETEN", "VIGUEUR_NON_ETEN"],
                        },
                    )
                )
            result.listed_texts = len(seen_texts)

            if not containers:
                raise RuntimeError("KALI n'a renvoyé aucune convention")
            logger.info(
                "CCN reference refresh: %d texts listed, %d IDCC",
                result.listed_texts,
                len(containers),
            )

            now = datetime.now(UTC)
            for idcc, container_ids in sorted(containers.items()):
                existing = await db.get(CcnReference, idcc)
                best: tuple[int, str, str, str] | None = None  # (texts, id, titre, etat)
                for container_id in sorted(container_ids):
                    await asyncio.sleep(_API_THROTTLE)
                    result.containers += 1
                    try:
                        container = await self._api_post(
                            client, "/consult/kaliCont", json_body={"id": container_id}
                        )
                    except Exception as exc:
                        result.errors += 1
                        result.error_messages.append(f"IDCC {idcc} ({container_id}) : {exc}")
                        continue
                    if container is None:
                        continue
                    in_force, etat = self._container_in_force(container)
                    if not in_force:
                        continue
                    # The convention already chosen by users wins a tie-break.
                    chosen = existing is not None and existing.kali_id == container_id
                    rank = in_force + (10**6 if chosen else 0)
                    if best is None or rank > best[0]:
                        titre = re.sub(r"\s+", " ", container.get("titre") or "").strip()
                        best = (rank, container_id, titre, etat)
                if best is None:
                    result.not_installable += 1
                    continue
                _, container_id, titre, etat = best
                if existing:
                    changed = (existing.titre, existing.kali_id, existing.etat) != (
                        titre or existing.titre,
                        container_id,
                        etat,
                    )
                    existing.titre = titre or existing.titre
                    existing.kali_id = container_id
                    existing.etat = etat
                    existing.last_api_check = now
                    if not existing.titre_court:
                        existing.titre_court = self._make_titre_court(existing.titre)
                    if changed:
                        result.updated += 1
                else:
                    db.add(
                        CcnReference(
                            idcc=idcc,
                            titre=titre,
                            titre_court=self._make_titre_court(titre),
                            kali_id=container_id,
                            etat=etat,
                            last_api_check=now,
                        )
                    )
                    result.created += 1
                    result.created_idcc.append(idcc)

        await db.commit()
        logger.info(
            "CCN reference refreshed: %d created, %d updated, %d not installable, %d errors",
            result.created,
            result.updated,
            result.not_installable,
            result.errors,
        )
        return result

    async def _list_texts(self, client: httpx.AsyncClient, criteria: dict) -> list[dict]:
        """Every text KALI /list/conventions returns for these criteria.

        Pages start at 1. Beyond _LIST_WINDOW results later pages repeat the
        last one, and pages of a large set overlap: when one order does not
        fit in a single page, the reverse order is read too."""
        texts: list[dict] = []
        for sort in ("DATE_PUBLI_ASC", "DATE_PUBLI_DESC"):
            page = 1
            total = 0
            while True:
                await asyncio.sleep(_API_THROTTLE)
                data = await self._api_post(
                    client,
                    "/list/conventions",
                    json_body={
                        **criteria,
                        "pageNumber": page,
                        "pageSize": _LIST_PAGE_SIZE,
                        "sort": sort,
                    },
                )
                if data is None:
                    raise RuntimeError(f"KALI /list/conventions {criteria} page {page}")
                batch = data.get("results") or []
                texts.extend(batch)
                total = data.get("totalResultNumber") or 0
                read = page * _LIST_PAGE_SIZE
                if not batch or read >= total or read >= _LIST_WINDOW:
                    break
                page += 1
            if total <= _LIST_PAGE_SIZE:
                break
        return texts

    @staticmethod
    def _container_in_force(container: dict) -> tuple[int, str]:
        """Count a container's texts in force and read the convention's status.

        The status is the base text's (VIGUEUR_ETEN / VIGUEUR_NON_ETEN) when it
        is in force, else plain VIGUEUR."""
        count = 0
        base_etat = ""

        def walk(items: list[dict]) -> None:
            nonlocal count
            for item in items:
                if (item.get("id") or "").startswith("KALITEXT") and (
                    item.get("etat") or ""
                ).startswith("VIGUEUR"):
                    count += 1
                walk(item.get("sections") or [])

        sections = container.get("sections") or []
        for section in sections:
            title = (section.get("title") or section.get("titre") or "").lower()
            etat = section.get("etat") or ""
            if title.startswith("texte de base") and etat.startswith("VIGUEUR"):
                base_etat = base_etat or etat
        walk(sections)
        return count, base_etat or "VIGUEUR"

    async def install_convention(
        self,
        db: AsyncSession,
        org_conv: OrganisationConvention,
        user_id: uuid.UUID,
        force_refetch: bool = False,
    ) -> KaliInstallResult:
        """Fetch a CCN from KALI and ingest as COMMON documents (shared).

        If common docs already exist for this IDCC, just link (no re-fetch).
        If not, fetch from KALI and create common docs.
        Blue-green for updates.
        If force_refetch=True, delete existing common docs and re-fetch.
        """
        result = KaliInstallResult()

        org_conv.status = "fetching"
        await db.commit()

        try:
            ccn_ref = await db.get(CcnReference, org_conv.idcc)
            if not ccn_ref or not ccn_ref.kali_id:
                raise ValueError(f"IDCC {org_conv.idcc} introuvable dans le référentiel")

            # Check if common docs already exist for this IDCC
            existing_common = await self._find_common_ccn_docs(db, org_conv.idcc)

            old_kali_ids: list[str] = []
            if existing_common and force_refetch:
                # Rebuild only the generated KALI snapshot (BOCC documents for
                # the same IDCC are separate legal sources). Blue-green: the old
                # snapshot is removed once its replacement is indexed.
                old_kali_ids = [
                    str(doc.id) for doc in existing_common if self._is_generated_kali_document(doc)
                ]
                logger.info(
                    "KALI IDCC %s: force_refetch — replacing %d common docs",
                    org_conv.idcc,
                    len(old_kali_ids),
                )
                existing_common = [
                    doc for doc in existing_common if not self._is_generated_kali_document(doc)
                ]

            if existing_common:
                # Only shortcut if we have REAL KALI docs (name starts with
                # "CCN ") that are properly indexed — not just BOCC avenants
                # which happen to match the IDCC in their name.
                kali_docs = [
                    d
                    for d in existing_common
                    if self._is_generated_kali_document(d)
                    and d.indexation_status == "indexed"
                    and d.chunk_count
                ]
                if kali_docs:
                    logger.info(
                        "KALI IDCC %s: KALI docs already exist (%d indexed), linking only",
                        org_conv.idcc,
                        len(kali_docs),
                    )
                    total_chunks = sum(d.chunk_count or 0 for d in kali_docs)
                    org_conv.status = "ready"
                    org_conv.articles_count = total_chunks
                    org_conv.installed_at = datetime.now(UTC)
                    org_conv.last_synced_at = datetime.now(UTC)
                    org_conv.error_message = None
                    await db.commit()

                    # Also ingest any pending BOCC docs for this IDCC
                    try:
                        from app.services.bocc_service import BoccService

                        await BoccService().ingest_bocc_for_idcc(db, org_conv.idcc)
                    except Exception:
                        logger.warning(
                            "KALI IDCC %s: BOCC ingest failed in shortcut path",
                            org_conv.idcc,
                            exc_info=True,
                        )

                    return result
                else:
                    logger.info(
                        "KALI IDCC %s: only BOCC docs found (%d), no indexed "
                        "KALI docs — proceeding with KALI fetch",
                        org_conv.idcc,
                        len(existing_common),
                    )

            # No common docs — fetch from KALI and create
            all_articles, fetch_errors, source_date = await self._fetch_kali_articles(ccn_ref)
            result.errors += len(fetch_errors)
            result.error_messages.extend(fetch_errors)
            result.articles_count = len(all_articles)

            org_conv.status = "indexing"
            await db.commit()

            doc_ids, _ = await self._create_common_docs(db, ccn_ref, all_articles, user_id)
            result.documents_created = len(doc_ids)
            if old_kali_ids:
                await self._enqueue_old_docs_cleanup(old_kali_ids, replacement_ids=doc_ids)

            org_conv.status = "ready"
            org_conv.articles_count = result.articles_count
            org_conv.source_date = source_date
            org_conv.installed_at = datetime.now(UTC)
            org_conv.last_synced_at = datetime.now(UTC)
            org_conv.error_message = None
            await db.commit()

            # Ingest any pending BOCC avenants for this IDCC
            try:
                from app.services.bocc_service import BoccService

                bocc_count = await BoccService().ingest_bocc_for_idcc(db, org_conv.idcc)
                if bocc_count:
                    logger.info(
                        "KALI install IDCC %s: also enqueued %d BOCC docs",
                        org_conv.idcc,
                        bocc_count,
                    )
            except Exception:
                logger.warning(
                    "KALI install IDCC %s: failed to ingest BOCC docs", org_conv.idcc, exc_info=True
                )

        except Exception as exc:
            org_conv.status = "error"
            # User-facing message: never expose internal details (KALI, DNS, etc.)
            raw = str(exc)
            if "n'est pas disponible" in raw or "remplacée" in raw:
                org_conv.error_message = raw[:500]
            else:
                org_conv.error_message = (
                    "L'installation de cette convention collective a échoué. "
                    "Veuillez réessayer. Si le problème persiste, contactez le support."
                )
            await db.commit()
            result.errors += 1
            result.error_messages.append(raw)
            logger.exception("KALI install failed for IDCC %s", org_conv.idcc)

        return result

    def _common_doc_parts(
        self, all_articles: list[dict], ccn_ref: CcnReference
    ) -> tuple[list[tuple[str, str, str | None]], str]:
        """Documents of a KALI snapshot: (name suffix, text, source type override).

        The snapshot hash covers every part, accords included, and is stored on
        the main document to detect a change on the next sync."""
        by_category: dict[str, list[dict]] = {}
        for article in all_articles:
            category = article.get("category")
            key = "annexe" if category in ("annexe", "avenant") else category
            by_category.setdefault(key, []).append(article)
        parts: list[tuple[str, str, str | None]] = []
        for key, suffix in (
            ("base", ""),
            ("annexe", " — Avenants et annexes"),
            ("salaire", " — Grilles de salaires"),
        ):
            if by_category.get(key):
                parts.append(
                    (suffix, self._format_articles_as_markdown(by_category[key], ccn_ref), None)
                )
        if by_category.get("accord"):
            parts.append(
                (
                    " — Accords de branche",
                    self._format_accords_as_markdown(by_category["accord"], ccn_ref),
                    "accord_branche",
                )
            )
        snapshot_hash = hashlib.sha256(
            "".join(text for _, text, _ in parts).encode("utf-8")
        ).hexdigest()
        return parts, snapshot_hash

    async def _create_common_docs(
        self,
        db: AsyncSession,
        ccn_ref: CcnReference,
        all_articles: list[dict],
        user_id: uuid.UUID,
    ) -> tuple[list[str], str]:
        """Create and enqueue the shared documents of a KALI snapshot."""
        from app.services.storage_service import StorageService

        parts, snapshot_hash = self._common_doc_parts(all_articles, ccn_ref)
        if not parts:
            raise ValueError(f"Aucun article en vigueur pour l'IDCC {ccn_ref.idcc}")
        storage = StorageService()
        doc_ids: list[str] = []
        for suffix, text_content, source_type in parts:
            doc = await self._create_common_ccn_document(
                db,
                ccn_ref,
                text_content,
                user_id=user_id,
                storage=storage,
                name_suffix=suffix,
                file_hash_override=snapshot_hash if suffix == "" else None,
                source_type_override=source_type,
            )
            await enqueue_ingestion(str(doc.id))
            doc_ids.append(str(doc.id))
        logger.info(
            "KALI IDCC %s: %d common document(s) created (%d articles)",
            ccn_ref.idcc,
            len(doc_ids),
            len(all_articles),
        )
        return doc_ids, snapshot_hash

    async def refresh_common_ccn(
        self,
        db: AsyncSession,
        idcc: str,
        user_id: uuid.UUID,
        force: bool = False,
    ) -> KaliSyncResult:
        """Bring the SHARED snapshot of a convention up to date with KALI.

        One fetch per IDCC; every organisation that installed it reads the
        shared documents. Unchanged snapshot (same hash) → nothing rewritten.
        Otherwise blue-green: new documents are created and indexed, the old
        ones are removed once their replacement is ready."""
        sync_result = KaliSyncResult(idcc=idcc)
        ccn_ref = await db.get(CcnReference, idcc)
        if not ccn_ref or not ccn_ref.kali_id:
            sync_result.error = f"IDCC {idcc} introuvable dans le référentiel"
            return sync_result

        all_articles, fetch_errors, source_date = await self._fetch_kali_articles(ccn_ref)
        sync_result.articles_count = len(all_articles)
        if fetch_errors:
            # A partial snapshot must never replace a complete one.
            sync_result.error = "; ".join(fetch_errors)[:500]
            return sync_result
        _, snapshot_hash = self._common_doc_parts(all_articles, ccn_ref)
        sync_result.content_hash = snapshot_hash

        existing = [
            doc
            for doc in await self._find_common_ccn_docs(db, idcc)
            if self._is_generated_kali_document(doc)
        ]
        # A snapshot that failed to index is not current: comparing with it
        # would keep serving the previous version and never retry.
        unchanged = any(
            doc.file_hash == snapshot_hash and doc.indexation_status != "error" for doc in existing
        )
        if not unchanged or force:
            sync_result.update_needed = True
            sync_result.old_document_ids = [str(doc.id) for doc in existing]
            doc_ids, _ = await self._create_common_docs(db, ccn_ref, all_articles, user_id)
            sync_result.new_document_id = doc_ids[0]
            if sync_result.old_document_ids:
                await self._enqueue_old_docs_cleanup(
                    sync_result.old_document_ids, replacement_ids=doc_ids
                )

        now = datetime.now(UTC)
        org_convs = (
            await db.execute(
                select(OrganisationConvention).where(OrganisationConvention.idcc == idcc)
            )
        ).scalars()
        for org_conv in org_convs:
            org_conv.last_synced_at = now
            if sync_result.update_needed:
                org_conv.articles_count = len(all_articles)
                org_conv.source_date = source_date
        await db.commit()
        logger.info(
            "refresh_common_ccn IDCC %s: %s",
            idcc,
            "updated" if sync_result.update_needed else "unchanged",
        )
        return sync_result

    @staticmethod
    def _is_generated_kali_document(doc: Document) -> bool:
        """Distinguish generated KALI snapshots from BOCC branch documents."""
        return doc.source_type in {
            "convention_collective_nationale",
            "accord_branche",
        } and (doc.name.startswith("CCN ") or doc.name.startswith("Accords de branche — "))

    async def bulk_sync_ccn(
        self,
        db: AsyncSession,
        idcc_list: list[str],
        user_id: uuid.UUID,
    ) -> KaliBulkSyncResult:
        """Weekly rotation: refresh the shared snapshot of each IDCC once."""
        bulk_result = KaliBulkSyncResult(total_idcc=len(idcc_list))
        for idcc in idcc_list:
            try:
                sync_result = await self.refresh_common_ccn(db, idcc, user_id)
            except Exception as exc:
                await db.rollback()
                logger.exception("bulk_sync_ccn: failed for IDCC %s", idcc)
                sync_result = KaliSyncResult(idcc=idcc, error=str(exc)[:500])
            bulk_result.details.append(sync_result)
            if sync_result.error:
                bulk_result.errors += 1
            elif sync_result.update_needed:
                bulk_result.updates_needed += 1
            else:
                bulk_result.skipped_identical += 1
        logger.info(
            "bulk_sync_ccn complete: %d IDCC, %d updates, %d identical, %d errors",
            bulk_result.total_idcc,
            bulk_result.updates_needed,
            bulk_result.skipped_identical,
            bulk_result.errors,
        )
        return bulk_result

    # --- ANI (accords nationaux interprofessionnels) ---
    #
    # Les ANI vivent dans le fond KALI, à côté des CCN, mais sans IDCC — le
    # chemin CCN (piloté par IDCC) ne les atteint pas. On les énumère via
    # /search sur le titre, puis on ingère chaque texte (base + avenants) en
    # vigueur comme document COMMUN. Volume faible : ~1-3 nouveaux ANI/an, donc
    # un simple scan mensuel idempotent suffit (backfill au 1er passage).

    _ANI_SEARCH_VALUE = "accord national interprofessionnel"
    _ANI_MONTHS = {
        "janvier": 1,
        "février": 2,
        "fevrier": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "août": 8,
        "aout": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "décembre": 12,
        "decembre": 12,
    }

    async def sync_ani(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        since_year: int = 2010,
    ) -> AniSyncResult:
        """Ingère les ANI (base + avenants) en vigueur depuis `since_year`.

        Idempotent : saute les textes déjà ingérés (dédup sur l'id KALITEXT
        stocké dans ``numero_pourvoi``). Sert de backfill au 1er passage puis
        de scan incrémental mensuel.
        """
        from app.services.storage_service import StorageService

        result = AniSyncResult()
        existing = await self._get_existing_ani_ids(db)
        storage = StorageService()

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            candidates = await self._search_ani(client)
            result.fetched = len(candidates)

            for cand in candidates:
                if not cand["id"]:
                    continue
                if cand["year"] < since_year:
                    continue
                if not cand["etat"].startswith("VIGUEUR"):
                    continue  # abrogé / périmé : on ne nourrit pas le RAG
                if cand["id"] in existing:
                    result.skipped += 1
                    continue

                try:
                    await asyncio.sleep(_API_THROTTLE)
                    text_data = await self._api_post(
                        client, "/consult/kaliText", json_body={"id": cand["id"]}
                    )
                    if text_data is None:
                        result.errors += 1
                        result.error_messages.append(f"{cand['id']} introuvable")
                        continue

                    articles = self._extract_articles_from_text(text_data)
                    if not articles:
                        result.skipped += 1
                        continue

                    text_content = self._format_ani_as_markdown(articles, cand["title"])
                    doc = await self._create_ani_document(
                        db,
                        cand,
                        text_content,
                        user_id=user_id,
                        storage=storage,
                    )
                    await enqueue_ingestion(str(doc.id))
                    existing.add(cand["id"])
                    result.created += 1
                    result.titles_created.append(cand["title"])
                    logger.info("ANI ingéré: %s (%s)", cand["title"][:80], cand["id"])
                except Exception as exc:  # noqa: BLE001
                    result.errors += 1
                    result.error_messages.append(f"{cand['id']}: {exc}")
                    logger.exception("ANI ingest failed for %s", cand["id"])

        logger.info(
            "ANI sync: %d listés, %d créés, %d sautés, %d erreurs",
            result.fetched,
            result.created,
            result.skipped,
            result.errors,
        )
        return result

    async def _search_ani(self, client: httpx.AsyncClient) -> list[dict]:
        """Liste tous les textes ANI de KALI (base + avenants) via /search.

        Retourne des dicts {id, title, etat, year, signature_date}.
        """
        rows: list[dict] = []
        page = 1
        while True:
            data = await self._api_post(client, "/search", json_body=self._ani_search_payload(page))
            if not data:
                break
            results = data.get("results", [])
            if not results:
                break
            for res in results:
                titles = res.get("titles") or [{}]
                t = titles[0]
                title = re.sub(r"</?mark>", "", t.get("title", "")).strip()
                sig_date = self._parse_ani_date(title)
                rows.append(
                    {
                        "id": t.get("id"),
                        "title": title,
                        "etat": res.get("etat") or "",
                        "year": sig_date.year if sig_date else self._parse_ani_year(title),
                        "signature_date": sig_date,
                    }
                )
            total = data.get("totalResultNumber", 0)
            if page * 100 >= total:
                break
            page += 1
            await asyncio.sleep(_API_THROTTLE)
        return rows

    @classmethod
    def _ani_search_payload(cls, page: int) -> dict:
        return {
            "fond": "KALI",
            "recherche": {
                "champs": [
                    {
                        "typeChamp": "TITLE",
                        "criteres": [
                            {
                                "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP",
                                "valeur": cls._ANI_SEARCH_VALUE,
                                "operateur": "ET",
                            }
                        ],
                        "operateur": "ET",
                    }
                ],
                "pageNumber": page,
                "pageSize": 100,
                "operateur": "ET",
                "sort": "PERTINENCE",
                "typePagination": "DEFAUT",
            },
        }

    @classmethod
    def _parse_ani_date(cls, title: str) -> date | None:
        """Extrait la date de signature depuis le titre (« ... du 5 octobre 2023 ... »)."""
        m = re.search(
            r"du\s+(\d{1,2})(?:er)?\s+([A-Za-zàâäéèêëîïôöûüç]+)\s+(\d{4})",
            title,
        )
        if m:
            month = cls._ANI_MONTHS.get(m.group(2).lower())
            if month:
                try:
                    return date(int(m.group(3)), month, int(m.group(1)))
                except ValueError:
                    return None
        return None

    @staticmethod
    def _parse_ani_year(title: str) -> int:
        m = re.search(r"\b(?:19|20)\d{2}\b", title)
        return int(m.group(0)) if m else 0

    @staticmethod
    async def _get_existing_ani_ids(db: AsyncSession) -> set[str]:
        """Ids KALITEXT d'ANI déjà ingérés (stockés dans numero_pourvoi)."""
        result = await db.execute(
            select(Document.numero_pourvoi).where(
                Document.source_type == "accord_national_interprofessionnel",
                Document.organisation_id.is_(None),
                Document.numero_pourvoi.isnot(None),
            )
        )
        return {row[0] for row in result.all()}

    async def _create_ani_document(
        self,
        db: AsyncSession,
        cand: dict,
        text_content: str,
        *,
        user_id: uuid.UUID,
        storage,
    ) -> Document:
        """Crée un document COMMUN (org_id = NULL) pour un ANI."""
        source_type = "accord_national_interprofessionnel"
        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]

        file_id = uuid.uuid4()
        storage_path = f"common/ani/{file_id}_{cand['id']}.txt"
        text_bytes = text_content.encode("utf-8")
        storage.put_file_bytes(storage_path, text_bytes, content_type="text/plain")
        file_hash = hashlib.sha256(text_bytes).hexdigest()

        doc = Document(
            organisation_id=None,  # COMMON document
            name=cand["title"][:250] or f"ANI {cand['id']}",
            source_type=source_type,
            norme_niveau=hierarchy["niveau"],
            norme_poids=hierarchy["poids"],
            storage_path=storage_path,
            indexation_status="pending",
            uploaded_by=user_id,
            file_size=len(text_bytes),
            file_format="txt",
            file_hash=file_hash,
            numero_pourvoi=cand["id"],  # clé de dédup = id KALITEXT
            date_decision=cand["signature_date"],
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    @staticmethod
    def _format_ani_as_markdown(articles: list[dict], title: str) -> str:
        """Format un ANI (articles extraits) en Markdown pour l'ingestion."""
        lines = [f"# {title}", ""]
        current_section = ""
        unnamed_counter = 0
        for art in articles:
            section = art.get("section", "")
            if section and section != current_section:
                current_section = section
                lines.append(f"\n## {section}\n")

            num = art.get("num", "")
            if num:
                lines.append(f"### Article {num}\n")
            else:
                unnamed_counter += 1
                lines.append(f"### Article (sans numéro {unnamed_counter})\n")
            lines.append(art["content"])
            lines.append("")

        return "\n".join(lines)

    # --- Private methods ---

    async def _fetch_kali_articles(
        self, ccn_ref: CcnReference
    ) -> tuple[list[dict], list[str], str | None]:
        """Fetch all articles for a CCN from the KALI API.

        Returns (articles, error_messages, most_recent_source_date).
        Articles include a 'category' field: 'base', 'annexe', or 'salaire'.
        """
        errors: list[str] = []
        most_recent_date: str | None = None

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            container = await self._api_post(
                client, "/consult/kaliCont", json_body={"id": ccn_ref.kali_id}
            )
            if container is None:
                raise ValueError(f"Container KALI introuvable pour {ccn_ref.kali_id}")

            # Categorize text IDs by section type
            sections = container.get("sections", [])
            categorized_ids: list[tuple[str, str, str, str]] = []
            # (text_id, category, title, status)

            for section in sections:
                title = (section.get("title") or section.get("titre") or "").lower()
                etat = section.get("etat") or ""

                if "salaire" in title:
                    section_category = "salaire"
                elif "attaché" in title or "attach" in title:
                    section_category = "attaché"
                else:
                    section_category = "base"

                # Collect KALITEXT IDs from this section
                section_ids: list[tuple[str, str, str]] = []  # (id, title, status)

                def _walk(items: list[dict]) -> None:
                    for item in items:
                        tid = item.get("id") or ""
                        ie = item.get("etat") or ""
                        child_title = item.get("title") or item.get("titre") or ""
                        if tid.startswith("KALITEXT") and ie.startswith("VIGUEUR"):
                            section_ids.append((tid, child_title, ie))
                        children = item.get("sections", [])
                        if children:
                            _walk(children)

                sid = section.get("id") or ""
                section_title_orig = section.get("title") or section.get("titre") or ""
                if sid.startswith("KALITEXT") and etat.startswith("VIGUEUR"):
                    section_ids.append((sid, section_title_orig, etat))
                _walk(section.get("sections", []))

                for tid, child_title, text_status in section_ids:
                    if section_category == "attaché":
                        # Within "Textes Attachés", distinguish accords from annexes
                        child_lower = child_title.lower()
                        if "accord" in child_lower or "protocole d'accord" in child_lower:
                            category = "accord"
                        elif "avenant" in child_lower:
                            category = "avenant"
                        else:
                            category = "annexe"
                    else:
                        category = section_category
                    categorized_ids.append((tid, category, child_title, text_status))

            if not categorized_ids:
                raise ValueError(
                    "Cette convention collective n'est pas disponible dans la base Légifrance. "
                    "Elle a peut-être été remplacée ou fusionnée avec une autre convention."
                )

            logger.info(
                "KALI fetch IDCC %s: %d text(s) to fetch "
                "(base=%d, accords=%d, avenants=%d, annexes=%d, salaires=%d)",
                ccn_ref.idcc,
                len(categorized_ids),
                sum(1 for _, c, _, _ in categorized_ids if c == "base"),
                sum(1 for _, c, _, _ in categorized_ids if c == "accord"),
                sum(1 for _, c, _, _ in categorized_ids if c == "avenant"),
                sum(1 for _, c, _, _ in categorized_ids if c == "annexe"),
                sum(1 for _, c, _, _ in categorized_ids if c == "salaire"),
            )

            all_articles: list[dict] = []
            for text_id, category, child_title, container_status in categorized_ids:
                await asyncio.sleep(_API_THROTTLE)
                text_data = await self._api_post(
                    client, "/consult/kaliText", json_body={"id": text_id}
                )
                if text_data is None:
                    errors.append(f"Texte {text_id} introuvable")
                    continue

                text_etat = text_data.get("etat") or ""
                if text_etat and not text_etat.startswith("VIGUEUR"):
                    continue

                # Track most recent source date
                modif_date = text_data.get("modifDate") or ""
                if modif_date and (most_recent_date is None or modif_date > most_recent_date):
                    most_recent_date = modif_date

                articles = self._extract_articles_from_text(text_data)
                instrument_title = (
                    text_data.get("title") or text_data.get("titre") or child_title or text_id
                )
                for art in articles:
                    art["category"] = category
                    # Keep the KALITEXT parent on every article.  Without it,
                    # salary grids from several successive agreements become
                    # indistinguishable once combined into one CCN document.
                    art["instrument_id"] = text_id
                    art["instrument_title"] = instrument_title
                    art["instrument_status"] = text_etat or container_status
                all_articles.extend(articles)

        return all_articles, errors, most_recent_date

    @staticmethod
    async def _find_common_ccn_docs(db: AsyncSession, idcc: str) -> list[Document]:
        """Find common (shared) CCN documents for an IDCC (CCN + accords de branche)."""
        from sqlalchemy import or_

        result = await db.execute(
            select(Document)
            .where(
                Document.organisation_id.is_(None),
                or_(
                    Document.source_type == "convention_collective_nationale",
                    Document.source_type == "accord_branche",
                ),
                Document.name.ilike(f"%IDCC {idcc}%"),
            )
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def _create_common_ccn_document(
        self,
        db: AsyncSession,
        ccn_ref: CcnReference,
        text_content: str,
        user_id: uuid.UUID,
        storage,
        name_suffix: str = "",
        file_hash_override: str | None = None,
        source_type_override: str | None = None,
    ) -> Document:
        """Create a common (shared) CCN document — org_id = NULL."""
        source_type = source_type_override or "convention_collective_nationale"
        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]

        titre = ccn_ref.titre_court or ccn_ref.titre
        if source_type == "accord_branche":
            name = f"Accords de branche — {titre} (IDCC {ccn_ref.idcc})"
        else:
            name = f"CCN {titre} (IDCC {ccn_ref.idcc}){name_suffix}"

        file_id = uuid.uuid4()
        storage_path = f"common/ccn/{ccn_ref.idcc}/{file_id}.txt"
        text_bytes = text_content.encode("utf-8")
        storage.put_file_bytes(storage_path, text_bytes, content_type="text/plain")

        file_hash = file_hash_override or hashlib.sha256(text_bytes).hexdigest()

        doc = Document(
            organisation_id=None,  # COMMON document
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
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    @staticmethod
    async def _cleanup_old_ccn_docs(
        db: AsyncSession,
        old_doc_ids: list[str],
        replacement_ids: list[str] | None = None,
    ) -> int:
        """Delete old CCN documents and their Qdrant vectors (blue-green cleanup).

        ``replacement_ids``: the complete new snapshot. When given, the old
        documents are removed once EVERY replacement is fully indexed, whatever
        their names: a part that no longer exists in KALI (no more salary grid,
        renamed convention) must not keep its old, superseded text forever.
        Without it, each old document waits for an indexed one of the same name.
        Returns the number of documents cleaned up.
        """
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
        from app.services.storage_service import StorageService

        storage = StorageService()
        cleaned = 0
        qdrant = get_qdrant_client()

        def fully_indexed(replacement: Document) -> bool:
            count = qdrant.count(
                COLLECTION_NAME,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=str(replacement.id)),
                        ),
                        FieldCondition(key="organisation_id", match=MatchValue(value="common")),
                        FieldCondition(key="private", match=MatchValue(value=False)),
                    ]
                ),
                exact=True,
            ).count
            return count == replacement.chunk_count

        snapshot_ready: bool | None = None
        if replacement_ids:
            replacements = [await db.get(Document, uuid.UUID(value)) for value in replacement_ids]
            snapshot_ready = all(
                doc is not None
                and doc.retired_at is None
                and doc.organisation_id is None
                and doc.indexation_status == "indexed"
                and (doc.chunk_count or 0) > 0
                and fully_indexed(doc)
                for doc in replacements
            )

        for doc_id_str in old_doc_ids:
            doc_id = uuid.UUID(doc_id_str)
            doc = await db.get(Document, doc_id)
            if doc is None:
                continue

            # A scheduled delay does not prove that replacement ingestion
            # succeeded. Preserve the old public source until its replacement
            # is indexed and its complete vector set is available.
            if (
                doc.organisation_id is not None
                or doc.private_dossier_id is not None
                or doc.private_conversation_id is not None
            ):
                logger.warning("Refusing public-source cleanup for private doc %s", doc_id)
                continue
            if snapshot_ready is not None:
                if not snapshot_ready:
                    logger.warning("Keeping old doc %s: new snapshot is not ready", doc_id)
                    continue
                replacements = []
            else:
                replacements = (
                    (
                        await db.execute(
                            select(Document).where(
                                Document.organisation_id.is_(None),
                                Document.private_dossier_id.is_(None),
                                Document.private_conversation_id.is_(None),
                                Document.retired_at.is_(None),
                                Document.id.not_in([uuid.UUID(value) for value in old_doc_ids]),
                                Document.name == doc.name,
                                Document.source_type == doc.source_type,
                                Document.indexation_status == "indexed",
                                Document.chunk_count > 0,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if not any(fully_indexed(replacement) for replacement in replacements):
                    logger.warning("Keeping old doc %s: replacement is not ready", doc_id)
                    continue

            # Delete Qdrant vectors
            try:
                qdrant.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=FilterSelector(
                        filter=Filter(
                            must=[
                                FieldCondition(
                                    key="document_id",
                                    match=MatchValue(value=str(doc_id)),
                                )
                            ]
                        )
                    ),
                )
            except Exception:
                # Keep the row: deleting it would leave orphan vectors that
                # stay searchable with no document behind them.
                logger.warning("Failed to delete Qdrant chunks for old doc %s", doc_id)
                continue

            # Delete storage file
            try:
                storage.delete_file(doc.storage_path)
            except Exception:
                logger.warning("Failed to delete storage for old doc %s", doc_id)

            # Delete DB record
            await db.delete(doc)
            cleaned += 1

        if cleaned:
            await db.commit()
            logger.info("Blue-green cleanup: deleted %d old CCN document(s)", cleaned)

        return cleaned

    @staticmethod
    async def _enqueue_old_docs_cleanup(
        old_doc_ids: list[str], replacement_ids: list[str] | None = None
    ) -> None:
        """Enqueue a job to clean up old CCN documents after new one is indexed."""
        from app.rag.tasks import get_arq_pool

        pool = await get_arq_pool()
        job_id = f"ccn_cleanup_{'_'.join(old_doc_ids[:3])}"
        await pool.enqueue_job(
            "run_ccn_blue_green_cleanup",
            old_doc_ids,
            replacement_ids=replacement_ids,
            _job_id=job_id,
            _defer_by=120,  # Wait 2 minutes for ingestion to complete
        )
        logger.info(
            "Blue-green cleanup enqueued for %d old doc(s): %s",
            len(old_doc_ids),
            old_doc_ids,
        )

    def _extract_articles_from_text(self, text_data: dict) -> list[dict]:
        """Extract all in-force articles from a KALITEXT response.

        Real API article fields: id, cid, num, etat, content (HTML), path, pathTitle,
        dateDebut, dateFin, nota, surtitre, etc.
        etat can be None (treat as in-force since parent text is in-force).
        """
        articles: list[dict] = []
        excluded_count = 0

        def _is_in_force(etat: str | None) -> bool:
            if etat is None:
                return True  # No status = inherited from parent
            return etat.startswith("VIGUEUR")

        def _extract_article(art: dict, section_path: str) -> None:
            nonlocal excluded_count
            num = art.get("num") or ""
            etat = art.get("etat")
            if not _is_in_force(etat):
                excluded_count += 1
                logger.debug(
                    "[KALI] Excluded article %s (etat=%s, section=%s)",
                    num,
                    etat,
                    section_path,
                )
                return
            content = art.get("content", art.get("texte", art.get("texteHtml", "")))
            if not content:
                excluded_count += 1
                logger.warning(
                    "[KALI] Article %s has no content (etat=%s, section=%s)",
                    num,
                    etat,
                    section_path,
                )
                return
            articles.append(
                {
                    "num": num,
                    "article_id": art.get("id") or "",
                    "article_title": art.get("surtitre") or "",
                    "content": self._clean_html(content),
                    "section": section_path,
                    "etat": etat or "",
                    "date_debut": self._normalise_kali_date(art.get("dateDebut")),
                    "date_fin": self._normalise_kali_date(art.get("dateFin")),
                }
            )

        def _walk_sections(sections: list[dict], path: str = "") -> None:
            for section in sections:
                section_title = section.get("title", section.get("titre", ""))
                current_path = f"{path} > {section_title}" if path else section_title

                for art in section.get("articles", []):
                    _extract_article(art, current_path)

                sub_sections = section.get("sections", section.get("children", []))
                if sub_sections:
                    _walk_sections(sub_sections, current_path)

        # Top-level articles
        for art in text_data.get("articles", []):
            _extract_article(art, "")

        # Sections
        sections = text_data.get("sections", [])
        if sections:
            _walk_sections(sections)

        logger.info(
            "[KALI] Extracted %d in-force articles, excluded %d",
            len(articles),
            excluded_count,
        )
        return articles

    @staticmethod
    def _normalise_kali_date(value) -> str:
        """Return a KALI date as ISO-8601, ignoring open-ended year 2999."""
        if value in (None, ""):
            return ""
        if isinstance(value, (int, float)):
            try:
                parsed = datetime.fromtimestamp(value / 1000, tz=UTC).date()
            except (OverflowError, OSError, ValueError):
                return ""
            return "" if parsed.year >= 2999 else parsed.isoformat()
        raw = str(value).strip()
        if not raw:
            return ""
        if raw[:4].isdigit() and int(raw[:4]) >= 2999:
            return ""
        return raw[:10]

    @staticmethod
    def _clean_html(html: str) -> str:
        """Convert HTML to markdown, preserving tables/lists/headings.

        Critical for CCN content : barèmes, grilles de salaire et minima
        conventionnels sont presque toujours des `<table>` côté Légifrance.
        Les aplatir en texte les rend illisibles pour l'utilisateur final
        et empêche le RAG de les retrouver correctement.
        """
        from app.services.html_to_markdown import html_to_markdown

        return html_to_markdown(html)

    @staticmethod
    def _format_articles_as_markdown(articles: list[dict], ccn_ref: CcnReference) -> str:
        """Format articles as a Markdown document for ingestion."""
        return KaliService._format_instrumented_articles(
            articles,
            f"# Convention collective — {ccn_ref.titre} (IDCC {ccn_ref.idcc})",
        )

    @staticmethod
    def _format_instrumented_articles(
        articles: list[dict],
        document_heading: str,
    ) -> str:
        """Format articles while retaining their parent KALITEXT identity."""
        from app.rag.article_chunker import ARTICLE_METADATA_PREFIX

        lines = [document_heading, ""]
        current_source: tuple[str, str, str, str, str, str] | None = None
        unnamed_counter = 0
        for art in articles:
            section = art.get("section", "")
            source = (
                art.get("instrument_id", ""),
                art.get("instrument_title", ""),
                art.get("instrument_status", ""),
                art.get("date_debut", ""),
                art.get("date_fin", ""),
                section,
            )
            if source != current_source:
                current_source = source
                instrument_id, title, status, date_debut, date_fin, section = source
                if instrument_id:
                    lines.append(f"\n## Source juridique : {title or instrument_id}\n")
                    lines.append(f"Référence : {instrument_id}")
                    if date_debut:
                        lines.append(f"Entrée en vigueur : {date_debut}")
                    if date_fin:
                        lines.append(f"Fin d'effet : {date_fin}")
                    if status:
                        lines.append(f"Statut : {status}")
                    if section:
                        lines.append(f"Section : {section}")
                    lines.append("")
                elif section:
                    lines.append(f"\n## {section}\n")

            num = art.get("num", "")
            if num:
                lines.append(f"### Article {num}\n")
            else:
                # Ensure every article has a heading so the chunker can detect it
                unnamed_counter += 1
                lines.append(f"### Article (sans numéro {unnamed_counter})\n")
            metadata = {
                "article_id": art.get("article_id", ""),
                "article_title": art.get("article_title", ""),
                "article_status": art.get("etat", ""),
                "article_effective_from": art.get("date_debut", ""),
                "article_effective_to": art.get("date_fin", ""),
            }
            if any(metadata.values()):
                lines.append(ARTICLE_METADATA_PREFIX + json.dumps(metadata, ensure_ascii=False))
                lines.append("")
            lines.append(art["content"])
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_accords_as_markdown(
        articles: list[dict],
        ccn_ref: CcnReference,
    ) -> str:
        """Format accord de branche articles as Markdown for ingestion."""
        titre = ccn_ref.titre_court or ccn_ref.titre
        return KaliService._format_instrumented_articles(
            articles,
            f"# Accords de branche — {titre} (IDCC {ccn_ref.idcc})",
        )

    @staticmethod
    def _make_titre_court(titre: str) -> str | None:
        """Generate a short title from the full convention title."""
        if not titre:
            return None
        # Remove common prefixes
        short = re.sub(
            r"^Convention collective nationale d(es?|u|e la|e l') ",
            "",
            titre,
            flags=re.IGNORECASE,
        )
        short = re.sub(
            r"^Convention collective ",
            "",
            short,
            flags=re.IGNORECASE,
        )
        # Truncate at 255 chars
        if len(short) > 255:
            short = short[:252] + "..."
        return short if short != titre else None

    async def _api_post(
        self,
        client: httpx.AsyncClient,
        path: str,
        json_body: dict,
    ) -> dict | None:
        """Make a POST request to the Légifrance API with OAuth2 Bearer auth."""
        url = f"{self.base_url}{path}"

        for attempt in range(_MAX_RETRIES):
            try:
                token = await self._get_access_token()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                response = await client.post(url, headers=headers, json=json_body)

                if response.status_code == 401 and attempt < _MAX_RETRIES - 1:
                    KaliService._cached_token = None
                    KaliService._token_expires_at = 0.0
                    continue

                if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_DELAY * (2**attempt)
                    logger.warning("KALI rate limit (429), retry in %.1fs", delay)
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
                logger.error("KALI API timeout for %s", path)
                return None

        return None
