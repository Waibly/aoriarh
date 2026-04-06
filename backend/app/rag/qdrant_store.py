import logging
import threading

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    SparseVectorParams,
    VectorParams,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "aoriarh_documents"
DENSE_VECTOR_SIZE = 1024  # Voyage AI voyage-law-2 dimension


_client: QdrantClient | None = None
_lock = threading.Lock()


def _create_client() -> QdrantClient:
    """Create a new Qdrant client with timeout and retry settings."""
    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key or None,
        timeout=10,
        check_compatibility=False,
    )


def get_qdrant_client() -> QdrantClient:
    """Return a module-level singleton Qdrant client with auto-reconnection."""
    global _client
    if _client is not None:
        try:
            _client.get_collections()
            return _client
        except Exception:
            logger.warning("Qdrant connection lost, reconnecting...")
            _client = None

    with _lock:
        if _client is None:
            _client = _create_client()
    return _client


def reset_qdrant_client() -> None:
    """Force reset the Qdrant client (useful after Qdrant restart)."""
    global _client
    with _lock:
        _client = None


def ensure_collection(client: QdrantClient) -> None:
    """Create the collection with dense + sparse vectors and payload indexes."""
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": VectorParams(
                    size=DENSE_VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse-bm25": SparseVectorParams(),
            },
        )
        # Create payload indexes for efficient filtering
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="organisation_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="document_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="source_type",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="idcc",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        logger.info("Created Qdrant collection '%s' with indexes", COLLECTION_NAME)

    # Ensure newer indexes exist (added after initial collection creation)
    _ensure_payload_index(client, "idcc", PayloadSchemaType.KEYWORD)


def _ensure_payload_index(
    client: QdrantClient,
    field_name: str,
    field_schema: PayloadSchemaType,
) -> None:
    """Create a payload index if it doesn't already exist (idempotent)."""
    try:
        info = client.get_collection(COLLECTION_NAME)
        existing = info.payload_schema or {}
        if field_name not in existing:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=field_schema,
            )
            logger.info("Created payload index '%s' on '%s'", field_name, COLLECTION_NAME)
    except Exception:
        logger.debug("Could not ensure index '%s' (collection may not exist yet)", field_name)
