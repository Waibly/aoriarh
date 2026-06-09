"""Small-to-big retrieval: expand retrieved chunks to their full parent context.

After hybrid search + reranking returns the top chunks, this module ensures
that the LLM receives the FULL relevant context, not just the chunk that
matched the query embedding. Three strategies depending on document type:

- Jurisprudence (arrêts) : the parent is the full document. All sibling
  chunks of the same arrêt are fetched and merged.
- Article-based docs (Code du travail, CCN, accords) : the parent is the
  full article. All chunks sharing the same article number are fetched.
- Other documents : a sliding window of ±2 chunks around the matched
  chunk_index, so the LLM sees the immediate neighborhood.

In addition, an identifier-detection helper looks for explicit references
in the user query (numéros de pourvoi, articles de code) and pulls the
matching chunks directly via Qdrant filters, bypassing the semantic search
which fails on identifier-only queries (e.g. "que dit l'article L.4121-1").
"""
from __future__ import annotations

import logging
import re
from dataclasses import replace

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
)

from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.search import SearchResult

logger = logging.getLogger(__name__)


def _is_legislation(source_type: str) -> bool:
    """True for "written law" (hierarchy levels 1–5 except jurisprudence)."""
    niveau = DOCUMENT_TYPE_HIERARCHY.get(source_type, {}).get("niveau")
    return isinstance(niveau, int) and niveau <= 5 and niveau != 4

# --- Tunables -----------------------------------------------------------------

# Max chunks fetched per parent group (cap on Qdrant scroll cost).
MAX_CHUNKS_PER_GROUP = 30
# Max characters per merged group sent to the LLM (truncated with ellipsis).
MAX_CHARS_PER_GROUP = 9000
# Max parent groups kept after expansion (token budget).
MAX_PARENT_GROUPS = 10
# Max chunks injected via identifier boost.
MAX_IDENTIFIER_CHUNKS = 30

# --- Identifier patterns ------------------------------------------------------

# Numéro de pourvoi : "22-18.875", "22-18875", "n° W 22-18.875"
_PATTERN_NUM_POURVOI = re.compile(
    r"\b(\d{2})[-\s](\d{2})[\.\s]?(\d{3})\b"
)

# Article de code : "L4121-1", "L. 4121-1", "art. L.4121-1", "R1234-2", etc.
_PATTERN_ARTICLE_CODE = re.compile(
    r"\b([LRDA])\.?\s*(\d{3,4})[-\s]?(\d+)\b",
    re.IGNORECASE,
)

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
    for m in _PATTERN_ARTICLE_CODE.finditer(query):
        prefix = m.group(1).upper()
        canonical = f"{prefix}{m.group(2)}-{m.group(3)}"
        if canonical not in seen_a:
            seen_a.add(canonical)
            articles.append(canonical)

    return {"numero_pourvoi": pourvois, "article_nums": articles}


# --- Identifier-based retrieval boost -----------------------------------------


def _build_org_access_filter(
    organisation_id: str | None,
    org_idcc_list: list[str] | None = None,
) -> Filter | None:
    """Build the same multi-tenant access filter used by HybridSearch.

    Allows: org's own docs + common non-CCN docs + common CCN docs for org's IDCCs.
    Returns None if organisation_id is None (no filter applied — admin context).
    """
    if not organisation_id:
        return None

    should: list = [
        FieldCondition(
            key="organisation_id",
            match=MatchValue(value=organisation_id),
        ),
    ]
    ccn_types = ["convention_collective_nationale", "accord_branche"]
    if org_idcc_list:
        should.append(
            Filter(
                must=[
                    FieldCondition(
                        key="organisation_id",
                        match=MatchValue(value="common"),
                    ),
                ],
                must_not=[
                    FieldCondition(
                        key="source_type",
                        match=MatchAny(any=ccn_types),
                    ),
                ],
            )
        )
        for st in ccn_types:
            should.append(
                Filter(
                    must=[
                        FieldCondition(
                            key="organisation_id",
                            match=MatchValue(value="common"),
                        ),
                        FieldCondition(
                            key="source_type",
                            match=MatchValue(value=st),
                        ),
                        FieldCondition(
                            key="idcc",
                            match=MatchAny(any=org_idcc_list),
                        ),
                    ],
                )
            )
    else:
        # No IDCC installed → exclude ALL CCN/accord_branche docs to avoid
        # leaking content from sectors that don't apply to this org.
        should.append(
            Filter(
                must=[
                    FieldCondition(
                        key="organisation_id",
                        match=MatchValue(value="common"),
                    ),
                ],
                must_not=[
                    FieldCondition(
                        key="source_type",
                        match=MatchAny(any=ccn_types),
                    ),
                ],
            )
        )
    return Filter(should=should)


