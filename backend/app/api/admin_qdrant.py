from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.dependencies import require_role
from app.models.user import User
from app.rag.qdrant_store import get_qdrant_client

router = APIRouter()


class CollectionInfo(BaseModel):
    name: str
    points_count: int
    status: str


class PointPayload(BaseModel):
    id: str
    text: str
    organisation_id: str | None = None
    document_id: str | None = None
    doc_name: str | None = None
    source_type: str | None = None
    norme_niveau: int | None = None
    norme_poids: float | None = None
    chunk_index: int | None = None


class PointsResponse(BaseModel):
    points: list[PointPayload]
    total: int
    offset: int
    limit: int


@router.get("/collections", response_model=list[CollectionInfo])
async def list_collections(
    user: User = Depends(require_role(["admin"])),
) -> list[CollectionInfo]:
    client = get_qdrant_client()
    collections = client.get_collections().collections
    result = []
    for col in collections:
        info = client.get_collection(col.name)
        result.append(
            CollectionInfo(
                name=col.name,
                points_count=info.points_count or 0,
                status=str(info.status),
            )
        )
    return result


@router.get("/collections/{collection_name}/points", response_model=PointsResponse)
async def list_points(
    collection_name: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    organisation_id: str | None = Query(None),
    document_id: str | None = Query(None),
    user: User = Depends(require_role(["admin"])),
) -> PointsResponse:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = get_qdrant_client()

    # Build filter
    must_conditions = []
    if organisation_id:
        must_conditions.append(
            FieldCondition(key="organisation_id", match=MatchValue(value=organisation_id))
        )
    if document_id:
        must_conditions.append(
            FieldCondition(key="document_id", match=MatchValue(value=document_id))
        )

    scroll_filter = Filter(must=must_conditions) if must_conditions else None

    # Get total count
    count_result = client.count(
        collection_name=collection_name,
        count_filter=scroll_filter,
        exact=True,
    )
    total = count_result.count

    # Qdrant scroll uses cursor-based pagination (offset = point ID, not page number).
    # To simulate page-based offset, we scroll through pages sequentially.
    next_cursor: str | int | None = None
    skipped = 0
    # Skip pages until we reach the desired offset
    while skipped < offset:
        batch_size = min(limit, offset - skipped)
        batch, next_cursor = client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=next_cursor,
            with_payload=False,
            with_vectors=False,
        )
        skipped += len(batch)
        if next_cursor is None:
            break

    # Fetch the actual page
    points_result, _next = client.scroll(
        collection_name=collection_name,
        scroll_filter=scroll_filter,
        limit=limit,
        offset=next_cursor,
        with_payload=True,
        with_vectors=False,
    )

    points = []
    for point in points_result:
        payload = point.payload or {}
        points.append(
            PointPayload(
                id=str(point.id),
                text=payload.get("text", ""),
                organisation_id=payload.get("organisation_id"),
                document_id=payload.get("document_id"),
                doc_name=payload.get("doc_name"),
                source_type=payload.get("source_type"),
                norme_niveau=payload.get("norme_niveau"),
                norme_poids=payload.get("norme_poids"),
                chunk_index=payload.get("chunk_index"),
            )
        )

    return PointsResponse(points=points, total=total, offset=offset, limit=limit)
