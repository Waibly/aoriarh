"""Copy to a separate collection: compatible with Qdrant 1.13, no source mutation."""

import math

from qdrant_client.models import (
    Filter,
    HasVectorCondition,
    HnswConfigDiff,
    Modifier,
    OptimizersConfigDiff,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
)

from app.rag.lexical_profile import lexical_profile
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.search import _get_sparse_model

FRENCH_COLLECTION = "aoriarh_documents_fr_v1"


def sparse_coverage(client, collection=FRENCH_COLLECTION, *, source=COLLECTION_NAME) -> dict:
    field = lexical_profile("french-v1").vector_name
    source_total = client.count(source, exact=True).count
    if not client.collection_exists(collection):
        return {"collection": collection, "exists": False, "complete": False,
                "source_points": source_total}
    config = client.get_collection(collection).config.params.sparse_vectors or {}
    total = client.count(collection, exact=True).count
    covered = client.count(collection, count_filter=Filter(
        must=[HasVectorCondition(has_vector=field)],
    ), exact=True).count if field in config else 0
    return {"collection": collection, "exists": True, "points": total, "covered": covered,
            "source_points": source_total, "complete": total == covered == source_total,
            "modifier": str(config[field].modifier)
            if field in config else None}


def build_sparse_profile(client, *, max_points: int, batch_size: int = 128, model=None,
                         source=COLLECTION_NAME, target=FRENCH_COLLECTION, offset=None,
                         resume: bool = False) -> dict:
    if source == target or max_points < 1 or not 1 <= batch_size <= 256:
        raise ValueError("invalid_sparse_migration_budget_or_destination")
    field = lexical_profile("french-v1").vector_name
    original = client.get_collection(source)
    if client.collection_exists(target) and not resume:
        raise ValueError("sparse_migration_destination_exists_requires_explicit_resume")
    if not client.collection_exists(target):
        client.create_collection(
            target, vectors_config=original.config.params.vectors,
            sparse_vectors_config={**(original.config.params.sparse_vectors or {}),
                                   field: SparseVectorParams(
                                       index=SparseIndexParams(on_disk=True), modifier=Modifier.IDF,
                                   )},
            hnsw_config=HnswConfigDiff(on_disk=True, max_indexing_threads=2),
            optimizers_config=OptimizersConfigDiff(max_optimization_threads=1),
        )
        for key, schema in original.payload_schema.items():
            client.create_payload_index(target, key, field_schema=schema.params or schema.data_type)
    config = client.get_collection(target).config.params
    if (config.vectors != original.config.params.vectors
            or field not in (config.sparse_vectors or {})
            or config.sparse_vectors[field].modifier != Modifier.IDF):
        raise ValueError("sparse_migration_destination_schema_mismatch")
    model = model or _get_sparse_model("french-v1")
    processed = 0
    while processed < max_points:
        points, next_offset = client.scroll(
            source, offset=offset, limit=min(batch_size, max_points - processed),
            with_vectors=True, with_payload=True,
        )
        if not points:
            offset = None
            break
        texts = [(p.payload or {}).get("text") for p in points]
        if any(not isinstance(value, str) or not value for value in texts):
            raise ValueError("sparse_migration_missing_source_text")
        vectors = list(model.embed(texts))
        if len(vectors) != len(points):
            raise ValueError("sparse_migration_incomplete_vectors")
        if any(not isinstance(point.vector, dict) for point in points):
            raise ValueError("sparse_migration_requires_named_vectors")
        client.upsert(target, points=[
            PointStruct(id=point.id, payload=point.payload, vector={
                **point.vector, field: SparseVector(
                    indices=vector.indices.tolist(), values=vector.values.tolist(),
                ),
            }) for point, vector in zip(points, vectors, strict=True)
        ], wait=True)
        processed += len(points)
        offset = next_offset
        if next_offset is None:
            break
    return {"processed": processed, "next_offset": offset,
            **sparse_coverage(client, target, source=source)}


def verify_sparse_copy(client, *, source=COLLECTION_NAME, target=FRENCH_COLLECTION) -> dict:
    """Full identity, payload and old-vector comparison; freeze writes during this check."""
    report = sparse_coverage(client, target, source=source)
    total = client.count(source, exact=True).count
    if (source == target or not report.get("complete") or report.get("modifier") != "idf"
            or report.get("points") != total):
        raise ValueError("sparse_migration_incomplete_copy")
    before_indexes = client.get_collection(source).payload_schema
    after_indexes = client.get_collection(target).payload_schema
    if any(key not in after_indexes or info.data_type != after_indexes[key].data_type
           or info.params != after_indexes[key].params for key, info in before_indexes.items()):
        raise ValueError("sparse_migration_payload_index_mismatch")
    offset, checked = None, 0
    while True:
        points, offset = client.scroll(source, offset=offset, limit=128,
                                       with_vectors=True, with_payload=True)
        copied = {p.id: p for p in client.retrieve(
            target, ids=[p.id for p in points], with_payload=True, with_vectors=True,
        )} if points else {}
        for point in points:
            other = copied.get(point.id)
            if other is None or point.payload != other.payload:
                raise ValueError("sparse_migration_payload_or_identity_mismatch")
            for name, vector in point.vector.items():
                copied_vector = other.vector.get(name)
                if isinstance(vector, list):
                    equal = (isinstance(copied_vector, list) and len(vector) == len(copied_vector)
                             and all(math.isclose(a, b, abs_tol=1e-6, rel_tol=1e-5)
                                     for a, b in zip(vector, copied_vector, strict=True)))
                else:
                    equal = vector == copied_vector
                if not equal:
                    raise ValueError("sparse_migration_existing_vector_mismatch")
            checked += 1
        if offset is None:
            break
    return {**report, "verified_points": checked}