def fetch_by_identifiers(
    qdrant,
    identifiers: dict[str, list[str]],
    organisation_id: str | None,
    org_idcc_list: list[str] | None = None,
) -> list[SearchResult]:
    """Fetch chunks matching identifiers via Qdrant scroll, respecting org access."""
    if not any(identifiers.values()):
        return []

    org_filter = _build_org_access_filter(organisation_id, org_idcc_list)
    found: list[SearchResult] = []
    seen: set[tuple[str, int]] = set()

    def _scroll(extra_must: list) -> None:
        must = list(extra_must)
        if org_filter is not None:
            # Nest the org access filter inside `must` so its `should` clauses
            # remain a required disjunction (multi-tenant safety).
            must.append(org_filter)
        flt = Filter(must=must)
        try:
            pts, _ = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=flt,
                limit=MAX_IDENTIFIER_CHUNKS,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            logger.warning(
                "[BOOST] Identifier scroll failed (%s): %s", extra_must, exc
            )
            return
        for p in pts:
            r = _payload_to_result(p.payload or {}, score=1.0)
            key = (r.document_id, r.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            found.append(r)

    for pourvoi in identifiers.get("numero_pourvoi", []):
        _scroll([
            FieldCondition(key="numero_pourvoi", match=MatchValue(value=pourvoi))
        ])
    for article in identifiers.get("article_nums", []):
        _scroll([
            FieldCondition(key="article_nums", match=MatchAny(any=[article]))
        ])

    if found:
        logger.info(
            "[BOOST] Identifier retrieval: %d chunks for %s",
            len(found), identifiers,
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
        article_nums=payload.get("article_nums"),
        section_path=payload.get("section_path"),
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
        return ("article", r.document_id, r.article_nums[0])
    return ("window", r.document_id, r.chunk_index)


def _fetch_siblings(qdrant, key: tuple) -> list[SearchResult]:
    """Fetch all sibling chunks belonging to a parent group via Qdrant scroll."""
    kind = key[0]
    try:
        if kind == "doc":
            doc_id = key[1]
            pts, _ = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(must=[
                    FieldCondition(key="document_id", match=MatchValue(value=doc_id))
                ]),
                limit=MAX_CHUNKS_PER_GROUP,
                with_payload=True,
                with_vectors=False,
            )
            return [_payload_to_result(p.payload or {}) for p in pts]

        if kind == "article":
            doc_id, article = key[1], key[2]
            pts, _ = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(must=[
                    FieldCondition(key="document_id", match=MatchValue(value=doc_id)),
                    FieldCondition(key="article_nums", match=MatchAny(any=[article])),
                ]),
                limit=MAX_CHUNKS_PER_GROUP,
                with_payload=True,
                with_vectors=False,
            )
            return [_payload_to_result(p.payload or {}) for p in pts]

        if kind == "window":
            doc_id, center_idx = key[1], key[2]
            pts, _ = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(must=[
                    FieldCondition(key="document_id", match=MatchValue(value=doc_id))
                ]),
                limit=MAX_CHUNKS_PER_GROUP * 4,
                with_payload=True,
                with_vectors=False,
            )
            all_results = [_payload_to_result(p.payload or {}) for p in pts]
            return [c for c in all_results if abs(c.chunk_index - center_idx) <= 2]
    except Exception as exc:
        logger.warning("[EXPAND] Sibling fetch failed for %s: %s", key, exc)
    return []


# --- Jurisprudence-aware merging ---------------------------------------------

# A line that is exactly a section label, e.g. "[Motifs de la décision]".
_SECTION_LINE = re.compile(r"^\[[^\]\n]+\]$")
# Min/max overlap (chars) considered when stitching consecutive chunks.
_MIN_OVERLAP = 20
_MAX_OVERLAP = 600


def _decompose(text: str) -> tuple[str, str | None, str]:
    """Split a stored chunk into (meta_header, section_label, body).

    Jurisprudence chunks are stored as ``"<meta header>\\n[Section]\\n\\n<body>"``.
    The meta header (court + date + pourvoi) is identical on every chunk of the
    same arrêt, so callers strip it to avoid repeating it N times. Returns empty
    meta / None section when that structure is absent (paragraph-fallback
    chunks), in which case the whole text is the body.
    """
    lines = text.split("\n")
    meta = ""
    section: str | None = None
    start = 0
    if len(lines) >= 2 and _SECTION_LINE.match(lines[1].strip()):
        meta = lines[0]
        section = lines[1].strip()
        start = 2
    elif lines and _SECTION_LINE.match(lines[0].strip()):
        section = lines[0].strip()
        start = 1
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    body = "\n".join(lines[start:]).strip()
    return meta, section, body


