"""Synchronisation des textes du Journal officiel (lois, ordonnances, décrets,
arrêtés) via le fond LODA de PISTE Légifrance.

Réutilise les credentials PISTE déjà configurés (mêmes que LegiService /
ConseilConstitService). Pas de nouvelle clé à provisionner.

Stratégie :
1. POST /search sur le fond LODA, fenêtre glissante (publication récente),
   natures LOI / ORDONNANCE / DECRET / ARRETE.
2. Filtre RH "mixte" (cf. _is_rh_relevant) : on garde un texte si son titre
   matche des mots-clés RH OU s'il modifie le Code du travail / Code de la
   sécurité sociale (détecté via les liens du texte consulté).
   Le filtre titre s'applique AVANT toute consultation pour borner le quota
   PISTE : le JO publie des milliers d'arrêtés/nominations sans rapport RH.
3. Pour chaque texte retenu : POST /consult/lawDecree → texte intégral.
4. Création d'un Document (source_type loi/ordonnance/decret/arrete) + ingestion.
5. Dédup par CID (stocké dans Document.numero_pourvoi, comme le Conseil constit).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

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
_TOKEN_REFRESH_MARGIN = 60
_PAGE_SIZE = 100
_MAX_PAGES = 20  # safety cap on /search pagination

_FOND = "LODA_DATE"

# LEGITEXT des codes qu'on suit : un texte qui modifie l'un d'eux est RH-pertinent
_CODE_TRAVAIL_ID = "LEGITEXT000006072050"
_CODE_SECU_ID = "LEGITEXT000006073189"
_RELEVANT_CODE_IDS = frozenset({_CODE_TRAVAIL_ID, _CODE_SECU_ID})

# Natures LODA → source_type de la hiérarchie des normes
_NATURE_TO_SOURCE_TYPE = {
    "LOI": "loi",
    "ORDONNANCE": "ordonnance",
    "DECRET": "decret",
    "ARRETE": "arrete",
}

# Mots-clés RH (normalisés sans accents, en minuscules) cherchés dans le titre.
# Volontairement précis : on évite les mots trop larges ("emploi" attrapait les
# concours administratifs, "rémunération" les honoraires médicaux, "congé" la
# congélation). "travail" isolé est conservé car en titre de JO il désigne
# quasi-toujours le droit du travail (et capte "travailleur", "télétravail"…).
_RH_KEYWORDS = (
    "code du travail",
    "securite sociale",
    "travail",
    "travailleur",
    "salarie",
    "licenciement",
    "duree du travail",
    "temps de travail",
    "risques professionnels",
    "document unique",
    "duerp",
    "sante au travail",
    "accident du travail",
    "maladie professionnelle",
    "rupture conventionnelle",
    "plan de sauvegarde de l'emploi",
    "demandeur d'emploi",
    "france travail",
    "pole emploi",
    "comite social",
    "cse",
    "teletravail",
    "conges payes",
    "conge parental",
    "conge maternite",
    "conge de paternite",
    "smic",
    "harcelement",
    "inaptitude",
    "formation professionnelle",
    "apprentissage",
    "negociation collective",
    "convention collective",
    "egalite professionnelle",
    "prevention des risques",
    "medecine du travail",
    "penibilite",
)


def _normalize(text: str) -> str:
    """Lowercase + strip accents for accent-insensitive keyword matching."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _is_rh_relevant(title: str, modified_code_ids: set[str]) -> bool:
    """Filtre mixte : titre RH OU modifie un code suivi."""
    if modified_code_ids & _RELEVANT_CODE_IDS:
        return True
    normalized = _normalize(title)
    return any(kw in normalized for kw in _RH_KEYWORDS)


def _title_matches_keywords(title: str) -> bool:
    """Pré-filtre bon marché appliqué avant toute consultation (borne le quota)."""
    normalized = _normalize(title)
    return any(kw in normalized for kw in _RH_KEYWORDS)


# --- Types ------------------------------------------------------------------


@dataclass
class JorfText:
    cid: str
    title: str
    nature: str  # LOI / ORDONNANCE / DECRET / ARRETE
    text: str
    publication_date: date | None = None


@dataclass
class JorfSyncResult:
    total_fetched: int = 0
    new_ingested: int = 0
    already_exists: int = 0
    filtered_out: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


