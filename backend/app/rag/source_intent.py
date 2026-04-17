"""Detect explicit source-type intent in user queries.

When a user explicitly names a category of source ("la CCN", "le Code du travail",
"notre règlement intérieur"), we guarantee that source type is represented in the
retrieval pool — regardless of RRF/rerank scores.

This is intent-driven, not speculative: we only act when the user names the source.
"""

import logging
import re

from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FusionQuery,
    MatchAny,
    MatchValue,
    Prefetch,
    SparseVector,
)

from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.search import SearchResult

logger = logging.getLogger(__name__)

# Each entry: (compiled regex, list of source_types to fetch, needs_org_filter)
# needs_org_filter: True = filter on organisation_id (org-specific docs)
#                   False = filter on "common" + optional idcc
_INTENT_PATTERNS: list[tuple[re.Pattern, list[str], bool]] = [
    # CCN / Convention collective
    (
        re.compile(
            r"\b(?:ccn|convention\s+collective|ma\s+convention|notre\s+convention"
            r"|votre\s+convention|la\s+convention)\b",
            re.IGNORECASE,
        ),
        ["convention_collective_nationale", "accord_branche"],
        False,  # common docs filtered by idcc
    ),
    # Accord d'entreprise
    (
        re.compile(
            r"\b(?:accord\s+d['\u2019]entreprise|nos\s+accords|notre\s+accord"
            r"|accord\s+interne|accords?\s+collectifs?\s+d['\u2019]entreprise)\b",
            re.IGNORECASE,
        ),
        ["accord_entreprise", "accord_performance_collective"],
        True,  # org-specific docs
    ),
    # Règlement intérieur
    (
        re.compile(
            r"\b(?:r[eè]glement\s+int[eé]rieur|notre\s+ri\b|le\s+ri\b|mon\s+ri\b)\b",
            re.IGNORECASE,
        ),
        ["reglement_interieur"],
        True,
    ),
    # Contrat de travail
    (
        re.compile(
            r"\b(?:contrat\s+de\s+travail|mon\s+contrat|notre\s+contrat"
            r"|le\s+contrat)\b",
            re.IGNORECASE,
        ),
        ["contrat_travail"],
        True,
    ),
    # Code du travail
    (
        re.compile(
            r"\b(?:code\s+du\s+travail)\b",
            re.IGNORECASE,
        ),
        ["code_travail", "code_travail_reglementaire"],
        False,
    ),
    # Jurisprudence
    (
        re.compile(
            r"\b(?:jurisprudence|cour\s+de\s+cassation|cassation"
            r"|arr[eê]t|cour\s+d['\u2019]appel)\b",
            re.IGNORECASE,
        ),
        [
            "arret_cour_cassation",
            "arret_cour_appel",
            "arret_conseil_etat",
            "decision_conseil_constitutionnel",
        ],
        False,
    ),
    # DUE / Engagement unilatéral
    (
        re.compile(
            r"\b(?:due|d[eé]cision\s+unilat[eé]rale|engagement\s+unilat[eé]ral)\b",
            re.IGNORECASE,
        ),
        ["engagement_unilateral"],
        True,
    ),
    # Usage d'entreprise
    (
        re.compile(
            r"\b(?:usage\s+d['\u2019]entreprise|nos\s+usages|un\s+usage)\b",
            re.IGNORECASE,
        ),
        ["usage_entreprise"],
        True,
    ),
]

# Max chunks to inject from intent-based search
_INTENT_INJECT_LIMIT = 10


def detect_source_intent(query: str) -> list[tuple[list[str], bool]]:
    """Detect explicit source-type mentions in the query.

    Returns list of (source_types, needs_org_filter) tuples for each match.
    """
    matches = []
    for pattern, source_types, needs_org in _INTENT_PATTERNS:
        if pattern.search(query):
            matches.append((source_types, needs_org))
    return matches


def _point_to_result(payload: dict, score: float) -> SearchResult:
    """Convert a Qdrant point payload to a SearchResult."""
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


def fetch_by_source_intent(
    qdrant: QdrantClient,
    query: str,
    organisation_id: str,
    org_idcc_list: list[str] | None = None,
    dense_embedding: list[float] | None = None,
    sparse_vector: dict | None = None,
    limit: int = _INTENT_INJECT_LIMIT,
) -> list[SearchResult]:
    """Fetch chunks matching the user's explicit source-type intent.

    Uses hybrid search (dense + sparse RRF) filtered to the requested
    source types. Both embeddings are required for proper results.
    """
    intents = detect_source_intent(query)
    if not intents:
        return []
    if not dense_embedding:
        return []

    all_results: list[SearchResult] = []
    seen: set[tuple[str, int]] = set()

    for source_types, needs_org in intents:
        # Build filter
        must_conditions = [
            FieldCondition(
                key="source_type",
                match=MatchAny(any=source_types),
            ),
        ]

        if needs_org:
            must_conditions.append(
                FieldCondition(
                    key="organisation_id",
                    match=MatchValue(value=organisation_id),
                ),
            )
        else:
            must_conditions.append(
                FieldCondition(
                    key="organisation_id",
                    match=MatchValue(value="common"),
                ),
            )
            ccn_types = {"convention_collective_nationale", "accord_branche"}
            if org_idcc_list and any(st in ccn_types for st in source_types):
                must_conditions.append(
                    FieldCondition(
                        key="idcc",
                        match=MatchAny(any=org_idcc_list),
                    ),
                )

        intent_filter = Filter(must=must_conditions)

        # Hybrid search: dense + sparse RRF (same as main pipeline)
        prefetches = [
            Prefetch(
                query=dense_embedding,
                using="dense",
                limit=limit * 2,
                filter=intent_filter,
            ),
        ]
        if sparse_vector:
            prefetches.append(
                Prefetch(
                    query=SparseVector(
                        indices=sparse_vector["indices"],
                        values=sparse_vector["values"],
                    ),
                    using="sparse-bm25",
                    limit=limit * 2,
                    filter=intent_filter,
                ),
            )

        points = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=prefetches,
            query=FusionQuery(fusion="rrf"),
            limit=limit,
            with_payload=True,
        )

        for point in points.points:
            payload = point.payload or {}
            key = (payload.get("document_id", ""), int(payload.get("chunk_index", 0)))
            if key in seen:
                continue
            seen.add(key)
            all_results.append(
                _point_to_result(payload, point.score or 0.0),
            )

    logger.info(
        "[INTENT] Source intent detected: %s → %d chunks injected",
        ", ".join(st for types, _ in intents for st in types),
        len(all_results),
    )
    return all_results