def _section_kind(section: str | None, body: str) -> str:
    """Classify a chunk: motifs, dispositif, faits, moyens, en-tete or autre."""
    s = (section or "").lower()
    if "motifs" in s:
        return "motifs"
    if "dispositif" in s:
        return "dispositif"
    if "faits" in s:
        return "faits"
    if "moyens" in s:
        return "moyens"
    if "en-tête" in s or "en-tete" in s:
        return "en-tete"
    # No usable label (paragraph fallback): sniff the body for ruling markers.
    if "Réponse de la Cour" in body:
        return "motifs"
    if re.search(r"PAR CES MOTIFS|REJETTE|CASSE ET ANNULE", body):
        return "dispositif"
    return "autre"


def _overlap_len(tail: str, nxt: str) -> int:
    """Length of the longest suffix of ``tail`` that is also a prefix of ``nxt``."""
    window = tail[-_MAX_OVERLAP:]
    hi = min(len(window), len(nxt))
    for k in range(hi, _MIN_OVERLAP - 1, -1):
        if window[-k:] == nxt[:k]:
            return k
    return 0


def _merge_jurisprudence(
    ordered: list[SearchResult],
    seed_indices: frozenset[int],
) -> str:
    """Merge an arrêt's chunks, keeping the ruling rather than the boilerplate.

    Court decisions put the holding (motifs / dispositif) at the END, but the
    char budget is finite. Keeping "the first N chars" drops exactly the part
    that answers the question. So we always keep the motifs/dispositif and the
    chunks that matched the query (seeds), fill the rest with faits/moyens then
    en-tête, strip the repeated per-chunk header, and stitch the token overlap
    between consecutive chunks. Dropped ranges are marked with […].
    """
    dec = {c.chunk_index: _decompose(c.text) for c in ordered}
    meta_header = ""
    for c in ordered:
        if dec[c.chunk_index][0]:
            meta_header = dec[c.chunk_index][0]
            break

    def kind(ci: int) -> str:
        _, section, body = dec[ci]
        return _section_kind(section, body)

    def tier(ci: int) -> int:
        # The holding (motifs/dispositif) wins over everything: it is the answer.
        # Matched chunks (seeds) come next — they are often the faits/moyens that
        # the query hit, large and less decisive, so they must not crowd out the
        # ruling. Then the remaining faits/moyens, then the en-tête boilerplate.
        if kind(ci) in ("motifs", "dispositif"):
            return 0
        if ci in seed_indices:
            return 1
        if kind(ci) in ("faits", "moyens"):
            return 2
        return 3

    # Reserve room for the header and a little label/separator overhead.
    budget = MAX_CHARS_PER_GROUP - (len(meta_header) + 2 if meta_header else 0) - 400
    if budget < 500:
        budget = MAX_CHARS_PER_GROUP

    chosen: set[int] = set()
    remaining = budget
    for t in (0, 1, 2, 3):
        for c in ordered:
            ci = c.chunk_index
            if ci in chosen or tier(ci) != t:
                continue
            need = len(dec[ci][2]) + 2
            if need <= remaining:
                chosen.add(ci)
                remaining -= need
            elif t <= 1 and not chosen:
                # Always keep at least the top-priority chunk (the ruling, or the
                # best match if no ruling was detected), even if it is large.
                chosen.add(ci)
                remaining = 0
    if not chosen and ordered:
        chosen.add(ordered[0].chunk_index)

    text = ""
    prev_idx: int | None = None
    prev_section: str | None = None
    tail = ""
    for c in ordered:
        ci = c.chunk_index
        if ci not in chosen:
            continue
        _, section, body = dec[ci]
        if not body:
            prev_idx = ci
            continue
        if prev_idx is not None and ci != prev_idx + 1:
            text += "\n\n[…]"
            tail = ""
            prev_section = None
        if section and section != prev_section:
            text += ("\n\n" if text else "") + section + "\n\n" + body
            prev_section = section
        else:
            k = _overlap_len(tail, body) if tail else 0
            if k:
                text += body[k:]
            elif text:
                text += "\n\n" + body
            else:
                text += body
        tail = body
        prev_idx = ci

    merged = (meta_header + "\n\n" + text) if meta_header else text
    merged = merged.strip()
    if len(merged) > MAX_CHARS_PER_GROUP:
        merged = merged[:MAX_CHARS_PER_GROUP].rsplit(" ", 1)[0] + " […]"
    return merged


