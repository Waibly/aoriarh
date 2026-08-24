"""Génération de posts LinkedIn sourcés pour l'équipe AORIA RH."""

from __future__ import annotations

import asyncio
import dataclasses
import re
import time
import uuid

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
from app.services.cost_tracker import cost_tracker

router = APIRouter()

_COMMON_CORPUS_ORG_ID = "00000000-0000-0000-0000-000000000000"
_LINKEDIN_MAX_CHARS = 3000
_LINKEDIN_BODY_MAX_CHARS = 2500
_LINKEDIN_MIN_WORDS = 200
_LINKEDIN_MAX_WORDS = 300
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
    r"globalement|finalement|ensuite|enfin|aussi|d['’]abord|ultime|"
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


def _sanitize_linkedin_post(post: str) -> str:
    """Supprime uniquement les marqueurs éditoriaux interdits, sans réécrire le fond."""

    cleaned = post.strip()
    cleaned = re.sub(r"^```(?:text)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*+]\s+", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = _HASHTAG_RE.sub("", cleaned)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _linkedin_draft_issues(post: str) -> list[str]:
    """Retourne les violations qui nécessitent une nouvelle rédaction."""

    cleaned = post.strip()
    word_count = len(_WORD_RE.findall(_sanitize_linkedin_post(cleaned)))
    issues: list[str] = []
    if not cleaned:
        issues.append("le corps est vide")
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
    question_count = cleaned.count("?")
    if question_count != 1 or not cleaned.endswith("?"):
        issues.append(
            "le post doit finir par une seule question ouverte et précise en guise de CTA"
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
    return issues


def _fit_linkedin_limit(post: str, limit: int = _LINKEDIN_MAX_CHARS) -> str:
    """Dernier garde-fou déterministe si le modèle dépasse encore la limite."""

    cleaned = _sanitize_linkedin_post(post)
    if len(cleaned) <= limit:
        return cleaned

    window = cleaned[: limit + 1]
    candidates = [
        window.rfind("\n\n", 0, limit),
        window.rfind(". ", 0, limit),
        window.rfind("? ", 0, limit),
        window.rfind("! ", 0, limit),
    ]
    cut = max(candidates)
    if cut < int(limit * 0.7):
        cut = window.rfind(" ", 0, limit - 1)
    if cut <= 0:
        cut = limit - 1
    return cleaned[:cut].rstrip(" .,;:") + "…"


def _build_reference_line(sources: list) -> str:
    """Construit des références publiques depuis les métadonnées contrôlées."""

    references: list[str] = []
    for source in sources:
        if source.article_nums:
            articles = ", ".join(f"art. {article}" for article in source.article_nums[:3])
            reference = f"{source.document_name}, {articles}"
        elif source.numero_pourvoi:
            decision_date = f", {source.date_decision}" if source.date_decision else ""
            reference = f"{source.document_name}{decision_date}, n° {source.numero_pourvoi}"
        else:
            reference = source.document_name
        reference = reference.strip()
        if len(reference) > 140:
            reference = reference[:139].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
        if reference and reference not in references:
            references.append(reference)
        if len(references) == 3:
            break
    return "Références juridiques : " + " ; ".join(references) if references else ""


def _sources_cited_in_post(post: str, sources: list) -> list:
    """Évite d'ajouter en bibliographie une source que le corps ne mobilise pas."""

    normalized_post = re.sub(r"[^a-z0-9]", "", post.casefold())
    cited = []
    for source in sources:
        stable_refs = list(source.article_nums or [])
        if source.numero_pourvoi:
            stable_refs.append(source.numero_pourvoi)
        if not stable_refs:
            stable_refs.append(source.document_name)
        if any(
            ref and re.sub(r"[^a-z0-9]", "", ref.casefold()) in normalized_post
            for ref in stable_refs
        ):
            cited.append(source)
    return cited or sources[:1]


def _append_references(post: str, sources: list) -> str:
    reference_line = _build_reference_line(_sources_cited_in_post(post, sources))
    if not reference_line:
        return _fit_linkedin_limit(post)

    # Le CTA reste la dernière phrase visible. Les références contrôlées sont
    # insérées juste avant son paragraphe au lieu de repousser l'appel à l'échange.
    body, separator, cta = post.rstrip().rpartition("\n\n")
    if separator and cta.endswith("?"):
        body_limit = _LINKEDIN_MAX_CHARS - len(reference_line) - len(cta) - 4
        fitted_body = _fit_linkedin_limit(body, body_limit)
        return f"{fitted_body}\n\n{reference_line}\n\n{cta}"

    body_limit = _LINKEDIN_MAX_CHARS - len(reference_line) - 2
    return f"{_fit_linkedin_limit(post, body_limit)}\n\n{reference_line}"


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
    return "".join(chunks).strip()


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

    try:
        post = await _draft_post(
            agent,
            topic,
            results,
            reformulated=reformulated,
            low_confidence=rag_trace.low_confidence,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="La rédaction du post a expiré. Veuillez réessayer.",
        ) from exc
    if not post:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La rédaction du post n'a pas pu aboutir. Veuillez réessayer.",
        )

    # Une seule révision maximum, avec les mêmes sources et sans relancer le RAG.
    issues = _linkedin_draft_issues(post)
    if issues:
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
                results,
                reformulated=reformulated,
                low_confidence=rag_trace.low_confidence,
                revision=True,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="La révision du post a expiré. Veuillez réessayer.",
            ) from exc

    post = _sanitize_linkedin_post(post)
    remaining_issues = _linkedin_draft_issues(post)
    if remaining_issues:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Le brouillon généré ne respecte pas encore le format LinkedIn. Veuillez réessayer."
            ),
        )

    formatted_sources = agent.format_sources(results)
    post = _append_references(post, formatted_sources)
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
