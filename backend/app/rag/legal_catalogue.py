"""Chronological document discovery, followed by bounded source reads.

Only common official sources are exposed by this capability. Private files and
CCNs remain in their existing authorised retrieval paths. Dates come from source
metadata, never from text heuristics, created_at or model-generated values.
"""

import asyncio
import uuid
from dataclasses import replace
from datetime import date
from typing import get_args

from qdrant_client.models import FieldCondition, Filter, MatchAny
from sqlalchemy import case, func, select

from app.core.database import async_session_factory
from app.models.document import Document
from app.models.sync_log import SyncLog
from app.rag.chronology import ChronologyRequest, ChronologySource
from app.rag.parent_expansion import RetrievalError, _payload_to_result
from app.rag.qdrant_store import COLLECTION_NAME

TOPIC_DOCUMENT_BUDGET = 500
TOPIC_PASSAGE_BUDGET = 80
READ_CHUNKS = 6
READ_CHARS = 18_000
DECISION_TYPES = (
    "arret_cour_cassation",
    "arret_cour_appel",
    "arret_conseil_etat",
    "decision_conseil_constitutionnel",
)


def date_expression(kind):
    decision = case((Document.source_type.in_(DECISION_TYPES), Document.date_decision))
    return {
        "publication": Document.publication_date,
        "decision": decision,
        "effective": Document.effective_date,
        "update": Document.source_updated_date,
        "event": case(
            (Document.source_type.in_(DECISION_TYPES), Document.date_decision),
            (Document.source_type == "boss", Document.source_updated_date),
            else_=Document.publication_date,
        ),
    }[kind]


def event_kind(spec, document):
    if spec.date_kind != "event":
        return spec.date_kind
    if document.source_type in DECISION_TYPES:
        return "decision"
    return "update" if document.source_type == "boss" else "publication"


