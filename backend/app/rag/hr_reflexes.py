"""HR reflexes: Code articles a practitioner checks whenever a situation appears.

Some follow-ups are expected by any HR reader but never look like the question.
Revue du 24/11/2026 :
- « la salariée ne nous a pas fourni sa prolongation d'arrêt » : la recherche
  restait sur l'arrêt maladie ; la présomption de démission pour abandon de
  poste (L1237-1-1, R1237-13) n'a jamais été lue ;
- « salarié en arrêt depuis plus de 7 ans » : rien sur les congés payés acquis
  pendant l'arrêt et leur report (loi du 22 avril 2024).

Each reflex is a situation recognised in the question and a short list of Code
articles. Their passages are appended to the selected sources (never replace
or re-score them); the answer model decides whether they apply. The table is
meant to be extended by the HR expert, one situation at a time.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, replace

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.rag.legal_references import norm
from app.rag.qdrant_store import COLLECTION_NAME

logger = logging.getLogger(__name__)

MAX_REFLEX_PASSAGES = 4
_CODE_TYPES = ["code_travail", "code_travail_reglementaire"]


@dataclass(frozen=True)
class Reflex:
    name: str
    # Every pattern must match the (accent-free, lowercase) question.
    patterns: tuple[re.Pattern, ...]
    articles: tuple[str, ...]


_ABSENCE = re.compile(r"\b(arret|absence|absente?|absent)s?\b")

REFLEXES: tuple[Reflex, ...] = (
    Reflex(
        name="absence_non_justifiee",
        patterns=(
            _ABSENCE,
            re.compile(
                r"pas (?:\w+ ){0,3}(?:fourni|envoye|transmi|recu|justifie|donne de nouvelles)"
                r"|sans (?:justificatif|justification|nouvelles)|injustifie|injoignable"
                r"|ne repond|abandon de poste|ne (?:se )?presente plus|pas revenue?|pas repris"
            ),
        ),
        articles=("L1237-1-1", "R1237-13"),
    ),
    Reflex(
        name="conges_pendant_arret_long",
        patterns=(
            re.compile(r"\b(arret|maladie|absence|absente?)\b"),
            re.compile(
                r"depuis (?:plus d.?\s*)?\d+\s*(?:ans?|annees?|mois)|plusieurs (?:annees|mois)"
                r"|longue (?:maladie|duree)|arret long|invalidite"
            ),
        ),
        articles=("L3141-5", "L3141-5-1", "L3141-19-1", "L3141-19-2"),
    ),
)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[’']", "'", text.lower())


def matching_reflexes(*texts: str) -> list[Reflex]:
    """Reflexes whose patterns all match one of the given formulations."""
    folded = [_fold(t) for t in texts if t]
    return [r for r in REFLEXES if any(all(p.search(t) for p in r.patterns) for t in folded)]


def _fetch_articles(qdrant, articles: list[str]):
    points, _ = qdrant.scroll(
        COLLECTION_NAME,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="article_nums", match=MatchAny(any=articles)),
                FieldCondition(key="organisation_id", match=MatchValue(value="common")),
                FieldCondition(key="source_type", match=MatchAny(any=_CODE_TYPES)),
            ]
        ),
        limit=len(articles) * 4,
        with_payload=True,
        with_vectors=False,
    )
    return [p.payload or {} for p in points]


async def extend_reflex_context(baseline, qdrant, *, texts, diagnostics=None):
    """Append the reflex articles of the situations recognised in ``texts``."""
    from app.rag.parent_expansion import _payload_to_result

    reflexes = matching_reflexes(*texts)
    info = {"status": "hr_reflexes", "reflexes": [r.name for r in reflexes], "added_passages": []}
    if diagnostics is not None:
        diagnostics.append(info)
    if not reflexes:
        return baseline
    started = time.perf_counter()
    wanted = list(dict.fromkeys(a for r in reflexes for a in r.articles))
    present = {norm(a) for r in baseline for a in r.article_nums or []}
    missing = [a for a in wanted if norm(a) not in present]
    if not missing:
        info["reason"] = "already_present"
        return baseline
    try:
        payloads = await asyncio.to_thread(_fetch_articles, qdrant, missing)
    except Exception as exc:  # never lose the answer for an optional addition
        logger.warning("[REFLEXES] lookup failed: %s", exc)
        info.update(reason="reflex_lookup_failed", error_type=type(exc).__name__)
        return baseline
    seen = {
        (r.document_id, i) for r in baseline for i in (r.context_chunk_indices or [r.chunk_index])
    }
    order = {norm(a): i for i, a in enumerate(wanted)}
    payloads.sort(
        key=lambda p: min(order.get(norm(a), 99) for a in p.get("article_nums") or ["?"])
    )
    additions = []
    for payload in payloads:
        key = (payload.get("document_id", ""), int(payload.get("chunk_index", 0)))
        if key in seen or len(additions) >= MAX_REFLEX_PASSAGES:
            continue
        seen.add(key)
        group = replace(_payload_to_result(payload), context_chunk_indices=[key[1]])
        additions.append(group)
        info["added_passages"].append(
            {
                "document_id": key[0],
                "articles": group.article_nums,
                "chunk_indices": [key[1]],
                "selection_reason": "hr_reflex",
            }
        )
    info.update(added_groups=len(additions), seconds=time.perf_counter() - started)
    return [*baseline, *additions]
