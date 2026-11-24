"""Exceptions stated right after a selected Code article.

The Code often states a rule, then its exceptions in the next article of the
same section, without citing the rule by number. Cas réel (05/11/2026) :
L1243-8 (indemnité de fin de CDD, 10 %) était retenu, mais pas L1243-10
(« L'indemnité de fin de contrat n'est pas due : … rupture anticipée à
l'initiative du salarié »). Le modèle a donc annoncé l'indemnité sans réserve.

For each Code group of the selection, this module reads the next passages of the
same document and keeps those of the same section whose article opens with an
exception wording. Additions never replace or re-score the baseline.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import replace

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.rag.legal_references import norm
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.source_intent import CODE_SOURCE_LABELS

logger = logging.getLogger(__name__)

MAX_EXCEPTION_GROUPS = 3
# Passages read after the last passage of a selected group.
LOOKAHEAD = 2
# Only the opening of each article is tested: an exception announced there
# qualifies the preceding rule; one buried in a long article does not.
OPENING_CHARS = 220

_CODE_TYPES = {t for types in CODE_SOURCE_LABELS.values() for t in types}
_ARTICLE = re.compile(r"^###\s+Article\s+[^\n]+\n+(.*?)(?=^###\s+Article\s|\Z)", re.M | re.S)
EXCEPTION_OPENING = re.compile(
    r"par\s+d[ée]rogation"
    r"|\btoutefois\b"
    r"|à\s+l['’]exception"
    r"|n['’]est\s+pas\s+(?:due?|dû|applicable)"
    r"|ne\s+sont\s+pas\s+(?:dues|dus|applicables)"
    r"|ne\s+s['’]appliquen?t?\s+pas"
    r"|n['’]ouvrent?\s+pas\s+droit"
    r"|ne\s+donnent?\s+pas\s+lieu",
    re.I,
)


def opens_with_exception(text: str) -> bool:
    """True if one article of the passage opens with an exception wording."""
    bodies = _ARTICLE.findall(text or "") or [text or ""]
    return any(EXCEPTION_OPENING.search(body.strip()[:OPENING_CHARS]) for body in bodies)


def _fetch_following(qdrant, document_id: str, indices: list[int]) -> dict[int, dict]:
    points, _ = qdrant.scroll(
        COLLECTION_NAME,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                FieldCondition(key="organisation_id", match=MatchValue(value="common")),
                FieldCondition(key="chunk_index", match=MatchAny(any=indices)),
            ]
        ),
        limit=len(indices) * 4,
        with_payload=True,
        with_vectors=False,
    )
    return {int((p.payload or {}).get("chunk_index", -1)): p.payload or {} for p in points}


async def extend_exception_context(baseline, qdrant, *, seeds=None, diagnostics=None):
    """Append the exception passages following the selected Code articles.

    ``seeds`` are the groups whose following passages are read (default: every
    Code group of ``baseline``); additions are appended to ``baseline``.
    """
    from app.rag.parent_expansion import _payload_to_result

    info = {"status": "exception_links", "seeds": [], "added_passages": []}
    if diagnostics is not None:
        diagnostics.append(info)
    code_groups = [
        r
        for r in (baseline if seeds is None else seeds)
        if r.source_type in _CODE_TYPES and r.article_nums
    ]
    if not code_groups:
        info["reason"] = "no_selected_code_article"
        return baseline
    started = time.perf_counter()
    seen = {
        (r.document_id, i) for r in baseline for i in (r.context_chunk_indices or [r.chunk_index])
    }
    present_articles = {norm(a) for r in baseline for a in r.article_nums or []}
    # document -> [(last selected index, its section)]
    wanted: dict[str, list[tuple[int, str | None]]] = {}
    for group in code_groups:
        last = max(group.context_chunk_indices or [group.chunk_index])
        wanted.setdefault(group.document_id, []).append((last, group.section_path))
        info["seeds"].append({"articles": group.article_nums, "last_chunk": last})

    async def read(document_id, anchors):
        indices = sorted({a + k for a, _s in anchors for k in range(1, LOOKAHEAD + 1)})
        return await asyncio.to_thread(_fetch_following, qdrant, document_id, indices)

    try:
        fetched = await asyncio.gather(*(read(d, a) for d, a in wanted.items()))
    except Exception as exc:  # never lose the answer for an optional addition
        logger.warning("[EXCEPTIONS] lookup failed: %s", exc)
        info.update(reason="exception_lookup_failed", error_type=type(exc).__name__)
        return baseline

    additions = []
    for (document_id, anchors), passages in zip(wanted.items(), fetched):
        for last, section in sorted(anchors):
            for idx in range(last + 1, last + LOOKAHEAD + 1):
                payload = passages.get(idx)
                # Stop at the end of the section: the next one is another subject.
                if not payload or not section or payload.get("section_path") != section:
                    break
                if (document_id, idx) in seen:
                    continue
                if not opens_with_exception(payload.get("text", "")):
                    continue
                articles = {norm(a) for a in payload.get("article_nums") or []}
                if articles and articles <= present_articles:
                    continue
                if len(additions) >= MAX_EXCEPTION_GROUPS:
                    break
                group = replace(_payload_to_result(payload), context_chunk_indices=[idx])
                seen.add((document_id, idx))
                present_articles |= articles
                additions.append(group)
                info["added_passages"].append(
                    {
                        "document_id": document_id,
                        "articles": group.article_nums,
                        "chunk_indices": [idx],
                        "after_chunk": last,
                        "selection_reason": "exception_following_selected_article",
                    }
                )
    info.update(added_groups=len(additions), seconds=time.perf_counter() - started)
    return [*baseline, *additions]