# --- Service -----------------------------------------------------------------


class JorfService:
    """Sync des textes JORF (lois/décrets/arrêtés) depuis le fond LODA de PISTE.

    Auth partagée avec LegiService — même app PISTE, même client_id.
    """

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
        if JorfService._cached_token and now < JorfService._token_expires_at:
            return JorfService._cached_token

        async with self._get_lock():
            now = time.monotonic()
            if JorfService._cached_token and now < JorfService._token_expires_at:
                return JorfService._cached_token

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
                JorfService._cached_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                JorfService._token_expires_at = (
                    time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN
                )
                return JorfService._cached_token

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
                    JorfService._cached_token = None
                    JorfService._token_expires_at = 0.0
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
                logger.error("JORF API timeout for %s", path)
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
    ) -> JorfSyncResult:
        """Récupère et ingère les textes JORF RH-pertinents sur la fenêtre."""
        result = JorfSyncResult()

        if not self._client_id or not self._client_secret:
            result.errors = 1
            result.error_messages = ["PISTE credentials non configurés"]
            return result

        if date_end is None:
            date_end = date.today()
        if date_start is None:
            date_start = date_end - timedelta(days=30)

        existing_cids = await self._get_existing_cids(db)

        from app.services.storage_service import StorageService
        storage = StorageService()

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            results_list = await self._search_all(
                client, date_start, date_end, result
            )
            logger.info(
                "JORF sync: %d textes listés (%s → %s)",
                len(results_list), date_start, date_end,
            )

            for raw in results_list:
                try:
                    cid, title, nature = self._parse_search_result(raw)
                    if not cid or nature not in _NATURE_TO_SOURCE_TYPE:
                        continue

                    # Pré-filtre titre AVANT consultation (borne le quota PISTE).
                    if not _title_matches_keywords(title):
                        result.filtered_out += 1
                        continue

                    if cid in existing_cids:
                        result.already_exists += 1
                        continue

                    consult = await self._api_post(
                        client, "/consult/jorf", {"textCid": cid}
                    )
                    if not consult:
                        result.errors += 1
                        continue

                    full_text, modified_code_ids, pub_date = self._parse_consult(
                        consult
                    )
                    if not _is_rh_relevant(title, modified_code_ids):
                        result.filtered_out += 1
                        continue
                    if not full_text or len(full_text) < 50:
                        result.already_exists += 1
                        continue

                    jorf_text = JorfText(
                        cid=cid,
                        title=title,
                        nature=nature,
                        text=full_text,
                        publication_date=pub_date,
                    )
                    doc = await self._create_document(
                        db, jorf_text, user_id, storage
                    )
                    await enqueue_ingestion(str(doc.id))
                    existing_cids.add(cid)
                    result.new_ingested += 1
                except Exception as exc:  # noqa: BLE001
                    result.errors += 1
                    result.error_messages.append(str(exc)[:200])
                    logger.warning("JORF: erreur sur un texte: %s", exc)

        logger.info(
            "JORF sync terminé: %d listés, %d ingérés, %d déjà en base, "
            "%d filtrés, %d erreurs",
            result.total_fetched, result.new_ingested, result.already_exists,
            result.filtered_out, result.errors,
        )
        return result

    # ---- Search ----

    def _build_search_payload(
        self, page_number: int, date_start: date, date_end: date
    ) -> dict:
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
                        "facette": "NATURE",
                        "valeurs": list(_NATURE_TO_SOURCE_TYPE.keys()),
                    },
                    {
                        "facette": "DATE_PUBLICATION",
                        "dates": {
                            "start": date_start.isoformat(),
                            "end": date_end.isoformat(),
                        },
                    },
                ],
                "pageNumber": page_number,
                "pageSize": _PAGE_SIZE,
                "sort": "PUBLICATION_DATE_DESC",
                "typePagination": "DEFAUT",
            },
        }

    async def _search_all(
        self,
        client: httpx.AsyncClient,
        date_start: date,
        date_end: date,
        result: JorfSyncResult,
    ) -> list[dict]:
        results_list: list[dict] = []
        for page_number in range(1, _MAX_PAGES + 1):
            data = await self._api_post(
                client, "/search",
                self._build_search_payload(page_number, date_start, date_end),
            )
            if not data:
                if page_number == 1:
                    result.errors = 1
                    result.error_messages.append("Échec /search LODA")
                break
            page_results = data.get("results", [])
            if page_number == 1:
                result.total_fetched = data.get("totalResultNumber", 0)
            if not page_results:
                break
            results_list.extend(page_results)
            if len(results_list) >= result.total_fetched:
                break
        return results_list

    # ---- Parsing ----

    @staticmethod
    def _parse_search_result(raw: dict) -> tuple[str | None, str, str]:
        """Extract (cid, title, nature) from a LODA /search result row."""
        titles = raw.get("titles") or []
        cid = None
        title = ""
        if titles:
            cid = titles[0].get("cid") or titles[0].get("id")
            title = titles[0].get("title", "")
        cid = cid or raw.get("cid") or raw.get("id")
        title = title or raw.get("title", "")
        nature = (raw.get("nature") or "").upper()
        return cid, title, nature

    @staticmethod
    def _parse_consult(consult: dict) -> tuple[str, set[str], date | None]:
        """From /consult/jorf, return (full_text, modified_code_ids, pub_date).

        Le texte vit dans articles[].content (HTML). Les codes modifiés/cités
        apparaissent sous forme de liens cidTexte=LEGITEXT... dans le HTML : on
        les détecte par simple présence de l'identifiant dans la réponse brute.
        """
        import json as _json

        from app.services.html_to_markdown import html_to_markdown

        articles = consult.get("articles") or []
        parts: list[str] = []
        for art in articles:
            etat = (art.get("etat") or "").upper()
            if etat not in ("VIGUEUR", "VIGUEUR_DIFF", ""):
                continue
            content = art.get("content") or ""
            if not content:
                continue
            md = html_to_markdown(content) if "<" in content else content
            num = art.get("num", "")
            parts.append(f"Article {num}\n{md}" if num else md)
        full_text = "\n\n".join(parts)

        if not full_text:
            for key in ("notice", "nota", "visa"):
                raw = consult.get(key) or ""
                if raw:
                    full_text = html_to_markdown(raw) if "<" in raw else raw
                    break

        # Codes modifiés/cités : présence de l'identifiant LEGITEXT dans la réponse
        raw_json = _json.dumps(consult, ensure_ascii=False)
        modified_code_ids = {cid for cid in _RELEVANT_CODE_IDS if cid in raw_json}

        pub_date: date | None = None
        for key in ("dateTexte", "dateParution", "datePublication"):
            value = consult.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value:
                try:
                    pub_date = datetime.fromtimestamp(value / 1000, UTC).date()
                    break
                except (ValueError, OSError):
                    continue
            elif isinstance(value, str) and value:
                try:
                    pub_date = datetime.strptime(value[:10], "%Y-%m-%d").date()
                    break
                except ValueError:
                    continue

        return full_text, modified_code_ids, pub_date

    # ---- DB ----

    async def _get_existing_cids(self, db: AsyncSession) -> set[str]:
        """CIDs JORF déjà ingérés (stockés dans numero_pourvoi)."""
        result = await db.execute(
            select(Document.numero_pourvoi).where(
                Document.source_type.in_(tuple(_NATURE_TO_SOURCE_TYPE.values())),
                Document.organisation_id.is_(None),
                Document.numero_pourvoi.isnot(None),
            )
        )
        return {row[0] for row in result.all()}

    async def _create_document(
        self,
        db: AsyncSession,
        jorf_text: JorfText,
        user_id: uuid.UUID,
        storage,
    ) -> Document:
        source_type = _NATURE_TO_SOURCE_TYPE[jorf_text.nature]
        hierarchy = DOCUMENT_TYPE_HIERARCHY[source_type]

        name = jorf_text.title[:250] if jorf_text.title else f"JORF {jorf_text.cid}"

        file_id = uuid.uuid4()
        safe_cid = jorf_text.cid.replace(" ", "_")
        storage_path = f"common/jorf/{file_id}_{safe_cid}.txt"
        text_bytes = jorf_text.text.encode("utf-8")
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
            numero_pourvoi=jorf_text.cid,  # clé de dédup
            date_decision=jorf_text.publication_date,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc
