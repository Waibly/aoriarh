"""Génération de posts LinkedIn sourcés pour l'équipe AORIA RH."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.core.limiter import limiter
from app.models.api_usage import ApiUsageLog
from app.models.user import User
from app.rag.agent import _OUT_OF_SCOPE_MARKER, RAGAgent
from app.rag.config import RAG_TIMEOUT_CONTEXT, RAG_TIMEOUT_STREAM_IDLE
from app.rag.pipeline import prepare_rag_context
from app.rag.search import SearchResult
from app.services.cost_tracker import cost_tracker

router = APIRouter()
logger = logging.getLogger(__name__)

_COMMON_CORPUS_ORG_ID = "00000000-0000-0000-0000-000000000000"
_LINKEDIN_MAX_CHARS = 3000
_LINKEDIN_BODY_MAX_CHARS = 2500
_LINKEDIN_MIN_WORDS = 200
_LINKEDIN_MAX_WORDS = 300
_LINKEDIN_MAX_REFERENCES = 4
_LINKEDIN_MAX_REVISIONS = 2
_LINKEDIN_MAX_EMPTY_RETRIES = 1
_REFERENCE_LINE_MAX_CHARS = 480
_HASHTAG_RE = re.compile(r"(?<!\w)#[\wÀ-ÿ-]+")
_EMOJI_RE = re.compile(
    "[\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff\U00002600-\U000027bf]+",
)
_MARKDOWN_RE = re.compile(
    r"(?:\*\*|__|```|`[^`]+`|^\s{0,3}#{1,6}\s|^\s*[-*+]\s+|\[[^]]+]\([^)]+\))",
    re.MULTILINE,
)
_WORD_RE = re.compile(r"\b[\wÀ-ÿ]+(?:[’'-][\wÀ-ÿ]+)*\b")
_STYLE_BLOAT_RE = re.compile(
    r"\b(?:très|vraiment|extrêmement|absolument|totalement|parfaitement|"
    r"incroyablement|clairement|concrètement|effectivement|évidemment|"
    r"indéniablement|incontestablement|incontournable|révolutionnaire|"
    r"globalement|finalement|ensuite|enfin|aussi|souvent|strictement|réellement|"
    r"simplement|directement|précisément|potentiellement|juridiquement|"
    r"automatiquement|systématiquement|cependant|ainsi|donc|par ailleurs|"
    r"en effet|assez|d['’]abord|ultime|"
    r"exceptionnel(?:le|les|s)?|meilleur(?:e|es|s)?)\b",
    re.IGNORECASE,
)
_GENERIC_CTA_RE = re.compile(
    r"(?:qu['’]en pensez-vous|et vous|des avis|votre avis|ça vous parle|"
    r"qu['’]est-ce que vous en pensez)\s*\?\s*$",
    re.IGNORECASE,
)
_SUBJECT_VERB_INVERSION_RE = re.compile(
    r"\b(?!rendez[-‑–]vous\b)[a-zà-ÿ]+(?:[-‑–]t)?[-‑–]"
    r"(?:je|tu|il|elle|on|nous|vous|ils|elles)\b",
    re.IGNORECASE,
)
_EDITORIAL_AUTOMATISM_RE = re.compile(
    r"(?m)^\s*(?:(?:autre|dernier)\s+[^:\n]{1,40}|sur le terrain RH|"
    r"à retenir|en conclusion|pour résumer|ce qu['’]il faut retenir)\s*[:：]",
    re.IGNORECASE,
)
_META_DISCOURSE_RE = re.compile(
    r"(?:^|(?<=[.!?]))[ \t]*(?:autrement dit|en d['’]autres termes|en pratique|"
    r"la question devient(?: donc)?)\s*[: ,]",
    re.IGNORECASE | re.MULTILINE,
)
_PROMOTIONAL_WORDING_RE = re.compile(
    r"\b(?:angle contentieux|calcul robuste|calcul incontestable|accord solide|"
    r"levier stratégique|point d['’]attaque|bon réflexe|traduction opérationnelle|"
    r"n['’]est pas un automatisme|mérite une vigilance|"
    r"chiffrage doit rester net|cohérents? et traçables?|"
    r"traçables? et cohérents?|exigence simple|"
    r"expose (?:l['’]employeur|le salarié)(?=[.!])|"
    r"plus qu['’]un simple|logique posée par le texte|"
    r"optimis(?:er|ation)|stratégique)\b",
    re.IGNORECASE,
)
_ARTICLE_CITATION_RE = re.compile(
    r"\bart(?:icle)?s?\.?\s+((?:[A-Z]\.?\s*)?\d+(?:-\d+)*)",
    re.IGNORECASE,
)
_DIRECT_CODE_CITATION_RE = re.compile(r"\b[LRD]\.?\s*\d+(?:-\d+)+\b", re.IGNORECASE)
_POURVOI_CITATION_RE = re.compile(r"\b\d{2}-\d{2}\.\d{3}\b")
_JURISPRUDENCE_SOURCE_TYPES = {
    "arret_cour_cassation",
    "arret_cour_appel",
    "arret_conseil_etat",
    "decision_conseil_constitutionnel",
}
_CODE_REFERENCE_LABELS = {
    "code_travail": "C. trav.",
    "code_travail_reglementaire": "C. trav.",
    "code_civil": "C. civ.",
    "code_civil_reglementaire": "C. civ.",
    "code_securite_sociale": "CSS",
    "code_securite_sociale_reglementaire": "CSS",
    "code_procedures_civiles_execution": "CPCE",
}
_FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


class LinkedinGenerateRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    topic: str = Field(..., min_length=3, max_length=5000)


class LinkedinGenerateResponse(BaseModel):
    post: str
    character_count: int
    sources: list[dict]
    rag_trace: dict
    cost_usd: float
    duration_ms: int


def _normalize_stable_reference(reference: str) -> str:
    return re.sub(r"[^a-z0-9]", "", reference.casefold())


def _select_linkedin_editorial_results(
    results: list[SearchResult],
    *,
    max_documents: int = 5,
) -> list[SearchResult]:
    """Resserre le contexte sans changer les passages issus du RAG commun."""

    grouped: dict[str, list[SearchResult]] = {}
    representatives: list[SearchResult] = []
    for result in results:
        document_id = result.document_id
        if document_id not in grouped:
            grouped[document_id] = []
            representatives.append(result)
        grouped[document_id].append(result)

    written_law = [
        result
        for result in representatives
        if result.source_type not in _JURISPRUDENCE_SOURCE_TYPES
    ]
    jurisprudence = [
        result for result in representatives if result.source_type in _JURISPRUDENCE_SOURCE_TYPES
    ]

    selected_ids: list[str] = []
    for result in written_law[:3] + jurisprudence[:2] + representatives:
        if result.document_id not in selected_ids:
            selected_ids.append(result.document_id)
        if len(selected_ids) == max_documents:
            break

    return [chunk for document_id in selected_ids for chunk in grouped[document_id]]


def _stable_references_in_post(post: str) -> set[str]:
    references = {
        _normalize_stable_reference(match.group(1)) for match in _ARTICLE_CITATION_RE.finditer(post)
    }
    references.update(
        _normalize_stable_reference(match.group(0))
        for match in _DIRECT_CODE_CITATION_RE.finditer(post)
    )
    references.update(
        _normalize_stable_reference(match.group(0)) for match in _POURVOI_CITATION_RE.finditer(post)
    )
    return {reference for reference in references if reference}


def _source_stable_references(sources: list) -> set[str]:
    references: set[str] = set()
    for source in sources:
        references.update(
            _normalize_stable_reference(reference)
            for reference in (source.article_nums or [])
            if reference
        )
        if source.numero_pourvoi:
            references.add(_normalize_stable_reference(source.numero_pourvoi))
    return references


def _linkedin_draft_issues(post: str, sources: list | None = None) -> list[str]:
    """Retourne les violations qui nécessitent une nouvelle rédaction."""

    cleaned = post.strip()
    word_count = len(_WORD_RE.findall(cleaned))
    issues: list[str] = []
    if not cleaned:
        issues.append("le corps est vide")
    if post != cleaned:
        issues.append("le corps contient des espaces ou lignes vides avant ou après le post")
    if len(cleaned) > _LINKEDIN_BODY_MAX_CHARS:
        issues.append(f"le corps dépasse {_LINKEDIN_BODY_MAX_CHARS} caractères")
    if not _LINKEDIN_MIN_WORDS <= word_count <= _LINKEDIN_MAX_WORDS:
        issues.append(
            f"le corps contient {word_count} mots au lieu de "
            f"{_LINKEDIN_MIN_WORDS} à {_LINKEDIN_MAX_WORDS}"
        )
    if _HASHTAG_RE.search(cleaned):
        issues.append("des hashtags sont présents")
    if _EMOJI_RE.search(cleaned):
        issues.append("des emojis sont présents")
    if _MARKDOWN_RE.search(cleaned):
        issues.append("des marqueurs Markdown sont présents")
    bloated_terms = sorted({match.casefold() for match in _STYLE_BLOAT_RE.findall(cleaned)})
    if bloated_terms:
        issues.append(
            "des superlatifs, intensificateurs ou adverbes inutiles sont présents : "
            + ", ".join(bloated_terms)
        )
    if _EDITORIAL_AUTOMATISM_RE.search(cleaned):
        issues.append("un automatisme rhétorique introduit artificiellement un paragraphe")
    if _META_DISCOURSE_RE.search(cleaned):
        issues.append("une formule de méta-discours reformule ou annonce le contenu")
    promotional_wording = sorted(
        {match.casefold() for match in _PROMOTIONAL_WORDING_RE.findall(cleaned)}
    )
    if promotional_wording:
        issues.append(
            "des formulations abstraites ou promotionnelles sont présentes : "
            + ", ".join(promotional_wording)
        )
    question_count = cleaned.count("?")
    _body, cta_separator, _cta = cleaned.rpartition("\n\n")
    if question_count != 1 or not cleaned.endswith("?") or not cta_separator:
        issues.append(
            "le post doit finir par une seule question ouverte et précise, isolée dans "
            "son propre paragraphe, en guise de CTA"
        )
    elif _GENERIC_CTA_RE.search(cleaned):
        issues.append("le CTA final est générique et n'est pas lié au sujet")
    if _SUBJECT_VERB_INVERSION_RE.search(cleaned):
        issues.append(
            "une inversion sujet-verbe est présente ; toutes les questions doivent "
            "garder l'ordre sujet-verbe"
        )
    if "références juridiques :" in cleaned.casefold():
        issues.append("la ligne de références réservée au serveur a été générée")
    if sources is not None:
        cited_sources = _sources_cited_in_post(cleaned, sources)
        if not cited_sources:
            issues.append("aucune source contrôlée n'est citée dans le corps")
        elif len(cited_sources) > _LINKEDIN_MAX_REFERENCES:
            issues.append(
                f"le corps mobilise plus de {_LINKEDIN_MAX_REFERENCES} sources ; "
                "conserve uniquement les fondements qui changent la pratique"
            )
        unsupported = sorted(
            _stable_references_in_post(cleaned) - _source_stable_references(sources)
        )
        if unsupported:
            issues.append(
                "des références absentes des documents sont citées : " + ", ".join(unsupported)
            )
        first_two_paragraphs = "\n\n".join(cleaned.split("\n\n")[:2])
        if sources and not _sources_cited_in_post(first_two_paragraphs, sources[:1]):
            primary_reference = _canonical_source_reference(sources[0])
            issues.append(
                "la règle portée par la source prioritaire doit apparaître dans les "
                f"deux premiers paragraphes : {primary_reference}"
            )
    return issues


def _canonical_article(reference: str) -> str:
    compact = re.sub(r"\s+", "", reference.strip())
    return re.sub(r"^([A-Z]+)\.?(?=\d)", r"\1.", compact)


def _format_decision_date(value: str | None) -> str:
    if not value:
        return ""
    for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(value, date_format)
            return f"{parsed.day} {_FRENCH_MONTHS[parsed.month - 1]} {parsed.year}"
        except ValueError:
            continue
    return value.strip()


def _court_reference_label(source) -> str:
    if source.source_type == "arret_cour_cassation":
        chamber = (source.chambre or "").casefold()
        if "social" in chamber:
            return "Cass. soc."
        if "crimin" in chamber:
            return "Cass. crim."
        if "commercial" in chamber:
            return "Cass. com."
        civil_match = re.search(r"(?:civile?|civ\.?)[^1-3]*([1-3])", chamber)
        if civil_match:
            return f"Cass. {civil_match.group(1)}e civ."
        return "Cass."
    if source.source_type == "arret_conseil_etat":
        return "CE"
    if source.source_type == "decision_conseil_constitutionnel":
        return "Cons. const."
    if source.source_type == "arret_cour_appel":
        return "CA"
    return (source.juridiction or source.source_type_label or "Décision").strip()


def _canonical_source_reference(source, *, cited_post: str | None = None) -> str:
    if source.article_nums:
        label = _CODE_REFERENCE_LABELS.get(source.source_type)
        if not label:
            label = re.sub(r"\s*[—-]\s*Partie\s+.*$", "", source.document_name).strip()
        article_nums = source.article_nums
        if cited_post is not None:
            normalized_post = _normalize_stable_reference(cited_post)
            article_nums = [
                article
                for article in article_nums
                if _normalize_stable_reference(article) in normalized_post
            ]
        articles = [_canonical_article(article) for article in article_nums[:3]]
        if not articles:
            return ""
        article_text = " et ".join(articles)
        return f"{label}, art. {article_text}"

    if source.numero_pourvoi:
        parts = [_court_reference_label(source)]
        decision_date = _format_decision_date(source.date_decision)
        if decision_date:
            parts.append(decision_date)
        parts.append(f"n° {source.numero_pourvoi}")
        return ", ".join(parts)

    document_name = " ".join(source.document_name.split())
    if len(document_name) > 100:
        document_name = document_name[:99].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return document_name


def _build_reference_line(sources: list, *, cited_post: str | None = None) -> str:
    """Construit une ligne canonique sans recopier les titres documentaires."""

    prefix = "Références juridiques : "
    references: list[str] = []
    for source in sources:
        reference = _canonical_source_reference(source, cited_post=cited_post).strip()
        if not reference or reference.casefold() in {
            existing.casefold() for existing in references
        }:
            continue
        candidate = prefix + " ; ".join([*references, reference])
        if len(candidate) > _REFERENCE_LINE_MAX_CHARS:
            break
        references.append(reference)
        if len(references) == _LINKEDIN_MAX_REFERENCES:
            break
    return prefix + " ; ".join(references) if references else ""


def _sources_cited_in_post(post: str, sources: list) -> list:
    """Évite d'ajouter en bibliographie une source que le corps ne mobilise pas."""

    normalized_post = _normalize_stable_reference(post)
    cited = []
    for source in sources:
        stable_refs = list(source.article_nums or [])
        if source.numero_pourvoi:
            stable_refs.append(source.numero_pourvoi)
        if not stable_refs:
            stable_refs.append(source.document_name)
        if any(ref and _normalize_stable_reference(ref) in normalized_post for ref in stable_refs):
            cited.append(source)
    return cited


def _append_references(post: str, sources: list) -> str:
    reference_line = _build_reference_line(
        _sources_cited_in_post(post, sources),
        cited_post=post,
    )
    if not reference_line:
        raise ValueError("linkedin_post_without_cited_reference")

    # Le corps accepté est conservé octet pour octet. La ligne issue des
    # métadonnées est seulement insérée avant le paragraphe CTA.
    body, separator, cta = post.rpartition("\n\n")
    if not separator or not cta.endswith("?"):
        raise ValueError("linkedin_post_without_isolated_cta")
    final_post = f"{body}\n\n{reference_line}\n\n{cta}"
    if len(final_post) > _LINKEDIN_MAX_CHARS:
        raise ValueError("linkedin_post_exceeds_platform_limit")
    return final_post


async def _draft_post(
    agent: RAGAgent,
    topic: str,
    results: list,
    *,
    reformulated: str,
    low_confidence: bool,
    revision: bool = False,
) -> str:
    chunks: list[str] = []
    stream = agent.stream_generate(
        topic,
        results,
        org_context=None,
        history=None,
        low_confidence=low_confidence,
        condensed_query=reformulated,
        answer_format=None,
        generation_mode="linkedin_post",
        linkedin_revision=revision,
    )
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(
                    anext(stream),
                    timeout=RAG_TIMEOUT_STREAM_IDLE,
                )
            except StopAsyncIteration:
                break
            chunks.append(chunk)
    finally:
        await stream.aclose()
    return "".join(chunks)


async def _draft_post_with_empty_retry(
    agent: RAGAgent,
    topic: str,
    results: list,
    *,
    reformulated: str,
    low_confidence: bool,
) -> tuple[str, int]:
    """Retente une fois une génération initiale vide, sans relancer le RAG."""

    empty_retry_count = 0
    while True:
        post = await _draft_post(
            agent,
            topic,
            results,
            reformulated=reformulated,
            low_confidence=low_confidence,
        )
        if post or empty_retry_count >= _LINKEDIN_MAX_EMPTY_RETRIES:
            return post, empty_retry_count
        empty_retry_count += 1
        logger.warning("LinkedIn generation returned an empty body; retrying with the same sources")


@router.post("/generate", response_model=LinkedinGenerateResponse)
@limiter.limit("10/minute")
async def generate_linkedin_post(
    body: LinkedinGenerateRequest,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> LinkedinGenerateResponse:
    """Recherche dans le corpus commun puis rédige un post LinkedIn contrôlé."""

    topic = body.topic.strip()
    run_id = uuid.uuid4()
    started_at = time.perf_counter()
    agent = RAGAgent()

    try:
        results, reformulated, rag_trace = await asyncio.wait_for(
            prepare_rag_context(
                agent,
                query=topic,
                organisation_id=_COMMON_CORPUS_ORG_ID,
                org_context=None,
                history=None,
                cited_sources=None,
                org_idcc_list=None,
                user_id=None,
                context_id=str(run_id),
                is_replay=True,
            ),
            timeout=RAG_TIMEOUT_CONTEXT,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="La recherche documentaire a expiré. Veuillez réessayer.",
        ) from exc

    if reformulated == _OUT_OF_SCOPE_MARKER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le sujet doit relever du droit social ou des ressources humaines.",
        )
    if not results:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucune source suffisamment pertinente n'a été trouvée pour ce sujet.",
        )

    editorial_results = _select_linkedin_editorial_results(results)
    formatted_sources = agent.format_sources(editorial_results)
    rag_trace.search_plan_usage["linkedin_editorial_documents"] = len(formatted_sources)

    try:
        post, empty_retry_count = await _draft_post_with_empty_retry(
            agent,
            topic,
            editorial_results,
            reformulated=reformulated,
            low_confidence=rag_trace.low_confidence,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="La rédaction du post a expiré. Veuillez réessayer.",
        ) from exc
    rag_trace.search_plan_usage["linkedin_empty_retry_count"] = empty_retry_count
    if not post:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "La rédaction n'a produit aucun texte après une nouvelle tentative. "
                "Veuillez réessayer."
            ),
        )

    # Révisions LLM bornées, avec les mêmes sources et sans relancer le RAG.
    # Le serveur ne réécrit jamais le corps lui-même.
    issues = _linkedin_draft_issues(post, formatted_sources)
    revision_count = 0
    while issues and revision_count < _LINKEDIN_MAX_REVISIONS:
        revision_count += 1
        revision_request = (
            f"Sujet original : {topic}\n\n"
            "Réécris intégralement le brouillon ci-dessous. Corrige tous les "
            "défauts détectés sans ajouter de fait ni de référence :\n- "
            + "\n- ".join(issues)
            + f"\n\nBrouillon à remplacer :\n{post}"
        )
        try:
            post = await _draft_post(
                agent,
                revision_request,
                editorial_results,
                reformulated=reformulated,
                low_confidence=rag_trace.low_confidence,
                revision=True,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="La révision du post a expiré. Veuillez réessayer.",
            ) from exc
        issues = _linkedin_draft_issues(post, formatted_sources)

    rag_trace.search_plan_usage["linkedin_revision_count"] = revision_count
    remaining_issues = issues
    if remaining_issues:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Le brouillon généré ne respecte pas encore le format LinkedIn. Veuillez réessayer."
            ),
        )

    try:
        post = _append_references(post, formatted_sources)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Le post ou ses références dépassent le format LinkedIn. Veuillez réessayer.",
        ) from exc
    sources = [dataclasses.asdict(source) for source in formatted_sources]
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    rag_trace.perf_ms["total"] = float(duration_ms)

    # Les écritures de coût sont asynchrones ; on les vide avant de calculer le
    # total de cette génération admin, sans jamais l'attribuer à un client.
    await cost_tracker.flush()
    cost_result = await db.execute(
        select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
            ApiUsageLog.context_id == run_id,
            ApiUsageLog.is_replay.is_(True),
        )
    )

    return LinkedinGenerateResponse(
        post=post,
        character_count=len(post),
        sources=sources,
        rag_trace=rag_trace.to_dict(),
        cost_usd=float(cost_result.scalar() or 0.0),
        duration_ms=duration_ms,
    )
