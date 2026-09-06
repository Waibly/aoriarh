"""Bounded documentary context built from intact indexed passages.

Rank all candidates, select distinct parent groups, fetch neighboring passages
with access control and bounded pagination, and retain the best ranked passage.
No content-based rewriting, ranking rescue or replacement on transport failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import replace

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    Range,
)

from app.rag.access_filter import build_org_access_filter
from app.rag.article_reference import normalize_article_reference
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.search import SearchResult
from app.rag.source_intent import CODE_SOURCE_LABELS

logger = logging.getLogger(__name__)


class RetrievalError(RuntimeError):
    """A requested search could not execute; not an empty search result."""


# --- Tunables -----------------------------------------------------------------

# Max chunks fetched per parent group (cap on Qdrant scroll cost).
MAX_CHUNKS_PER_GROUP = 30
# Max characters per group. Whole passages only; no text slicing.
MAX_CHARS_PER_GROUP = 9000
# Max parent groups kept after expansion (token budget).
MAX_PARENT_GROUPS = 10
# Max chunks injected via identifier boost.
MAX_IDENTIFIER_CHUNKS = 30

# --- Identifier patterns ------------------------------------------------------

# Numéro de pourvoi : "22-18.875", "22-18875", "n° W 22-18.875"
_PATTERN_NUM_POURVOI = re.compile(r"\b(\d{2})[-\s](\d{2})[\.\s]?(\d{3})\b")

# Article de code : "L4121-1", "L. 4121-1", "art. L.4121-1", "R1234-2", etc.
_PATTERN_ARTICLE_CODE = re.compile(
    r"\b([LRDA])\.?\s*(\d{1,4})([-‑–]\d+(?:[-‑–]\d+)*)\b",
    re.IGNORECASE,
)
_PATTERN_ARTICLE_NUMERIC = re.compile(
    r"\b(?:article|art\.)\s+(\d+(?:[-‑–.]\d+)*)\b",
    re.IGNORECASE,
)


def _article_mentions(query: str) -> list[tuple[int, int, str]]:
    matches = [
        (m.start(), m.end(), normalize_article_reference("".join(m.groups())))
        for m in _PATTERN_ARTICLE_CODE.finditer(query)
    ]
    matches.extend(
        (m.start(), m.end(), m.group(1).replace("‑", "-").replace("–", "-"))
        for m in _PATTERN_ARTICLE_NUMERIC.finditer(query)
    )
    return sorted(matches)


def article_lookup_keys(article: str) -> list[str]:
    """Also match the prefixed spellings emitted by historical ingestion."""
    keys = [article]
    if re.fullmatch(r"[LRDA]\d+(?:-\d+)+", article):
        keys.extend([article[0] + "." + article[1:], article[0] + ". " + article[1:]])
    return keys


def reference_source_types(query: str) -> dict[str, list[str]]:
    """Associate each explicit article with an adjacent named Code, if known.

    A following Code applies to a preceding list of articles. A preceding Code
    is reused only within the same clause. Ambiguous references stay unscoped.
    """
    codes = sorted(
        (m.start(), m.end(), types)
        for label, types in CODE_SOURCE_LABELS.items()
        for m in re.finditer(label, query, re.I)
    )
    result: dict[str, list[str]] = {}
    for start, end, article in _article_mentions(query):
        after = next((c for c in codes if c[0] >= end), None)
        before = next((c for c in reversed(codes) if c[1] <= start), None)
        chosen = None
        if after and not re.search(r"[;!?\n]|\bet\s+(?:le|du)\s*$", query[end : after[0]], re.I):
            chosen = after
        elif before and not re.search(r"[;!?\n]", query[before[1] : start]):
            chosen = before
        if chosen:
            result.setdefault(article, [])
            result[article] = list(dict.fromkeys([*result[article], *chosen[2]]))
    return result


# Source types treated as "full document = parent"
_JURISPRUDENCE_SOURCE_TYPES = {
    "arret_cour_cassation",
    "arret_conseil_etat",
    "arret_cour_appel",
    "arret_conseil_constitutionnel",
    "jurisprudence",
}


# --- Identifier detection -----------------------------------------------------


def detect_identifiers(query: str) -> dict[str, list[str]]:
    """Find document identifiers (pourvois, articles) in the query.

    Returns a dict {"numero_pourvoi": [...], "article_nums": [...]}.
    Each list may be empty.
    """
    pourvois: list[str] = []
    seen_p: set[str] = set()
    for m in _PATTERN_NUM_POURVOI.finditer(query):
        canonical = f"{m.group(1)}-{m.group(2)}.{m.group(3)}"
        if canonical not in seen_p:
            seen_p.add(canonical)
            pourvois.append(canonical)

    articles: list[str] = []
    seen_a: set[str] = set()
    for _start, _end, canonical in _article_mentions(query):
        if canonical not in seen_a:
            seen_a.add(canonical)
            articles.append(canonical)

    return {"numero_pourvoi": pourvois, "article_nums": articles}


# --- Identifier-based retrieval boost -----------------------------------------


_build_org_access_filter = build_org_access_filter


async def fetch_by_identifiers(
    qdrant,
    identifiers: dict[str, list[str]],
    organisation_id: str | None,
    org_idcc_list: list[str] | None = None,
    reference_query: str | None = None,
    source_type_filter: list[str] | None = None,
    excluded_source_types: list[str] | None = None,
    diagnostics: list[dict] | None = None,
    article_source_filters: dict[str, list[str]] | None = None,
) -> list[SearchResult]:
    """Fetch chunks matching identifiers via Qdrant scroll, respecting org access.

    Le client Qdrant est synchrone : chaque scroll part dans un thread
    (asyncio.to_thread) pour ne pas bloquer l'event loop, et les scrolls
    (un par identifiant) s'exécutent en parallèle. L'ordre des résultats
    reste déterministe : pourvois puis articles, dans l'ordre de détection.
    """
    if not any(identifiers.values()):
        return []

    org_filter = _build_org_access_filter(organisation_id, org_idcc_list)

    def _scroll(extra_must: list) -> list[SearchResult]:
        diagnostic = {"kind": "reference", "status": "running", "candidate_chunks": 0}
        if diagnostics is not None:
            diagnostics.append(diagnostic)
        must = list(extra_must)
        if org_filter is not None:
            # Nest the org access filter inside `must` so its `should` clauses
            # remain a required disjunction (multi-tenant safety).
            must.append(org_filter)
        if source_type_filter is not None:
            must.append(FieldCondition(key="source_type", match=MatchAny(any=source_type_filter)))
        flt = Filter(
            must=must,
            must_not=[
                FieldCondition(key="source_type", match=MatchAny(any=excluded_source_types)),
            ]
            if excluded_source_types
            else None,
        )
        try:
            pts, _ = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=flt,
                limit=MAX_IDENTIFIER_CHUNKS,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            diagnostic["status"] = "error"
            logger.warning("[BOOST] Identifier scroll failed (%s): %s", extra_must, exc)
            raise RetrievalError("identifier_lookup_failed") from exc
        diagnostic.update(status="ok" if pts else "empty", candidate_chunks=len(pts))
        return [_payload_to_result(p.payload or {}, score=1.0) for p in pts]

    scopes = (
        article_source_filters
        if article_source_filters is not None
        else reference_source_types(reference_query or "")
    )
    conditions: list[list] = [
        [FieldCondition(key="numero_pourvoi", match=MatchValue(value=pourvoi))]
        for pourvoi in identifiers.get("numero_pourvoi", [])
    ] + [
        [FieldCondition(key="article_nums", match=MatchAny(any=article_lookup_keys(article)))]
        + (
            [FieldCondition(key="source_type", match=MatchAny(any=scopes[article]))]
            if article in scopes
            else []
        )
        for article in identifiers.get("article_nums", [])
    ]
    batches = await asyncio.gather(*[asyncio.to_thread(_scroll, cond) for cond in conditions])

    found: list[SearchResult] = []
    seen: set[tuple[str, int]] = set()
    for batch in batches:
        for r in batch:
            key = (r.document_id, r.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            found.append(r)

    if found:
        logger.info(
            "[BOOST] Identifier retrieval: %d chunks for %s",
            len(found),
            identifiers,
        )
    return found


# --- Parent expansion ---------------------------------------------------------


def _payload_to_result(payload: dict, *, score: float = 0.0) -> SearchResult:
    """Build a SearchResult from a Qdrant payload dict."""
    return SearchResult(
        text=payload.get("text", ""),
        doc_name=payload.get("doc_name", ""),
        document_id=payload.get("document_id", ""),
        source_type=payload.get("source_type", ""),
        norme_niveau=int(payload.get("norme_niveau", 9)),
        norme_poids=float(payload.get("norme_poids", 0.5)),
        chunk_index=int(payload.get("chunk_index", 0)),
        score=score,
        juridiction=payload.get("juridiction"),
        chambre=payload.get("chambre"),
        formation=payload.get("formation"),
        numero_pourvoi=payload.get("numero_pourvoi"),
        date_decision=payload.get("date_decision"),
        solution=payload.get("solution"),
        publication=payload.get("publication"),
        content_date=payload.get("content_date"),
        idcc=payload.get("idcc"),
        article_nums=payload.get("article_nums"),
        section_path=payload.get("section_path"),
        instrument_id=payload.get("instrument_id"),
        instrument_title=payload.get("instrument_title"),
        effective_from=payload.get("effective_from"),
        effective_to=payload.get("effective_to"),
        instrument_status=payload.get("instrument_status"),
        organisation_id=payload.get("organisation_id"),
        **{key: payload.get(key) for key in (
            "article_id", "article_title", "article_status",
            "article_effective_from", "article_effective_to",
        )},
    )


def _parent_key_for(r: SearchResult) -> tuple:
    """Return the parent group key for a chunk.

    - Jurisprudence : ("doc", document_id) — full arrêt as one parent.
    - Article-based : ("article", document_id, first_article_num) — one parent
      per article (a chunk that covers articles A and B will be assigned to A;
      this is a simplification but adequate for the typical case).
    - Other         : ("window", document_id, chunk_index) — sliding window.
    """
    src = (r.source_type or "").lower()
    if src in _JURISPRUDENCE_SOURCE_TYPES or src.startswith("arret_"):
        return ("doc", r.document_id)
    if r.article_nums:
        # Article numbers are frequently reused across successive CCN
        # agreements. Include KALITEXT identity to avoid merging two versions.
        return (
            "article",
            r.document_id,
            r.instrument_id or "",
            r.article_nums[0],
        )
    return ("window", r.document_id, r.chunk_index)


class ParentExpansionError(RuntimeError):
    """Technical failure while assembling the source context."""


def deduplicate_article_passages(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate exact versioned passages AFTER access filtering, not documents.

    Never infer equivalence from similar wording, incomplete identities or scores.
    Different fragments of a long article and different ACL scopes remain distinct.
    """
    seen = set()
    output = []
    for r in results:
        if r.article_id and r.instrument_id and r.organisation_id is not None:
            key = (r.organisation_id, r.source_type, r.idcc, r.instrument_id,
                   r.article_id, r.article_effective_from, r.article_effective_to,
                   r.article_status, r.effective_from, r.effective_to,
                   r.instrument_status, r.article_title, r.text)
            if key in seen:
                continue
            seen.add(key)
        output.append(r)
    return output


