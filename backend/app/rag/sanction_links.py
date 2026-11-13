"""Sanctions of a selected Code obligation, found by explicit citation.

A Code article rarely states its own sanction. The fine or the offence sits in
another chapter ("Amendes administratives", "Dispositions pénales"…) and cites
the obligation by number. Those articles talk about sanctions in general, so a
semantic search on the obligation (ex. "DUERP") does not reach them.

From the Code articles already selected (and the articles they cite), this
module adds the sanction-chapter articles that cite them explicitly, plus the
next passage of the same chapter (where amounts often sit, ex. L8115-3).
Additions never replace or re-score the baseline. Only common Code documents
are read; the index of sanction passages is cached per Code family.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import replace

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.rag.legal_references import explicit_reference_scopes, norm, refs
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.source_intent import CODE_SOURCE_LABELS

logger = logging.getLogger(__name__)

SANCTION_SECTION = re.compile(
    r"amendes?\s+administratives?|dispositions\s+p[ée]nales|sanctions?|p[ée]nalit[ée]s"
    r"|infractions",
    re.I,
)
MAX_SANCTION_GROUPS = 3
MAX_CHARS_PER_SANCTION_GROUP = 9000
# Seed articles beyond this many are ignored (a merged section may list many).
MAX_SEED_REFERENCES = 40
CACHE_TTL_SECONDS = 3600
# "L. 3121-18 à L. 3121-25" → every article of the range (bounded).
_MAX_RANGE_SPAN = 30
_RANGE = re.compile(
    r"\b([LRDA])\.?\s*(\d{1,4}(?:[-‑–]\d+)*)[-‑–](\d+)\s+à\s+(?:l['’]article\s+)?"
    r"([LRDA])\.?\s*(\d{1,4}(?:[-‑–]\d+)*)[-‑–](\d+)\b",
    re.I,
)

_FAMILIES: dict[str, tuple[str, ...]] = {}
for _types in CODE_SOURCE_LABELS.values():
    for _type in _types:
        _FAMILIES[_type] = tuple(sorted(_types))

_cache: dict[tuple[str, ...], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def cited_references(text: str) -> set[str]:
    """Explicit article numbers in a text, ranges expanded."""
    explicit, ranged = split_references(text)
    return explicit | ranged


def split_references(text: str) -> tuple[set[str], set[str]]:
    """(articles named in the text, articles only covered by a range)."""
    explicit = refs(text or "")
    found = set()
    for m in _RANGE.finditer(text or ""):
        letter_a, stem_a, first, letter_b, stem_b, last = m.groups()
        if letter_a.upper() != letter_b.upper() or norm(stem_a) != norm(stem_b):
            continue
        start, end = int(first), int(last)
        if start < end <= start + _MAX_RANGE_SPAN:
            found.update(norm(f"{letter_a}{stem_a}-{n}") for n in range(start, end + 1))
    return explicit, found - explicit


def _build_index(qdrant, family: tuple[str, ...]) -> dict:
    """Read every common passage of the family once; keep sanction chapters."""
    # ref -> {passage key: True if named explicitly, False if only in a range}
    by_ref: dict[str, dict[tuple[str, int], bool]] = {}
    passages: dict[tuple[str, int], dict] = {}
    must = [
        FieldCondition(key="source_type", match=MatchAny(any=list(family))),
        FieldCondition(key="organisation_id", match=MatchValue(value="common")),
    ]
    offset, seen_offsets = None, set()
    while True:
        points, offset = qdrant.scroll(
            COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            offset=offset,
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            if not SANCTION_SECTION.search(payload.get("section_path") or ""):
                continue
            key = (payload.get("document_id", ""), int(payload.get("chunk_index", 0)))
            passages[key] = payload
            own = {norm(a) for a in payload.get("article_nums") or []}
            explicit, ranged = split_references(payload.get("text", ""))
            for ref in explicit - own:
                by_ref.setdefault(ref, {})[key] = True
            for ref in ranged - own:
                by_ref.setdefault(ref, {}).setdefault(key, False)
        if offset is None:
            break
        if str(offset) in seen_offsets:
            raise RuntimeError("sanction_index_pagination_not_progressing")
        seen_offsets.add(str(offset))
    return {"by_ref": by_ref, "passages": passages}


def _index_for(qdrant, family: tuple[str, ...]) -> dict:
    with _cache_lock:
        cached = _cache.get(family)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        index = _build_index(qdrant, family)
        _cache[family] = (time.monotonic(), index)
        return index


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _seed_references(group) -> tuple[set[str], set[str]]:
    """(own articles, articles cited within the same Code) of a selected group."""
    own = {norm(a) for a in group.article_nums or []}
    scopes = explicit_reference_scopes(group.text or "", CODE_SOURCE_LABELS)
    cited = {
        ref
        for ref in cited_references(group.text or "") - own
        if not scopes.get(ref) or group.source_type in scopes[ref]
    }
    return own, cited


def _assemble(index: dict, keys: list[tuple[str, int]]):
    """Whole sanction article(s) + the next passage of the same chapter."""
    from app.rag.parent_expansion import _payload_to_result

    passages = index["passages"]
    first = passages[keys[0]]
    doc_id = first.get("document_id", "")
    article = (first.get("article_nums") or [None])[0]
    indices = sorted(
        idx
        for (doc, idx), payload in passages.items()
        if doc == doc_id and article in (payload.get("article_nums") or [])
    ) or sorted(idx for _doc, idx in keys)
    following = (doc_id, indices[-1] + 1)
    if (
        following in passages
        and passages[following].get("section_path") == passages[(doc_id, indices[-1])].get(
            "section_path"
        )
    ):
        indices.append(following[1])
    selected, chars = [], 0
    for idx in indices:
        text = passages[(doc_id, idx)].get("text", "")
        if selected and chars + len(text) > MAX_CHARS_PER_SANCTION_GROUP:
            break
        selected.append(idx)
        chars += len(text)
    chunks = [_payload_to_result(passages[(doc_id, idx)]) for idx in selected]
    return replace(
        chunks[0],
        text="\n\n".join(c.text for c in chunks),
        article_nums=list(dict.fromkeys(a for c in chunks for a in c.article_nums or [])),
        context_chunk_indices=selected,
    )


async def extend_sanction_context(baseline, qdrant, *, diagnostics=None):
    """Append the sanction articles citing the selected Code articles."""
    info = {"status": "sanction_links", "seeds": [], "added_passages": []}
    if diagnostics is not None:
        diagnostics.append(info)
    code_groups = [r for r in baseline if r.source_type in _FAMILIES and r.article_nums]
    if not code_groups:
        info["reason"] = "no_selected_code_article"
        return baseline
    started = time.perf_counter()
    seen = {
        (r.document_id, i) for r in baseline for i in (r.context_chunk_indices or [r.chunk_index])
    }
    present_articles = {norm(a) for r in baseline for a in r.article_nums or []}
    # Score candidates: citing a selected article weighs more than citing an
    # article the selection itself refers to.
    candidates: dict[tuple[str, int], dict] = {}
    try:
        for family in dict.fromkeys(_FAMILIES[r.source_type] for r in code_groups):
            index = await asyncio.to_thread(_index_for, qdrant, family)
            for group in code_groups:
                if _FAMILIES[group.source_type] != family:
                    continue
                own, cited = _seed_references(group)
                info["seeds"].append({"articles": sorted(own), "cited": sorted(cited)})
                weighted = [(ref, 2) for ref in sorted(own)]
                weighted += [(ref, 1) for ref in sorted(cited)][:MAX_SEED_REFERENCES]
                for ref, weight in weighted:
                    for key, named in index["by_ref"].get(ref, {}).items():
                        # A broad range ("L. 4121-1 à L. 4121-5") only counts
                        # for an article selected itself, not for a cited one.
                        if not named and weight < 2:
                            continue
                        entry = candidates.setdefault(
                            key, {"index": index, "score": 0, "refs": set()}
                        )
                        if ref not in entry["refs"]:
                            entry["refs"].add(ref)
                            entry["score"] += weight
    except Exception as exc:  # never lose the answer for an optional addition
        logger.warning("[SANCTIONS] lookup failed: %s", exc)
        info.update(reason="sanction_lookup_failed", error_type=type(exc).__name__)
        return baseline

    ranked = sorted(candidates.items(), key=lambda item: (-item[1]["score"], item[0]))
    additions = []
    for key, entry in ranked:
        if len(additions) >= MAX_SANCTION_GROUPS:
            break
        if key in seen:
            continue
        payload = entry["index"]["passages"][key]
        if {norm(a) for a in payload.get("article_nums") or []} & present_articles:
            continue
        group = _assemble(entry["index"], [key])
        identities = {(group.document_id, i) for i in group.context_chunk_indices or []}
        if identities & seen:
            continue
        seen |= identities
        present_articles |= {norm(a) for a in group.article_nums or []}
        additions.append(group)
        info["added_passages"].append(
            {
                "document_id": group.document_id,
                "articles": group.article_nums,
                "chunk_indices": group.context_chunk_indices,
                "cites": sorted(entry["refs"]),
                "selection_reason": "sanction_of_selected_article",
            }
        )
    info.update(added_groups=len(additions), seconds=time.perf_counter() - started)
    return [*baseline, *additions]
