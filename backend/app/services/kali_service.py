"""Service d'intégration avec l'API KALI (Légifrance / PISTE).

Gère l'authentification OAuth2, la récupération du référentiel IDCC,
le fetch des textes de conventions collectives, et l'ingestion dans le pipeline RAG.
"""

import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
    total_orgs_synced: int = 0
    updates_needed: int = 0
    skipped_identical: int = 0
    errors: int = 0
    details: list[KaliSyncResult] = field(default_factory=list)


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
            KaliService._token_expires_at = (
                time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN
            )
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
                db.add(CcnReference(
                    idcc=idcc,
                    titre=titre,
                    titre_court=titre_court or None,
                    kali_id=kali_id,
                    etat="VIGUEUR_ETEN",
                    last_api_check=datetime.now(UTC),
                ))
            count += 1

        await db.commit()
        logger.info("CCN reference seeded: %d conventions from static data", count)
        return count

    async def refresh_ccn_reference(self, db: AsyncSession) -> int:
        """Refresh the local CCN reference table from the KALI API.

        Falls back to static seed data if the API is unavailable.
        Returns the number of CCN updated/inserted.
        """
        if not self._client_id or not self._client_secret:
            logger.warning("No Légifrance credentials, falling back to static seed")
            return await self.seed_ccn_reference(db)

        all_conventions: list[dict] = []
        page = 0
        page_size = 100

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                while True:
                    data = await self._api_post(client, "/list/conventions", json_body={
                        "pageNumber": page,
                        "pageSize": page_size,
                        "legalStatus": ["VIGUEUR_ETEN", "VIGUEUR_NON_ETEN", "VIGUEUR"],
                    })
                    if data is None:
                        break

                    results = data.get("results", [])
                    all_conventions.extend(results)

                    total = data.get("totalResultNumber", 0)
                    if (page + 1) * page_size >= total or not results:
                        break
                    page += 1
                    await asyncio.sleep(_API_THROTTLE)
        except Exception as exc:
            logger.warning("KALI /list/conventions failed (%s), falling back to seed", exc)

        # Fallback to seed if API returned nothing
        if not all_conventions:
            logger.info("API returned no results, using static seed data")
            return await self.seed_ccn_reference(db)

        count = 0
        for conv in all_conventions:
            idcc = self._extract_idcc(conv)
            if not idcc:
                continue

            titre = conv.get("title", conv.get("titre", ""))
            kali_id = conv.get("id", conv.get("cid", ""))
            etat = conv.get("etat", "")

            existing = await db.get(CcnReference, idcc)
            if existing:
                existing.titre = titre
                existing.kali_id = kali_id
                existing.etat = etat
                existing.last_api_check = datetime.now(UTC)
            else:
                db.add(CcnReference(
                    idcc=idcc,
                    titre=titre,
                    titre_court=self._make_titre_court(titre),
                    kali_id=kali_id,
                    etat=etat,
                    last_api_check=datetime.now(UTC),
                ))
            count += 1

        await db.commit()
        logger.info("CCN reference refreshed from API: %d conventions", count)
        return count

    async def install_convention(
        self,
        db: AsyncSession,
        org_conv: OrganisationConvention,
        user_id: uuid.UUID,
    ) -> KaliInstallResult:
        """Fetch a CCN from KALI and ingest as COMMON documents (shared).

        If common docs already exist for this IDCC, just link (no re-fetch).
        If not, fetch from KALI and create common docs.
        Blue-green for updates.
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

            if existing_common:
                # Common docs exist — just link, no need to re-fetch
                logger.info(
                    "KALI IDCC %s: common docs already exist (%d docs), linking only",
                    org_conv.idcc, len(existing_common),
                )
                org_conv.status = "ready"
                org_conv.articles_count = existing_common[0].chunk_count
                org_conv.installed_at = datetime.now(UTC)
                org_conv.last_synced_at = datetime.now(UTC)
                org_conv.error_message = None
                await db.commit()
                return result

            # No common docs — fetch from KALI and create
            all_articles, fetch_errors, source_date = await self._fetch_kali_articles(ccn_ref)
            result.errors += len(fetch_errors)
            result.error_messages.extend(fetch_errors)
            result.articles_count = len(all_articles)

            base_articles = [a for a in all_articles if a.get("category") == "base"]
            annexe_articles = [a for a in all_articles if a.get("category") in ("annexe", "avenant")]
            salaire_articles = [a for a in all_articles if a.get("category") == "salaire"]
            accord_articles = [a for a in all_articles if a.get("category") == "accord"]

            logger.info(
                "KALI IDCC %s: %d articles "
                "(base=%d, accords=%d, annexes=%d, salaires=%d)",
                org_conv.idcc, len(all_articles),
                len(base_articles), len(accord_articles),
                len(annexe_articles), len(salaire_articles),
            )

            # CCN parts (base, annexes, salaires)
            ccn_parts: list[tuple[str, str]] = []
            if base_articles:
                ccn_parts.append(("", self._format_articles_as_markdown(base_articles, ccn_ref)))
            if annexe_articles:
                ccn_parts.append((" — Avenants et annexes", self._format_articles_as_markdown(annexe_articles, ccn_ref)))
            if salaire_articles:
                ccn_parts.append((" — Grilles de salaires", self._format_articles_as_markdown(salaire_articles, ccn_ref)))

            combined = "".join(text for _, text in ccn_parts)
            new_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()

            org_conv.status = "indexing"
            await db.commit()

            from app.services.storage_service import StorageService
            storage = StorageService()

            for suffix, text_content in ccn_parts:
                doc = await self._create_common_ccn_document(
                    db, ccn_ref, text_content,
                    user_id=user_id,
                    storage=storage,
                    name_suffix=suffix,
                    file_hash_override=new_hash if suffix == "" else None,
                )
                await enqueue_ingestion(str(doc.id))

            # Accords de branche — stored as separate documents
            if accord_articles:
                accord_text = self._format_accords_as_markdown(
                    accord_articles, ccn_ref,
                )
                doc = await self._create_common_ccn_document(
                    db, ccn_ref, accord_text,
                    user_id=user_id,
                    storage=storage,
                    name_suffix=" — Accords de branche",
                    source_type_override="accord_branche",
                )
                await enqueue_ingestion(str(doc.id))
                logger.info(
                    "KALI IDCC %s: created accord_branche document "
                    "(%d articles)",
                    org_conv.idcc, len(accord_articles),
                )

            result.documents_created = len(ccn_parts) + (1 if accord_articles else 0)

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
                    logger.info("KALI install IDCC %s: also enqueued %d BOCC docs", org_conv.idcc, bocc_count)
            except Exception:
                logger.warning("KALI install IDCC %s: failed to ingest BOCC docs", org_conv.idcc, exc_info=True)

        except Exception as exc:
            org_conv.status = "error"
            org_conv.error_message = str(exc)[:500]
            await db.commit()
            result.errors += 1
            result.error_messages.append(str(exc))
            logger.exception("KALI install failed for IDCC %s", org_conv.idcc)

        return result

    async def sync_convention_content(
        self,
        db: AsyncSession,
        org_conv: OrganisationConvention,
        user_id: uuid.UUID,
    ) -> KaliSyncResult:
        """Sync a single OrganisationConvention: fetch KALI, compare hash, blue-green if needed.

        Returns a KaliSyncResult indicating whether an update was needed.
        """
        sync_result = KaliSyncResult(idcc=org_conv.idcc)

        try:
            ccn_ref = await db.get(CcnReference, org_conv.idcc)
            if not ccn_ref or not ccn_ref.kali_id:
                sync_result.error = f"IDCC {org_conv.idcc} introuvable dans le référentiel"
                return sync_result

            # Fetch from KALI
            all_articles, fetch_errors, source_date = await self._fetch_kali_articles(ccn_ref)
            if fetch_errors:
                sync_result.error = "; ".join(fetch_errors)

            text_content = self._format_articles_as_markdown(all_articles, ccn_ref)
            text_bytes = text_content.encode("utf-8")
            new_hash = hashlib.sha256(text_bytes).hexdigest()
            sync_result.content_hash = new_hash
            sync_result.articles_count = len(all_articles)

            # Find existing docs
            existing_docs = await self._find_existing_ccn_docs(
                db, org_conv.organisation_id, org_conv.idcc
            )

            if existing_docs and existing_docs[0].file_hash == new_hash:
                # Identical — just update timestamp
                sync_result.update_needed = False
                org_conv.last_synced_at = datetime.now(UTC)
                await db.commit()
                logger.info(
                    "sync_convention_content IDCC %s org %s: unchanged",
                    org_conv.idcc, org_conv.organisation_id,
                )
                return sync_result

            # Update needed — blue-green
            sync_result.update_needed = True
            sync_result.old_document_ids = [str(d.id) for d in existing_docs]

            org_conv.status = "indexing"
            org_conv.error_message = None
            await db.commit()

            from app.services.storage_service import StorageService
            storage = StorageService()

            doc = await self._create_document(
                db, org_conv, ccn_ref, text_content,
                user_id=user_id,
                storage=storage,
            )
            sync_result.new_document_id = str(doc.id)

            await enqueue_ingestion(str(doc.id))

            if sync_result.old_document_ids:
                await self._enqueue_old_docs_cleanup(sync_result.old_document_ids)

            org_conv.articles_count = len(all_articles)
            org_conv.source_date = source_date
            org_conv.last_synced_at = datetime.now(UTC)
            if not existing_docs:
                org_conv.installed_at = datetime.now(UTC)
                org_conv.status = "ready"
            await db.commit()

            logger.info(
                "sync_convention_content IDCC %s org %s: update needed, new doc %s",
                org_conv.idcc, org_conv.organisation_id, doc.id,
            )

        except Exception as exc:
            sync_result.error = str(exc)[:500]
            org_conv.status = "error"
            org_conv.error_message = str(exc)[:500]
            await db.commit()
            logger.exception(
                "sync_convention_content failed for IDCC %s org %s",
                org_conv.idcc, org_conv.organisation_id,
            )

        return sync_result

    async def bulk_sync_ccn(
        self,
        db: AsyncSession,
        idcc_list: list[str],
        user_id: uuid.UUID,
    ) -> KaliBulkSyncResult:
        """Bulk sync multiple CCN across all orgs that use them.

        Fetches each IDCC from KALI once, then applies to all orgs.
        """
        bulk_result = KaliBulkSyncResult(total_idcc=len(idcc_list))

        for idcc in idcc_list:
            try:
                ccn_ref = await db.get(CcnReference, idcc)
                if not ccn_ref or not ccn_ref.kali_id:
                    logger.warning("bulk_sync_ccn: IDCC %s not found in reference", idcc)
                    bulk_result.errors += 1
                    continue

                # Fetch KALI content ONCE for this IDCC
                all_articles, fetch_errors, source_date = await self._fetch_kali_articles(ccn_ref)
                if fetch_errors:
                    logger.warning(
                        "bulk_sync_ccn: fetch errors for IDCC %s: %s",
                        idcc, "; ".join(fetch_errors),
                    )

                text_content = self._format_articles_as_markdown(all_articles, ccn_ref)
                text_bytes = text_content.encode("utf-8")
                new_hash = hashlib.sha256(text_bytes).hexdigest()

                # Find all orgs that have this IDCC installed
                org_convs_result = await db.execute(
                    select(OrganisationConvention)
                    .options(joinedload(OrganisationConvention.ccn))
                    .where(OrganisationConvention.idcc == idcc)
                )
                org_convs = list(org_convs_result.scalars().all())

                if not org_convs:
                    logger.info("bulk_sync_ccn: no orgs have IDCC %s installed", idcc)
                    continue

                from app.services.storage_service import StorageService
                storage = StorageService()

                for org_conv in org_convs:
                    bulk_result.total_orgs_synced += 1
                    sync_result = KaliSyncResult(
                        idcc=idcc,
                        content_hash=new_hash,
                        articles_count=len(all_articles),
                    )

                    try:
                        existing_docs = await self._find_existing_ccn_docs(
                            db, org_conv.organisation_id, idcc
                        )

                        if existing_docs and existing_docs[0].file_hash == new_hash:
                            # Identical
                            sync_result.update_needed = False
                            org_conv.last_synced_at = datetime.now(UTC)
                            await db.commit()
                            bulk_result.skipped_identical += 1
                            bulk_result.details.append(sync_result)
                            continue

                        # Update needed — blue-green
                        sync_result.update_needed = True
                        sync_result.old_document_ids = [str(d.id) for d in existing_docs]
                        bulk_result.updates_needed += 1

                        org_conv.status = "indexing"
                        org_conv.error_message = None
                        await db.commit()

                        doc = await self._create_document(
                            db, org_conv, ccn_ref, text_content,
                            user_id=user_id,
                            storage=storage,
                        )
                        sync_result.new_document_id = str(doc.id)

                        await enqueue_ingestion(str(doc.id))

                        if sync_result.old_document_ids:
                            await self._enqueue_old_docs_cleanup(sync_result.old_document_ids)

                        org_conv.articles_count = len(all_articles)
                        org_conv.source_date = source_date
                        org_conv.last_synced_at = datetime.now(UTC)
                        if not existing_docs:
                            org_conv.installed_at = datetime.now(UTC)
                            org_conv.status = "ready"
                        await db.commit()

                    except Exception as exc:
                        sync_result.error = str(exc)[:500]
                        org_conv.status = "error"
                        org_conv.error_message = str(exc)[:500]
                        await db.commit()
                        bulk_result.errors += 1
                        logger.exception(
                            "bulk_sync_ccn: failed for IDCC %s org %s",
                            idcc, org_conv.organisation_id,
                        )

                    bulk_result.details.append(sync_result)

            except Exception as exc:
                bulk_result.errors += 1
                logger.exception("bulk_sync_ccn: failed to process IDCC %s: %s", idcc, exc)

        logger.info(
            "bulk_sync_ccn complete: %d IDCC, %d orgs, %d updates, %d identical, %d errors",
            bulk_result.total_idcc,
            bulk_result.total_orgs_synced,
            bulk_result.updates_needed,
            bulk_result.skipped_identical,
            bulk_result.errors,
        )
        return bulk_result

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
            categorized_ids: list[tuple[str, str]] = []  # (text_id, category)

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
                section_ids: list[tuple[str, str]] = []  # (id, child_title)

                def _walk(items: list[dict]) -> None:
                    for item in items:
                        tid = item.get("id") or ""
                        ie = item.get("etat") or ""
                        child_title = item.get("title") or item.get("titre") or ""
                        if tid.startswith("KALITEXT") and ie.startswith("VIGUEUR"):
                            section_ids.append((tid, child_title))
                        children = item.get("sections", [])
                        if children:
                            _walk(children)

                sid = section.get("id") or ""
                section_title_orig = section.get("title") or section.get("titre") or ""
                if sid.startswith("KALITEXT") and etat.startswith("VIGUEUR"):
                    section_ids.append((sid, section_title_orig))
                _walk(section.get("sections", []))

                for tid, child_title in section_ids:
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
                    categorized_ids.append((tid, category))

            if not categorized_ids:
                raise ValueError("Aucun texte trouvé dans le container KALI")

            logger.info(
                "KALI fetch IDCC %s: %d text(s) to fetch "
                "(base=%d, accords=%d, avenants=%d, annexes=%d, salaires=%d)",
                ccn_ref.idcc,
                len(categorized_ids),
                sum(1 for _, c in categorized_ids if c == "base"),
                sum(1 for _, c in categorized_ids if c == "accord"),
                sum(1 for _, c in categorized_ids if c == "avenant"),
                sum(1 for _, c in categorized_ids if c == "annexe"),
                sum(1 for _, c in categorized_ids if c == "salaire"),
            )

            all_articles: list[dict] = []
            for text_id, category in categorized_ids:
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
                for art in articles:
                    art["category"] = category
                all_articles.extend(articles)

        return all_articles, errors, most_recent_date

    @staticmethod
    async def _find_existing_ccn_docs(
        db: AsyncSession, organisation_id: uuid.UUID, idcc: str
    ) -> list[Document]:
        """Find existing CCN documents for an org+idcc pair (legacy, per-org)."""
        result = await db.execute(
            select(Document).where(
                Document.organisation_id == organisation_id,
                Document.source_type == "convention_collective_nationale",
                Document.name.ilike(f"%IDCC {idcc}%"),
            ).order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def _find_common_ccn_docs(
        db: AsyncSession, idcc: str
    ) -> list[Document]:
        """Find common (shared) CCN documents for an IDCC (CCN + accords de branche)."""
        from sqlalchemy import or_

        result = await db.execute(
            select(Document).where(
                Document.organisation_id.is_(None),
                or_(
                    Document.source_type == "convention_collective_nationale",
                    Document.source_type == "accord_branche",
                ),
                Document.name.ilike(f"%IDCC {idcc}%"),
            ).order_by(Document.created_at.desc())
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
        db: AsyncSession, old_doc_ids: list[str]
    ) -> int:
        """Delete old CCN documents and their Qdrant vectors (blue-green cleanup).

        Call this after the new document has been successfully indexed.
        Returns the number of documents cleaned up.
        """
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
        from app.services.storage_service import StorageService

        storage = StorageService()
        cleaned = 0

        for doc_id_str in old_doc_ids:
            doc_id = uuid.UUID(doc_id_str)
            doc = await db.get(Document, doc_id)
            if doc is None:
                continue

            # Delete Qdrant vectors
            try:
                qdrant = get_qdrant_client()
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
                logger.warning("Failed to delete Qdrant chunks for old doc %s", doc_id)

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
    async def _enqueue_old_docs_cleanup(old_doc_ids: list[str]) -> None:
        """Enqueue a job to clean up old CCN documents after new one is indexed."""
        from app.rag.tasks import get_arq_pool

        pool = await get_arq_pool()
        job_id = f"ccn_cleanup_{'_'.join(old_doc_ids[:3])}"
        await pool.enqueue_job(
            "run_ccn_blue_green_cleanup",
            old_doc_ids,
            _job_id=job_id,
            _defer_by=120,  # Wait 2 minutes for ingestion to complete
        )
        logger.info(
            "Blue-green cleanup enqueued for %d old doc(s): %s",
            len(old_doc_ids), old_doc_ids,
        )

    def _extract_text_ids(self, container: dict) -> list[str]:
        """Extract in-force KALITEXT IDs from a container response.

        The real API structure has a flat `sections` list where each item
        can be a KALITEXT reference or a grouping section (like "Textes Attachés")
        whose own `sections` contain KALITEXT references.
        """
        text_ids: list[str] = []

        def _walk(items: list[dict]) -> None:
            for item in items:
                tid = item.get("id") or ""
                etat = item.get("etat", "")
                if tid.startswith("KALITEXT") and etat.startswith("VIGUEUR"):
                    text_ids.append(tid)
                # Recurse into nested sections (e.g. "Textes Attachés" grouping)
                children = item.get("sections", [])
                if children:
                    _walk(children)

        # Primary structure: container.sections
        sections = container.get("sections", [])
        if sections:
            _walk(sections)

        # Also check texteBaseId (can be a string or a list)
        base_id = container.get("texteBaseId", "")
        if isinstance(base_id, list):
            for bid in base_id:
                if isinstance(bid, str) and bid.startswith("KALITEXT") and bid not in text_ids:
                    text_ids.insert(0, bid)
        elif isinstance(base_id, str) and base_id.startswith("KALITEXT") and base_id not in text_ids:
            text_ids.insert(0, base_id)

        # Fallback: recursive search for any KALITEXT references
        if not text_ids:
            text_ids = self._find_kalitext_ids_recursive(container)

        return text_ids

    def _find_kalitext_ids_recursive(self, data, found: list[str] | None = None) -> list[str]:
        """Recursively search for KALITEXT IDs in nested structure."""
        if found is None:
            found = []
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and value.startswith("KALITEXT") and value not in found:
                    found.append(value)
                elif isinstance(value, (dict, list)):
                    self._find_kalitext_ids_recursive(value, found)
        elif isinstance(data, list):
            for item in data:
                self._find_kalitext_ids_recursive(item, found)
        return found

    def _extract_articles_from_text(self, text_data: dict) -> list[dict]:
        """Extract all in-force articles from a KALITEXT response.

        Real API article fields: id, cid, num, etat, content (HTML), path, pathTitle,
        dateDebut, dateFin, nota, surtitre, etc.
        etat can be None (treat as in-force since parent text is in-force).
        """
        articles: list[dict] = []

        def _is_in_force(etat: str | None) -> bool:
            if etat is None:
                return True  # No status = inherited from parent
            return etat.startswith("VIGUEUR")

        def _extract_article(art: dict, section_path: str) -> None:
            if not _is_in_force(art.get("etat")):
                return
            content = art.get("content", art.get("texte", art.get("texteHtml", "")))
            if not content:
                return
            articles.append({
                "num": art.get("num") or "",
                "content": self._clean_html(content),
                "section": section_path,
                "etat": art.get("etat", ""),
                "date_debut": art.get("dateDebut", ""),
            })

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

        return articles

    @staticmethod
    def _clean_html(html: str) -> str:
        """Strip HTML tags and normalize whitespace."""
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _format_articles_as_markdown(articles: list[dict], ccn_ref: CcnReference) -> str:
        """Format articles as a Markdown document for ingestion."""
        lines = [
            f"# Convention collective — {ccn_ref.titre} (IDCC {ccn_ref.idcc})",
            "",
        ]
        current_section = ""
        for art in articles:
            section = art.get("section", "")
            if section and section != current_section:
                current_section = section
                lines.append(f"\n## {section}\n")

            num = art.get("num", "")
            if num:
                lines.append(f"### Article {num}\n")
            lines.append(art["content"])
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_accords_as_markdown(
        articles: list[dict], ccn_ref: CcnReference,
    ) -> str:
        """Format accord de branche articles as Markdown for ingestion."""
        titre = ccn_ref.titre_court or ccn_ref.titre
        lines = [
            f"# Accords de branche — {titre} (IDCC {ccn_ref.idcc})",
            "",
        ]
        current_section = ""
        for art in articles:
            section = art.get("section", "")
            if section and section != current_section:
                current_section = section
                lines.append(f"\n## {section}\n")

            num = art.get("num", "")
            if num:
                lines.append(f"### Article {num}\n")
            lines.append(art["content"])
            lines.append("")

        return "\n".join(lines)

    async def _create_document(
        self,
        db: AsyncSession,
        org_conv: OrganisationConvention,
        ccn_ref: CcnReference,
        text_content: str,
        user_id: uuid.UUID,
        storage,
        name_suffix: str = "",
        file_hash_override: str | None = None,
    ) -> Document:
        """Create a single Document record from extracted CCN articles."""
        source_type = "convention_collective_nationale"
        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]

        titre = ccn_ref.titre_court or ccn_ref.titre
        name = f"CCN {titre} (IDCC {ccn_ref.idcc}){name_suffix}"

        file_id = uuid.uuid4()
        storage_path = (
            f"{org_conv.organisation_id}/ccn/{ccn_ref.idcc}/{file_id}.txt"
        )
        text_bytes = text_content.encode("utf-8")
        storage.put_file_bytes(storage_path, text_bytes, content_type="text/plain")

        file_hash = file_hash_override or hashlib.sha256(text_bytes).hexdigest()

        doc = Document(
            organisation_id=org_conv.organisation_id,
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
    def _extract_idcc(conv: dict) -> str | None:
        """Extract IDCC code from a convention listing result."""
        # Try direct field
        idcc = conv.get("idcc", conv.get("num", ""))
        if idcc:
            return str(idcc).zfill(4)

        # Try to extract from title
        title = conv.get("title", conv.get("titre", ""))
        match = re.search(r"IDCC\s*[:\s]?\s*(\d{1,4})", title, re.IGNORECASE)
        if match:
            return match.group(1).zfill(4)

        # Try id field (KALICONT...) — not the IDCC itself
        return None

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
                    delay = _RETRY_DELAY * (2 ** attempt)
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