def _fetch_siblings(qdrant, key: tuple, access_filter=None):
    """Bounded pagination; window constraints are applied by Qdrant itself."""
    kind, doc_id = key[:2]
    must = [FieldCondition(key="document_id", match=MatchValue(value=doc_id))]
    if access_filter is not None:
        must.append(access_filter)
    if kind == "article":
        instrument_id, article = key[2], key[3]
        must.append(FieldCondition(key="article_nums", match=MatchAny(any=[article])))
        if instrument_id:
            must.append(FieldCondition(key="instrument_id", match=MatchValue(value=instrument_id)))
    elif kind == "window":
        last_center = key[3] if len(key) > 3 else key[2]
        must.append(
            FieldCondition(key="chunk_index", range=Range(gte=key[2] - 2, lte=last_center + 2))
        )
    found = []
    offset = None
    seen_offsets = set()
    for page in range(4):
        kwargs = dict(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            limit=MAX_CHUNKS_PER_GROUP,
            with_payload=True,
            with_vectors=False,
        )
        if offset is not None:
            kwargs["offset"] = offset
        points, offset = qdrant.scroll(**kwargs)
        found.extend(_payload_to_result(p.payload or {}) for p in points)
        if offset is None:
            return found, {"pages": page + 1, "fetch_limited": False}
        if str(offset) in seen_offsets:
            raise ParentExpansionError("parent_pagination_not_progressing")
        seen_offsets.add(str(offset))
    return found, {"pages": 4, "fetch_limited": True}


