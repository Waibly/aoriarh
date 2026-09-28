"""Explicit reads of common official sources, never of private uploaded files."""

import asyncio
import uuid
from dataclasses import replace
from typing import get_args

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select

from app.models.document import Document
from app.rag.chronology import ChronologySource
from app.rag.parent_expansion import RetrievalError, _payload_to_result
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client

MAX_SOURCE_CHUNKS = 200
MAX_READ_CHARACTERS = 150_000


async def read_legal_sources(
    db, document_ids, *, source_exclusions=(), source_restriction=None, client=None
):
    """Return every indexed passage, or an explicit technical error; no partial repair.

    SQL and Qdrant independently restrict access to the common official catalogue.
    A supplied UUID is a lookup key, never an access grant. Uploaded documents and
    collective agreements retain their existing authorised reading paths.
    """
    ids = list(dict.fromkeys(uuid.UUID(str(value)) for value in document_ids))
    if not 1 <= len(ids) <= 10:
        raise RetrievalError("legal_source_invalid_count")
    allowed = [
        kind
        for kind in get_args(ChronologySource)
        if kind not in source_exclusions
        and (source_restriction is None or kind in source_restriction)
    ]
    documents = (
        await db.scalars(
            select(Document).where(
                Document.id.in_(ids),
                Document.organisation_id.is_(None),
                Document.source_type.in_(allowed),
                Document.indexation_status == "indexed",
            )
        )
    ).all()
    by_id = {doc.id: doc for doc in documents}
    if set(by_id) != set(ids):
        raise RetrievalError("legal_source_unavailable")
    client = client if client is not None else get_qdrant_client()
    results, coverage = [], []
    characters = 0
    for doc_id in ids:
        doc = by_id[doc_id]
        if doc.chunk_count is not None and doc.chunk_count > MAX_SOURCE_CHUNKS:
            raise RetrievalError("legal_source_context_budget_exceeded")
        points, next_page = await asyncio.to_thread(
            client.scroll,
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="document_id", match=MatchValue(value=str(doc.id))),
                    FieldCondition(key="organisation_id", match=MatchValue(value="common")),
                    FieldCondition(key="source_type", match=MatchValue(value=doc.source_type)),
                ]
            ),
            limit=MAX_SOURCE_CHUNKS + 1,
            with_payload=True,
            with_vectors=False,
        )
        if next_page is not None or len(points) > MAX_SOURCE_CHUNKS:
            raise RetrievalError("legal_source_context_budget_exceeded")
        if not points or any(
            (p.payload or {}).get("document_id") != str(doc.id)
            or (p.payload or {}).get("organisation_id") != "common"
            or (p.payload or {}).get("source_type") != doc.source_type
            for p in points
        ):
            raise RetrievalError("legal_source_passages_unavailable")
        parts = sorted(
            [_payload_to_result(p.payload) for p in points], key=lambda part: part.chunk_index
        )
        indices = [part.chunk_index for part in parts]
        if (
            doc.chunk_count is not None
            and len(parts) != doc.chunk_count
            or indices != list(range(len(parts)))
            or any(not part.text for part in parts)
        ):
            raise RetrievalError("legal_source_incomplete_index")
        text = "\n\n".join(part.text for part in parts)
        characters += len(text)
        if characters > MAX_READ_CHARACTERS:
            raise RetrievalError("legal_source_context_budget_exceeded")
        results.append(
            replace(
                parts[0],
                doc_name=doc.name,
                text=text,
                context_chunk_indices=indices,
                numero_pourvoi=doc.numero_pourvoi,
                date_decision=doc.date_decision.isoformat() if doc.date_decision else None,
                publication_date=doc.publication_date.isoformat() if doc.publication_date else None,
                effective_date=doc.effective_date.isoformat() if doc.effective_date else None,
                source_updated_date=(
                    doc.source_updated_date.isoformat() if doc.source_updated_date else None
                ),
                source_url=doc.source_url,
            )
        )
        coverage.append(
            {
                "document_id": str(doc.id),
                "name": doc.name,
                "reading_scope": "all_indexed_passages",
                "passages": len(parts),
                "source_url": doc.source_url,
            }
        )
    return results, coverage
