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
        """Fetch a full convention collective from KALI and ingest it."""
        result = KaliInstallResult()

        # Update status
        org_conv.status = "fetching"
        await db.commit()

        try:
            ccn_ref = await db.get(CcnReference, org_conv.idcc)
            if not ccn_ref or not ccn_ref.kali_id:
                raise ValueError(f"IDCC {org_conv.idcc} introuvable dans le référentiel")

            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                # Step 1: Get container to find KALITEXT IDs
                container = await self._api_post(
                    client, "/consult/kaliCont", json_body={"id": ccn_ref.kali_id}
                )
                if container is None:
                    raise ValueError(f"Container KALI introuvable pour {ccn_ref.kali_id}")

                # Extract text IDs from container structure
                text_ids = self._extract_text_ids(container)
                if not text_ids:
                    raise ValueError("Aucun texte trouvé dans le container KALI")

                logger.info(
                    "KALI install IDCC %s: %d text(s) to fetch",
                    org_conv.idcc, len(text_ids),
                )

                # Step 2: Fetch each text and extract articles
                all_articles: list[dict] = []
                for text_id in text_ids:
                    await asyncio.sleep(_API_THROTTLE)
                    text_data = await self._api_post(
                        client, "/consult/kaliText", json_body={"id": text_id}
                    )
                    if text_data is None:
                        result.errors += 1
                        result.error_messages.append(f"Texte {text_id} introuvable")
                        continue

                    # Only in-force texts (etat can be None in API response,
                    # but we already filtered by etat in _extract_text_ids)
                    text_etat = text_data.get("etat") or ""
                    if text_etat and not text_etat.startswith("VIGUEUR"):
                        continue

                    articles = self._extract_articles_from_text(text_data)
                    all_articles.extend(articles)

            result.articles_count = len(all_articles)
            logger.info(
                "KALI IDCC %s: %d articles extracted, creating documents",
                org_conv.idcc, len(all_articles),
            )

            # Step 3: Update status and create documents
            org_conv.status = "indexing"
            await db.commit()

            from app.services.storage_service import StorageService
            storage = StorageService()

            # Create a single document with all articles
            text_content = self._format_articles_as_markdown(all_articles, ccn_ref)
            doc = await self._create_document(
                db, org_conv, ccn_ref, text_content,
                user_id=user_id,
                storage=storage,
            )
            await enqueue_ingestion(str(doc.id))
            result.documents_created = 1

            # Step 4: Mark as ready
            org_conv.status = "ready"
            org_conv.articles_count = result.articles_count
            org_conv.installed_at = datetime.now(UTC)
            org_conv.last_synced_at = datetime.now(UTC)
            org_conv.error_message = None
            await db.commit()

        except Exception as exc:
            org_conv.status = "error"
            org_conv.error_message = str(exc)[:500]
            await db.commit()
            result.errors += 1
            result.error_messages.append(str(exc))
            logger.exception("KALI install failed for IDCC %s", org_conv.idcc)

        return result

    # --- Private methods ---

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

    async def _create_document(
        self,
        db: AsyncSession,
        org_conv: OrganisationConvention,
        ccn_ref: CcnReference,
        text_content: str,
        user_id: uuid.UUID,
        storage,
    ) -> Document:
        """Create a single Document record from all extracted CCN articles."""
        source_type = "convention_collective_nationale"
        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]

        titre = ccn_ref.titre_court or ccn_ref.titre
        name = f"CCN {titre} (IDCC {ccn_ref.idcc})"

        file_id = uuid.uuid4()
        storage_path = (
            f"{org_conv.organisation_id}/ccn/{ccn_ref.idcc}/{file_id}.txt"
        )
        text_bytes = text_content.encode("utf-8")
        storage.put_file_bytes(storage_path, text_bytes, content_type="text/plain")

        file_hash = hashlib.sha256(text_bytes).hexdigest()

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