def _merge_group(chunks, best_score, seeds=None):
    """Assemble whole indexed passages; never reconstruct a legal conclusion."""
    ranked_seeds = sorted(seeds or chunks, key=lambda r: r.score, reverse=True)
    if not ranked_seeds:
        raise ParentExpansionError("parent_without_seed")
    best = ranked_seeds[0]
    by_index = {r.chunk_index: r for r in chunks}
    # Original ranked passages win over the secondary fetch.
    by_index.update({r.chunk_index: r for r in reversed(ranked_seeds)})
    if len(best.text) > MAX_CHARS_PER_GROUP:
        raise ParentExpansionError("selected_passage_exceeds_context_budget")
    priorities = list(dict.fromkeys(r.chunk_index for r in ranked_seeds))
    priorities += sorted(
        (i for i in by_index if i not in priorities),
        key=lambda i: (abs(i - best.chunk_index), i),
    )
    selected = []
    chars = 0
    for i in priorities:
        cost = len(by_index[i].text) + (2 if selected else 0)
        if chars + cost <= MAX_CHARS_PER_GROUP:
            selected.append(i)
            chars += cost
    ordered = [by_index[i] for i in sorted(selected)]
    articles = list(dict.fromkeys(a for r in ordered for a in (r.article_nums or [])))
    return replace(
        best,
        text="\n\n".join(r.text for r in ordered),
        score=best_score,
        seed_text=best.text,
        article_nums=articles or best.article_nums,
        context_chunk_indices=[r.chunk_index for r in ordered],
    )