def _merge_group(
    chunks: list[SearchResult],
    best_score: float,
    seed_indices: frozenset[int] = frozenset(),
    is_jurisprudence: bool = False,
) -> SearchResult:
    """Merge chunks of a parent group into one SearchResult.

    For jurisprudence, the holding is prioritised over position (see
    ``_merge_jurisprudence``). For other groups, chunks are concatenated in
    chunk_index order and truncated at MAX_CHARS_PER_GROUP characters.
    """
    seen: set[tuple[str, int]] = set()
    ordered: list[SearchResult] = []
    for c in sorted(chunks, key=lambda x: x.chunk_index):
        key = (c.document_id, c.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(c)

    template = ordered[0]
    if is_jurisprudence:
        merged_text = _merge_jurisprudence(ordered, seed_indices)
    else:
        merged_text = "\n\n".join(c.text for c in ordered).strip()
        if len(merged_text) > MAX_CHARS_PER_GROUP:
            merged_text = merged_text[:MAX_CHARS_PER_GROUP].rsplit(" ", 1)[0] + " […]"

    aggregated_articles: list[str] = []
    for c in ordered:
        if c.article_nums:
            for a in c.article_nums:
                if a not in aggregated_articles:
                    aggregated_articles.append(a)

    return replace(
        template,
        text=merged_text,
        score=best_score,
        article_nums=aggregated_articles or template.article_nums,
    )


def expand_to_parents(
    results: list[SearchResult],
    qdrant,
    min_legislation: int = 0,
) -> list[SearchResult]:
    """Expand each retrieved chunk to its parent group and return merged results.

    The output preserves descending score order. At most MAX_PARENT_GROUPS
    groups are returned. The original chunks are NOT preserved separately —
    each parent group becomes a single SearchResult.

    min_legislation: guarantee that up to this many "written-law" groups
    (Code/loi/décret…) already present in the reranked input survive the
    MAX_PARENT_GROUPS cap. The reranker buries terse code articles below
    verbose jurisprudence, so a directly-applicable article can land at rank
    11–15 and get dropped. This only rescues legislation the reranker already
    accepted into its output — it never injects new law — so questions whose
    rerank carries no legislation (pure jurisprudence) are untouched.
    """
    if not results:
        return results

    # Group by parent key, remember the best seed score per group
    group_seeds: dict[tuple, list[SearchResult]] = {}
    group_best_score: dict[tuple, float] = {}
    group_order: list[tuple] = []
    for r in results:
        key = _parent_key_for(r)
        if key not in group_seeds:
            group_seeds[key] = []
            group_best_score[key] = r.score
            group_order.append(key)
        group_seeds[key].append(r)
        if r.score > group_best_score[key]:
            group_best_score[key] = r.score

    expanded: list[SearchResult] = []
    for key in group_order:
        siblings = _fetch_siblings(qdrant, key)
        seeds = group_seeds[key]
        chunks = siblings if siblings else seeds
        is_juris = key[0] == "doc"
        seed_indices = frozenset(r.chunk_index for r in seeds)
        merged = _merge_group(
            chunks,
            best_score=group_best_score[key],
            seed_indices=seed_indices,
            is_jurisprudence=is_juris,
        )
        if is_juris and seeds:
            best_seed = max(seeds, key=lambda r: r.score)
            merged = replace(merged, seed_text=_decompose(best_seed.text)[2] or best_seed.text)
        expanded.append(merged)

    expanded.sort(key=lambda r: r.score, reverse=True)
    if len(expanded) <= MAX_PARENT_GROUPS:
        return expanded

    kept = expanded[:MAX_PARENT_GROUPS]
    if min_legislation > 0:
        present = sum(1 for r in kept if _is_legislation(r.source_type))
        if present < min_legislation:
            dropped_leg = [
                r for r in expanded[MAX_PARENT_GROUPS:]
                if _is_legislation(r.source_type)
            ]
            need = min_legislation - present
            for r in dropped_leg[:need]:
                # Replace the lowest-scored non-legislation group still kept.
                for j in range(len(kept) - 1, -1, -1):
                    if not _is_legislation(kept[j].source_type):
                        logger.info(
                            "[LEGFLOOR] Preserved %s through parent cap (score %.3f)",
                            r.source_type, r.score,
                        )
                        kept[j] = r
                        break
            kept.sort(key=lambda r: r.score, reverse=True)
    return kept
