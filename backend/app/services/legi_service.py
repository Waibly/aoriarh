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
_REQUEST_TIMEOUT = 180.0  # Codes are large payloads
_RETRY_DELAY = 2.0
_MAX_RETRIES = 3
_TOKEN_REFRESH_MARGIN = 300
_API_THROTTLE = 0.2

# All codes that can be synced automatically
SYNCABLE_CODES: dict[str, dict] = {
    "code_travail": {
        "text_id": "LEGITEXT000006072050",
        "name": "Code du travail",
        "has_reglementaire": True,
        "storage_prefix": "common/code_travail",
    },
    "code_civil": {
        "text_id": "LEGITEXT000006070721",
        "name": "Code civil",
        "source_type": "code_civil",
        "has_reglementaire": False,
        "storage_prefix": "common/code_civil",
    },
    "code_penal": {
        "text_id": "LEGITEXT000006070719",
        "name": "Code pénal",
        "source_type": "code_penal",
        "has_reglementaire": False,
        "storage_prefix": "common/code_penal",
    },
    "code_securite_sociale": {
        "text_id": "LEGITEXT000006073189",
        "name": "Code de la sécurité sociale",
        "source_type": "code_securite_sociale",
        "has_reglementaire": True,
        "storage_prefix": "common/code_securite_sociale",
    },
    "code_action_sociale": {
        "text_id": "LEGITEXT000006074069",
        "name": "Code de l'action sociale et des familles",
        "source_type": "code_civil",  # reuse code_civil hierarchy for now
        "has_reglementaire": False,
        "storage_prefix": "common/code_action_sociale",
    },
}


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
            # Step 1: Fetch entire code via /consult/legiPart (single API call, all articles inline)
            logger.info("LegiService: fetching Code du travail via legiPart...")
            articles_legislatif: list[dict] = []
            articles_reglementaire: list[dict] = []

            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                data = await self._api_post(client, "/consult/legiPart", {
                    "textId": _LEGITEXT_CODE_TRAVAIL,
                    "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                })
                if data is None:
                    raise ValueError("Impossible de récupérer le Code du travail depuis l'API LEGI")

                # Walk the structure to extract all articles with content
                sections = data.get("sections", [])
                for section in sections:
                    section_title = section.get("title", section.get("titre", ""))
                    is_reglementaire = self._is_reglementaire_section(section_title)

                    articles = self._extract_articles_from_section(section, section_title)

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

    async def sync_code(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        code_key: str,
    ) -> LegiSyncResult:
        """Generic sync for any code (Code civil, Code pénal, CSS, CASF...).

        Uses the same blue-green logic as sync_code_travail but for any code.
        """
        result = LegiSyncResult()

        code_def = SYNCABLE_CODES.get(code_key)
        if not code_def:
            result.errors = 1
            result.error_messages = [f"Code inconnu: {code_key}"]
            return result

        if not self._client_id or not self._client_secret:
            result.errors = 1
            result.error_messages = ["Credentials Légifrance non configurés"]
            return result

        try:
            text_id = code_def["text_id"]
            code_name = code_def["name"]
            source_type = code_def.get("source_type", code_key)
            has_regl = code_def.get("has_reglementaire", False)
            storage_prefix = code_def["storage_prefix"]

            logger.info("LegiService: fetching %s (%s)...", code_name, text_id)

            articles_leg: list[dict] = []
            articles_regl: list[dict] = []

            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                data = await self._api_post(client, "/consult/legiPart", {
                    "textId": text_id,
                    "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                })
                if data is None:
                    raise ValueError(f"Impossible de récupérer {code_name}")

                sections = data.get("sections", [])
                for section in sections:
                    section_title = section.get("title", section.get("titre", ""))
                    articles = self._extract_articles_from_section(section, section_title)

                    if has_regl and self._is_reglementaire_section(section_title):
                        articles_regl.extend(articles)
                    else:
                        articles_leg.extend(articles)

            result.articles_legislatif = len(articles_leg)
            result.articles_reglementaire = len(articles_regl)
            logger.info(
                "LegiService: %s — %d articles législatifs, %d réglementaires",
                code_name, len(articles_leg), len(articles_regl),
            )

            from app.services.storage_service import StorageService
            storage = StorageService()

            if articles_leg:
                doc_name = f"{code_name} — Partie législative" if has_regl else code_name
                changed, doc_id = await self._sync_part(
                    db=db,
                    articles=articles_leg,
                    source_type=source_type,
                    doc_name=doc_name,
                    user_id=user_id,
                    storage=storage,
                    storage_prefix=storage_prefix,
                )
                result.legislatif_changed = changed
                result.doc_legislatif_id = doc_id

            if has_regl and articles_regl:
                regl_source_type = f"{source_type}_reglementaire"
                changed, doc_id = await self._sync_part(
                    db=db,
                    articles=articles_regl,
                    source_type=regl_source_type,
                    doc_name=f"{code_name} — Partie réglementaire",
                    user_id=user_id,
                    storage=storage,
                    storage_prefix=storage_prefix,
                )
                result.reglementaire_changed = changed
                result.doc_reglementaire_id = doc_id

        except Exception as exc:
            result.errors += 1
            result.error_messages.append(str(exc)[:500])
            logger.exception("LegiService: sync %s failed", code_key)

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
        storage_prefix: str = "common/code_travail",
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
        storage_path = f"{storage_prefix}/{file_id}.txt"
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

    @classmethod
    def _extract_articles_from_section(
        cls,
        section: dict,
        path: str,
    ) -> list[dict]:
        """Recursively extract articles with content from a legiPart section."""
        articles: list[dict] = []

        for article in section.get("articles", []):
            if not cls._is_in_force(article):
                continue
            content = (
                article.get("texte")
                or article.get("texteHtml")
                or article.get("content")
                or ""
            )
            if content:
                articles.append({
                    "num": article.get("num", ""),
                    "content": cls._clean_html(content),
                    "section": path,
                })

        for child in section.get("sections", section.get("children", [])):
            child_title = child.get("title", child.get("titre", ""))
            child_path = f"{path} > {child_title}" if child_title else path
            articles.extend(cls._extract_articles_from_section(child, child_path))

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
