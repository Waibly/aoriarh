"""Service de synchronisation du BOSS (Bulletin Officiel de la Sécurité Sociale).

Récupère la doctrine administrative *opposable* en matière de cotisations et
contributions sociales depuis boss.gouv.fr, la convertit en Markdown et
l'ingère dans le corpus commun.

Le BOSS n'expose pas d'API : on crawle l'arborescence HTML. Chaque page de
rubrique liste ses sous-pages côté serveur, et chaque page de contenu porte la
version en vigueur dans un bloc ``<article id="article">`` (les blocs
``_vdiff`` / ``_vrecherche`` sont des placeholders remplis en JavaScript, donc
vides côté serveur — on ne prend que la version en vigueur, cf. décision v1).

Le site est protégé par un WAF qui rejette les requêtes sans en-têtes de
navigateur : on envoie donc un User-Agent + Accept-Language réalistes.

Idempotent : chaque page a un ``storage_path`` déterministe. Un re-crawl mensuel
ne ré-indexe que les pages dont le contenu a réellement changé (comparaison de
hash) ; les pages inchangées ne coûtent rien.

Source : https://boss.gouv.fr/
"""

import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.tasks import enqueue_ingestion
from app.services.html_to_markdown import html_to_markdown

logger = logging.getLogger(__name__)

BOSS_BASE_URL = "https://boss.gouv.fr"
_REQUEST_TIMEOUT = 60.0
_MAX_PAGES = 600  # garde-fou anti-boucle (l'arbre réel fait ~150-250 pages)
_MIN_CONTENT_CHARS = 400  # en-dessous : page de navigation, pas de doctrine
_CRAWL_DELAY = 0.4  # politesse entre requêtes (s)

# En-têtes navigateur : le WAF de boss.gouv.fr rejette les requêtes « robot ».
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Les 8 rubriques du BOSS (source de vérité du périmètre v1). Le crawl part de
# ces racines et ne suit que les liens de leur sous-arbre respectif.
BOSS_ROOTS: list[tuple[str, str]] = [
    ("/portail/accueil/regles-dassujettissement.html", "Règles d'assujettissement"),
    ("/portail/accueil/exonerations.html", "Exonérations"),
    ("/portail/accueil/autres-elements-de-remuneration.html", "Autres éléments de rémunération"),
    ("/portail/accueil/bulletin-de-paie.html", "Bulletin de paie"),
    ("/portail/accueil/controle.html", "Contrôle"),
    ("/portail/accueil/mesures-exceptionnelles.html", "Mesures exceptionnelles"),
    ("/portail/accueil/rescrits.html", "Rescrits sociaux"),
    ("/portail/accueil/table-des-parametres.html", "Table des paramètres"),
]

# Stem de 1er niveau (« exonerations », « rescrits »…) → libellé de rubrique.
# Chaque page porte dans son en-tête la nav vers les 8 racines : on ne peut donc
# pas déduire la rubrique du parcours BFS. On la dérive du chemin de la page.
_STEM_TO_LABEL: dict[str, str] = {
    path.split("/")[-1].removesuffix(".html"): label for path, label in BOSS_ROOTS
}
_ROOT_STEMS = frozenset(_STEM_TO_LABEL)