async def catalogue_page(
    db,
    spec: ChronologyRequest,
    *,
    today=None,
    source_exclusions=(),
    source_restriction=None,
):
    """SQL pagination over documents, not chunks; count missing dates separately."""
    selected_date = date_expression(spec.date_kind)
    allowed_types = [
        value
        for value in (spec.source_types or get_args(ChronologySource))
        if value not in source_exclusions
        and (source_restriction is None or value in source_restriction)
    ]
    filters = [
        Document.organisation_id.is_(None),
        Document.indexation_status == "indexed",
        Document.source_type.in_(allowed_types),
    ]
    for column, value in (
        (Document.juridiction, spec.jurisdiction),
        (Document.chambre, spec.chamber),
    ):
        if value:
            filters.append(column.icontains(value, autoescape=True))
    missing = await db.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            *filters,
            selected_date.is_(None),
        )
    )
    filters.append(selected_date.isnot(None))
    if spec.date_from:
        filters.append(selected_date >= spec.date_from)
    if spec.date_to:
        filters.append(selected_date <= spec.date_to)
    # Publications, decisions and updates cannot be future events as of the query.
    # Effective dates can be future, and must not acquire an arbitrary horizon.
    if spec.date_kind != "effective":
        filters.append(selected_date <= (today or date.today()))
    total = await db.scalar(select(func.count()).select_from(Document).where(*filters))
    ordering = selected_date.desc() if spec.order == "newest" else selected_date.asc()
    budget = TOPIC_DOCUMENT_BUDGET if spec.topic else spec.limit
    offset = 0 if spec.topic else spec.offset
    rows = (
        await db.execute(
            select(Document, selected_date.label("event_date"))
            .where(*filters)
            .order_by(ordering, Document.id)
            .offset(offset)
            .limit(budget + 1)
        )
    ).all()
    # Latest status per collector. It describes a collection attempt, not coverage
    # through a specific publication date. No raw error strings/secrets are exposed.
    sync_types = {
        "jorf"
        if t in {"loi", "ordonnance", "decret", "arrete"}
        else "boss"
        if t == "boss"
        else "jurisprudence"
        for t in allowed_types
    }
    syncs = []
    for sync_type in sorted(sync_types):
        log = (
            await db.execute(
                select(SyncLog)
                .where(SyncLog.sync_type == sync_type)
                .order_by(SyncLog.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        syncs.append(
            {
                "source": sync_type,
                "status": log.status if log else "unknown",
                "completed_at": log.completed_at.isoformat() if log and log.completed_at else None,
                "errors": log.errors if log else None,
            }
        )
    report = {
        "request": spec.model_dump(mode="json"),
        "allowed_source_types": allowed_types,
        "as_of": (today or date.today()).isoformat(),
        "scope": "collected_common_official_sources_only",
        "matching_dated_documents": total,
        "documents_with_unknown_date": missing,
        "catalogue_has_more": len(rows) > budget,
        "topic_candidate_limit": TOPIC_DOCUMENT_BUDGET if spec.topic else None,
        "topic_candidates_truncated": bool(spec.topic and len(rows) > budget),
        "collection_status": syncs,
    }
    return rows[:budget], report


class LegalCatalogueSearch:
    def __init__(self, search_engine, reranker, *, session_factory=async_session_factory):
        self.search_engine = search_engine
        self.reranker = reranker
        self.session_factory = session_factory

    async def search(
        self,
        spec,
        organisation_id,
        *,
        org_idcc_list=None,
        cost_ctx=None,
        source_exclusions=(),
        source_restriction=None,
    ):
        # Fail closed even though SQL lists only common official sources.
        uuid.UUID(organisation_id)
        try:
            async with self.session_factory() as db:
                rows, report = await catalogue_page(
                    db,
                    spec,
                    source_exclusions=source_exclusions,
                    source_restriction=source_restriction,
                )
            seeds = {}
            if spec.topic and rows:
                candidates = await self.search_engine.search(
                    spec.topic,
                    organisation_id,
                    top_k=TOPIC_PASSAGE_BUDGET,
                    org_idcc_list=org_idcc_list,
                    document_ids=[str(doc.id) for doc, _ in rows],
                    cost_ctx=cost_ctx,
                )
                ranked = await self.reranker.rerank(spec.topic, candidates, cost_ctx=cost_ctx)
                for item in ranked:
                    seeds.setdefault(item.document_id, item)
                # Select a bounded relevance pool before chronological ordering.
                # No quality threshold, invented score or substitute sources.
                seeds = dict(list(seeds.items())[:40])
                rows = [(doc, when) for doc, when in rows if str(doc.id) in seeds]
                report["topic_matched_documents"] = len(rows)
                report["topic_passage_limit"] = TOPIC_PASSAGE_BUDGET
                report["topic_selection_is_exhaustive"] = False
                report["catalogue_has_more"] = len(rows) > spec.offset + spec.limit
                rows = rows[spec.offset : spec.offset + spec.limit]
            report["next_offset"] = (
                spec.offset + len(rows) if report["catalogue_has_more"] else None
            )
            read_results = await asyncio.gather(
                *(
                    self._read_document(doc, organisation_id, org_idcc_list, seeds.get(str(doc.id)))
                    for doc, _ in rows
                )
            )
            results, selected = [], []
            for (doc, when), (passage, partial) in zip(rows, read_results):
                kind = event_kind(spec, doc)
                selected.append(
                    {
                        "document_id": str(doc.id),
                        "name": doc.name,
                        "date": when.isoformat(),
                        "date_kind": kind,
                        "source_url": doc.source_url,
                        "partial_read": partial,
                    }
                )
                results.append(
                    replace(
                        passage,
                        publication_date=doc.publication_date.isoformat()
                        if doc.publication_date
                        else None,
                        effective_date=doc.effective_date.isoformat()
                        if doc.effective_date
                        else None,
                        source_updated_date=(
                            doc.source_updated_date.isoformat() if doc.source_updated_date else None
                        ),
                        source_url=doc.source_url,
                        chronology_date=when.isoformat(),
                        chronology_date_kind=kind,
                        date_decision=(
                            doc.date_decision.isoformat()
                            if doc.source_type in DECISION_TYPES and doc.date_decision
                            else None
                        ),
                    )
                )
            report["selected_documents"] = selected
            return results, report
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError("chronological_catalogue_failed") from exc

    async def _read_document(self, doc, organisation_id, org_idcc_list, seed):
        # Read opening chunks and, for a topic, neighbours of the matching passage.
        indices = (
            list(range(READ_CHUNKS))
            if seed is None
            else list(
                dict.fromkeys([0, *range(max(0, seed.chunk_index - 2), seed.chunk_index + 3)])
            )
        )
        access = self.search_engine._build_org_filter(
            organisation_id,
            org_idcc_list,
            document_ids=[str(doc.id)],
        )
        points, _ = await asyncio.to_thread(
            self.search_engine.qdrant.scroll,
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    access,
                    FieldCondition(
                        key="chunk_index",
                        match=MatchAny(any=indices),
                    ),
                ]
            ),
            limit=len(indices) + 1,
            with_payload=True,
            with_vectors=False,
        )
        parts = sorted(
            [_payload_to_result(p.payload or {}) for p in points], key=lambda part: part.chunk_index
        )
        if not parts or any(p.document_id != str(doc.id) for p in parts):
            raise RetrievalError("chronological_document_unavailable")
        # Limit source context by whole passages, never trim a generated answer.
        kept, chars = [], 0
        priority = (
            sorted(parts, key=lambda p: (p.chunk_index != seed.chunk_index, p.chunk_index))
            if seed
            else parts
        )
        for part in priority:
            if chars + len(part.text) <= READ_CHARS:
                kept.append(part)
                chars += len(part.text)
        if not kept:
            raise RetrievalError("chronological_document_context_too_large")
        kept.sort(key=lambda p: p.chunk_index)
        return replace(
            kept[0],
            doc_name=doc.name,
            text="\n\n".join(p.text for p in kept),
            context_chunk_indices=[p.chunk_index for p in kept],
        ), doc.chunk_count is None or len(kept) < doc.chunk_count