async def expand_to_parents(
    results: list[SearchResult],
    qdrant,
    *,
    organisation_id: str | None = None,
    org_idcc_list: list[str] | None = None,
    diagnostics: list[dict] | None = None,
) -> list[SearchResult]:
    """Select distinct parent groups by raw rank, then fetch their context.

    Budgets are technical limits, not minimum confidence or source-type quotas.
    Each included passage is copied intact from the index.
    """
    if not results:
        return []
    # Overlapping windows are one parent, not several copies consuming seats.
    results = deduplicate_article_passages(sorted(results, key=lambda r: r.score, reverse=True))
    window_centers = {}
    for r in results:
        if _parent_key_for(r)[0] == "window":
            window_centers.setdefault(r.document_id, set()).add(r.chunk_index)
    window_keys = {}
    for doc, centers in window_centers.items():
        clusters = []
        for center in sorted(centers):
            if clusters and center <= clusters[-1][-1] + 4:
                clusters[-1].append(center)
            else:
                clusters.append([center])
        for cluster in clusters:
            key = ("window", doc, cluster[0], cluster[-1])
            for center in cluster:
                window_keys[(doc, center)] = key
    groups = {}
    for r in sorted(results, key=lambda r: r.score, reverse=True):
        key = window_keys.get((r.document_id, r.chunk_index), _parent_key_for(r))
        groups.setdefault(key, []).append(r)
    selected = list(groups)[:MAX_PARENT_GROUPS]
    if diagnostics is None:
        diagnostics = []
    for key in list(groups)[MAX_PARENT_GROUPS:]:
        diagnostics.append(
            {
                "parent_key": list(key),
                "status": "excluded_group_budget",
                "score": groups[key][0].score,
                "seed_indices": [r.chunk_index for r in groups[key]],
            }
        )
    access = build_org_access_filter(organisation_id, org_idcc_list)
    semaphore = asyncio.Semaphore(4)

    async def fetch(key):
        async with semaphore:
            return await asyncio.to_thread(_fetch_siblings, qdrant, key, access)

    fetched = await asyncio.gather(*(fetch(key) for key in selected), return_exceptions=True)
    expanded = []
    for key, outcome in zip(selected, fetched):
        if isinstance(outcome, BaseException):
            diagnostics.append({"parent_key": list(key), "status": "fetch_error"})
            raise ParentExpansionError("parent_fetch_failed") from outcome
        siblings, info = outcome
        seeds = groups[key]
        merged = _merge_group(siblings, seeds[0].score, seeds=seeds)
        available = {r.chunk_index for r in siblings + seeds}
        included = set(merged.context_chunk_indices or [])
        diagnostics.append(
            {
                "parent_key": list(key),
                "status": "selected",
                **info,
                "seeds_not_refetched": sorted(
                    {r.chunk_index for r in seeds} - {r.chunk_index for r in siblings}
                ),
                "score": merged.score,
                "seed_indices": [r.chunk_index for r in seeds],
                "context_indices": sorted(included),
                "omitted_indices": sorted(available - included),
                "context_chars": len(merged.text),
                "context_sha256": hashlib.sha256(merged.text.encode()).hexdigest(),
            }
        )
        expanded.append(merged)
    return expanded
