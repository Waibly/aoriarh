"""Service de synchronisation du Code du travail via l'API LEGI (Légifrance / PISTE).

Récupère les articles en vigueur du Code du travail (LEGITEXT000006072050)
et les ingère comme documents communs dans le pipeline RAG.

Produit 2 documents :
- Partie législative (articles L.) → source_type: code_travail (niveau 3)
- Partie réglementaire (articles R./D.) → source_type: code_travail_reglementaire (niveau 5)
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
from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.tasks import enqueue_ingestion

logger = logging.getLogger(__name__)

_LEGITEXT_CODE_TRAVAIL = "LEGITEXT000006072050"
_REQUEST_TIMEOUT = 120.0
_RETRY_DELAY = 2.0
_MAX_RETRIES = 3
_TOKEN_REFRESH_MARGIN = 300
_API_THROTTLE = 0.2


@dataclass
class LegiSyncResult:
    """Result of a Code du travail sync."""

    articles_legislatif: int = 0
    articles_reglementaire: int = 0
    doc_legislatif_id: str | None = None
    doc_reglementaire_id: str | None = None
    legislatif_changed: bool = False
    reglementaire_changed: bool = False
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


class LegiService:
    """Fetches the Code du travail from the LEGI API on PISTE."""

    # Share token cache with KaliService (same PISTE app)
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
        now = time.monotonic()
        if LegiService._cached_token and now < LegiService._token_expires_at:
            return LegiService._cached_token

        async with self._get_lock():
            now = time.monotonic()
            if LegiService._cached_token and now < LegiService._token_expires_at:
                return LegiService._cached_token

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

            LegiService._cached_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            LegiService._token_expires_at = (
                time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN
            )
            return LegiService._cached_token

    # --- Public API ---

    async def sync_code_travail(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> LegiSyncResult:
        """Fetch the Code du travail from LEGI API and create/update common documents.

        Uses blue-green: new documents are created before old ones are deleted.
        """
        result = LegiSyncResult()

        if not self._client_id or not self._client_secret:
            result.errors = 1
            result.error_messages = ["Credentials Légifrance non configurés"]
            return result

        try:
            # Step 1: Fetch table of contents to get all section/article structure
            logger.info("LegiService: fetching Code du travail structure...")
            articles_legislatif: list[dict] = []
            articles_reglementaire: list[dict] = []

            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                # Fetch the code's table of contents
                toc = await self._api_post(client, "/consult/code/tableMatieres", {
                    "textId": _LEGITEXT_CODE_TRAVAIL,
                    "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                })
                if toc is None:
                    raise ValueError("Impossible de récupérer la table des matières du Code du travail")

                # Walk the TOC to extract all articles
                sections = toc.get("sections", [])
                for section in sections:
                    section_title = section.get("title", section.get("titre", ""))
                    is_reglementaire = self._is_reglementaire_section(section_title)

                    articles = await self._fetch_section_articles(
                        client, section, section_title
                    )

                    if is_reglementaire:
                        articles_reglementaire.extend(articles)
                    else:
                        articles_legislatif.extend(articles)

            result.articles_legislatif = len(articles_legislatif)
            result.articles_reglementaire = len(articles_reglementaire)
            logger.info(
                "LegiService: %d articles législatifs, %d articles réglementaires",
                result.articles_legislatif, result.articles_reglementaire,
            )

            from app.services.storage_service import StorageService
            storage = StorageService()

            # Step 2: Process partie législative
            if articles_legislatif:
                changed, doc_id = await self._sync_part(
                    db=db,
                    articles=articles_legislatif,
                    source_type="code_travail",
                    doc_name="Code du travail — Partie législative",
                    user_id=user_id,
                    storage=storage,
                )
                result.legislatif_changed = changed
                result.doc_legislatif_id = doc_id

            # Step 3: Process partie réglementaire
            if articles_reglementaire:
                changed, doc_id = await self._sync_part(
                    db=db,
                    articles=articles_reglementaire,
                    source_type="code_travail_reglementaire",
                    doc_name="Code du travail — Partie réglementaire",
                    user_id=user_id,
                    storage=storage,
                )
                result.reglementaire_changed = changed
                result.doc_reglementaire_id = doc_id

        except Exception as exc:
            result.errors += 1
            result.error_messages.append(str(exc)[:500])
            logger.exception("LegiService: sync failed")

        return result

    # --- Private methods ---

    async def _sync_part(
        self,
        db: AsyncSession,
        articles: list[dict],
        source_type: str,
        doc_name: str,
        user_id: uuid.UUID,
        storage,
    ) -> tuple[bool, str | None]:
        """Sync one part (législative or réglementaire) with blue-green.

        Returns (changed, new_doc_id).
        """
        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]
        text_content = self._format_articles_as_markdown(articles, doc_name)
        new_hash = hashlib.sha256(text_content.encode("utf-8")).hexdigest()

        # Find existing document
        existing_result = await db.execute(
            select(Document).where(
                Document.organisation_id.is_(None),
                Document.source_type == source_type,
                Document.name == doc_name,
            )
        )
        existing_docs = list(existing_result.scalars().all())

        # Check if content changed
        if existing_docs and existing_docs[0].file_hash == new_hash:
            logger.info("LegiService: %s unchanged (hash match)", doc_name)
            return False, None

        # Create new document (blue)
        text_bytes = text_content.encode("utf-8")
        file_id = uuid.uuid4()
        storage_path = f"common/code_travail/{file_id}.txt"
        storage.put_file_bytes(storage_path, text_bytes, content_type="text/plain")

        new_doc = Document(
            organisation_id=None,
            name=doc_name,
            source_type=source_type,
            norme_niveau=hierarchy["niveau"],
            norme_poids=hierarchy["poids"],
            storage_path=storage_path,
            indexation_status="pending",
            uploaded_by=user_id,
            file_size=len(text_bytes),
            file_format="txt",
            file_hash=new_hash,
        )
        db.add(new_doc)
        await db.commit()
        await db.refresh(new_doc)

        # Enqueue ingestion
        await enqueue_ingestion(str(new_doc.id))

        # Schedule cleanup of old documents (green phase)
        if existing_docs:
            old_ids = [str(d.id) for d in existing_docs]
            from app.services.kali_service import KaliService
            await KaliService._enqueue_old_docs_cleanup(old_ids)
            logger.info(
                "LegiService: %s updated (blue-green) — new=%s, old=%s",
                doc_name, new_doc.id, old_ids,
            )
        else:
            logger.info("LegiService: %s created — doc=%s", doc_name, new_doc.id)

        return True, str(new_doc.id)

    async def _fetch_section_articles(
        self,
        client: httpx.AsyncClient,
        section: dict,
        path: str,
    ) -> list[dict]:
        """Recursively fetch articles from a TOC section."""
        articles: list[dict] = []

        # Extract articles at this level
        for article in section.get("articles", []):
            if not self._is_in_force(article):
                continue
            content = article.get("content", article.get("texte", ""))
            if not content:
                # Need to fetch full article
                article_id = article.get("id", "")
                if article_id:
                    await asyncio.sleep(_API_THROTTLE)
                    full = await self._api_post(client, "/consult/getArticle", {
                        "id": article_id,
                    })
                    if full:
                        content = full.get("article", {}).get("texte", full.get("texte", ""))

            if content:
                articles.append({
                    "num": article.get("num", ""),
                    "content": self._clean_html(content),
                    "section": path,
                })

        # Recurse into sub-sections
        for child in section.get("sections", section.get("children", [])):
            child_title = child.get("title", child.get("titre", ""))
            child_path = f"{path} > {child_title}" if child_title else path

            # If child has articles inline, extract them
            child_articles = await self._fetch_section_articles(client, child, child_path)
            articles.extend(child_articles)

        return articles

    @staticmethod
    def _is_reglementaire_section(title: str) -> bool:
        """Check if a section belongs to the regulatory part."""
        title_lower = title.lower()
        return (
            "réglementaire" in title_lower
            or "reglementaire" in title_lower
            or title_lower.startswith("partie r")
        )

    @staticmethod
    def _is_in_force(article: dict) -> bool:
        """Check if an article is currently in force."""
        etat = article.get("etat", article.get("state", ""))
        if not etat:
            return True
        return etat.upper() in ("VIGUEUR", "VIGUEUR_DIFF", "")

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
    def _format_articles_as_markdown(articles: list[dict], title: str) -> str:
        """Format articles as a Markdown document."""
        lines = [f"# {title}\n"]
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

    async def _api_post(
        self,
        client: httpx.AsyncClient,
        path: str,
        json_body: dict,
    ) -> dict | None:
        """Make a POST request to the Légifrance API."""
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
                    LegiService._cached_token = None
                    LegiService._token_expires_at = 0.0
                    continue

                if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_DELAY * (2 ** attempt)
                    logger.warning("LEGI rate limit (429), retry in %.1fs", delay)
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
                logger.error("LEGI API timeout for %s", path)
                return None

        return None