_HREF_RE = re.compile(r'href="([^"#?]+\.html)"', re.IGNORECASE)
_ARTICLE_OPEN_RE = re.compile(r'<article\b[^>]*\bid="article"[^>]*>', re.IGNORECASE)
_ARTICLE_TAG_RE = re.compile(r'<article\b[^>]*>|</article>', re.IGNORECASE)
_TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_A_JOUR_RE = re.compile(r"jour\s+au\s+(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class BossSyncResult:
    """Résultat d'une synchronisation BOSS."""

    pages_crawled: int = 0
    docs_created: int = 0
    docs_updated: int = 0
    docs_unchanged: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


class BossService:
    """Crawle et ingère la doctrine du BOSS depuis boss.gouv.fr."""

    async def sync(self, db: AsyncSession, user_id: uuid.UUID) -> BossSyncResult:
        """Crawle les 8 rubriques et (ré)ingère les pages dont le contenu a changé."""
        from app.services.storage_service import StorageService

        result = BossSyncResult()
        storage = StorageService()

        # BFS sur l'arbre des 8 rubriques (visited global : chaque page n'est
        # crawlée qu'une fois, quel que soit le chemin de nav qui y mène).
        queue: list[str] = [path for path, _ in BOSS_ROOTS]
        visited: set[str] = set()

        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            while queue and len(visited) < _MAX_PAGES:
                path = queue.pop(0)
                if path in visited:
                    continue
                visited.add(path)
                rubrique = self._rubrique_for_path(path)

                try:
                    html = await self._fetch(client, path)
                except Exception as exc:
                    result.errors += 1
                    result.error_messages.append(f"{path}: {str(exc)[:120]}")
                    logger.warning("BOSS: échec récupération %s: %s", path, exc)
                    continue

                result.pages_crawled += 1

                # Découvre les sous-pages du BOSS (toutes rubriques confondues).
                for child in self._extract_child_paths(html):
                    if child not in visited:
                        queue.append(child)

                # Extrait la version en vigueur et ingère si c'est de la doctrine.
                article_html = self._slice_article(html)
                if not article_html:
                    continue
                markdown = self._article_to_markdown(article_html)
                if len(markdown) < _MIN_CONTENT_CHARS:
                    continue

                try:
                    await self._upsert_document(
                        db, storage, user_id, path, rubrique, html, markdown, result
                    )
                except Exception as exc:
                    result.errors += 1
                    result.error_messages.append(f"{path}: {str(exc)[:120]}")
                    logger.warning("BOSS: échec ingestion %s: %s", path, exc)
                    await db.rollback()

                await asyncio.sleep(_CRAWL_DELAY)

        logger.info(
            "BOSS sync terminée — %d pages crawlées, %d créées, %d mises à jour, "
            "%d inchangées, %d erreurs",
            result.pages_crawled, result.docs_created, result.docs_updated,
            result.docs_unchanged, result.errors,
        )
        return result

    # ---- HTTP ----

    async def _fetch(self, client: httpx.AsyncClient, path: str) -> str:
        """Récupère une page (chemin absolu) avec un retry simple."""
        url = f"{BOSS_BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                await asyncio.sleep(1.0 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    # ---- Parsing HTML ----

    @staticmethod
    def _rubrique_for_path(path: str) -> str:
        """Libellé de rubrique déduit du 1er segment du chemin de la page."""
        rest = path[len("/portail/accueil/"):]
        stem = rest.split("/", 1)[0].removesuffix(".html")
        return _STEM_TO_LABEL.get(stem, "BOSS")

    def _extract_child_paths(self, html: str) -> list[str]:
        """Liens .html appartenant à l'arbre des 8 rubriques (dédupliqués)."""
        out: list[str] = []
        seen: set[str] = set()
        for m in _HREF_RE.finditer(html):
            path = self._normalize_path(m.group(1))
            if path and path not in seen and self._in_scope(path):
                seen.add(path)
                out.append(path)
        return out

    @staticmethod
    def _normalize_path(href: str) -> str | None:
        """Ramène un href (absolu ou relatif au site) à un chemin ``/portail/...``."""
        if href.startswith(BOSS_BASE_URL):
            href = href[len(BOSS_BASE_URL):]
        if href.startswith("http"):
            return None  # lien externe
        if not href.startswith("/"):
            return None  # relatif ambigu : ignoré (le site utilise des chemins absolus)
        return href

    @staticmethod
    def _in_scope(path: str) -> bool:
        """True si le chemin appartient au sous-arbre d'une des 8 rubriques."""
        if not path.startswith("/portail/accueil/"):
            return False
        rest = path[len("/portail/accueil/"):]
        stem = rest.split("/", 1)[0].removesuffix(".html")
        return stem in _ROOT_STEMS

    @staticmethod
    def _slice_article(html: str) -> str | None:
        """Extrait le bloc ``<article id="article">…</article>`` (version en vigueur).

        Scan avec comptage de profondeur pour gérer d'éventuels ``<article>``
        imbriqués sans casser sur le premier ``</article>``.
        """
        m = _ARTICLE_OPEN_RE.search(html)
        if not m:
            return None
        start = m.start()
        depth = 0
        end = len(html)
        for tag in _ARTICLE_TAG_RE.finditer(html, m.start()):
            if tag.group(0).startswith("</"):
                depth -= 1
            else:
                depth += 1
            if depth == 0:
                end = tag.end()
                break
        return html[start:end]

    @staticmethod
    def _article_to_markdown(article_html: str) -> str:
        md = html_to_markdown(article_html)
        return re.sub(r"\n{3,}", "\n\n", md).strip()

    def _page_title(self, html: str) -> str:
        m = _TITLE_RE.search(html)
        if not m:
            return ""
        text = _TAG_RE.sub(" ", m.group(1))
        from html import unescape
        return re.sub(r"\s+", " ", unescape(text)).strip()

    @staticmethod
    def _parse_a_jour_date(article_html: str) -> date | None:
        """Date « à jour au JJ/MM/AAAA » si présente sur la page."""
        m = _A_JOUR_RE.search(article_html)
        if not m:
            return None
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    # ---- Persistance ----

    def _build_storage_path(self, page_path: str) -> str:
        """Chemin MinIO déterministe dérivé du chemin de la page BOSS."""
        rel = page_path[len("/portail/accueil/"):].removesuffix(".html")
        rel = re.sub(r"[^a-zA-Z0-9/_-]", "_", rel)
        return f"common/boss/{rel}.md"

    def _format_markdown(
        self, title: str, rubrique: str, page_path: str, body: str
    ) -> str:
        body = body.lstrip()
        # Évite le doublon de titre : l'article porte déjà son propre <h1>.
        if body.startswith("# "):
            body = body.split("\n", 1)[1].lstrip() if "\n" in body else ""
        header = [
            f"# {title}" if title else f"# BOSS — {rubrique}",
            "",
            f"**Source** : BOSS — {rubrique}",
            f"**URL** : {BOSS_BASE_URL}{page_path}",
            "",
            "---",
            "",
        ]
        return "\n".join(header) + body

    async def _upsert_document(
        self,
        db: AsyncSession,
        storage,
        user_id: uuid.UUID,
        page_path: str,
        rubrique: str,
        html: str,
        markdown_body: str,
        result: BossSyncResult,
    ) -> None:
        """Crée, met à jour (si le contenu a changé) ou ignore une page BOSS."""
        title = self._page_title(html)
        full_md = self._format_markdown(title, rubrique, page_path, markdown_body)
        md_bytes = full_md.encode("utf-8")
        file_hash = hashlib.sha256(md_bytes).hexdigest()
        storage_path = self._build_storage_path(page_path)
        content_date = self._parse_a_jour_date(html)
        name = f"BOSS — {rubrique} — {title}" if title else f"BOSS — {rubrique}"
        hierarchy = DOCUMENT_TYPE_HIERARCHY["boss"]

        existing = await db.execute(
            select(Document).where(
                Document.organisation_id.is_(None),
                Document.storage_path == storage_path,
            ).limit(1)
        )
        doc = existing.scalar_one_or_none()

        if doc is not None and doc.file_hash == file_hash:
            result.docs_unchanged += 1
            return

        storage.put_file_bytes(storage_path, md_bytes, content_type="text/plain")

        if doc is None:
            doc = Document(
                organisation_id=None,
                name=name[:500],
                source_type="boss",
                norme_niveau=hierarchy["niveau"],
                norme_poids=hierarchy["poids"],
                storage_path=storage_path,
                indexation_status="pending",
                uploaded_by=user_id,
                file_size=len(md_bytes),
                file_format="md",
                file_hash=file_hash,
                date_decision=content_date,
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            result.docs_created += 1
        else:
            # Contenu modifié : on met à jour et on ré-ingère. Le pipeline fait
            # un insert-then-swap sur document_id → remplace les anciens chunks.
            doc.name = name[:500]
            doc.file_size = len(md_bytes)
            doc.file_hash = file_hash
            doc.date_decision = content_date
            doc.indexation_status = "pending"
            await db.commit()
            result.docs_updated += 1

        await enqueue_ingestion(str(doc.id))
