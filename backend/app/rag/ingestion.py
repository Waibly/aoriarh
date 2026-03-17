import asyncio
import logging
import math
import time
import uuid

import httpx
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.rag.article_chunker import ArticleChunker
from app.rag.chunker import LegalChunker
from app.rag.config import EMBEDDING_MODEL
from app.services.cost_tracker import cost_tracker
from app.rag.jurisprudence_chunker import JurisprudenceChunker
from app.rag.norme_hierarchy import JURISPRUDENCE_SOURCE_TYPES

# Source types that use article-aware chunking (Code du travail, CCN)
ARTICLE_AWARE_SOURCE_TYPES = {
    "code_travail",
    "code_travail_reglementaire",
    "code_civil",
    "code_penal",
    "code_securite_sociale",
    "code_securite_sociale_reglementaire",
    "code_action_sociale",
    "convention_collective_nationale",
}
from app.rag.qdrant_store import COLLECTION_NAME, ensure_collection, get_qdrant_client
from app.rag.text_cleaner import clean_text
from app.rag.text_extractor import TextExtractor
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

# Retry config for Voyage AI rate limits
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
EMBEDDING_BATCH_SIZE = 32  # Reduced from 64 to handle large legal code chunks

# --- Date extraction for recency boosting ---
import re as _re_mod

_FRENCH_MONTHS = {
    "janvier": "01", "février": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "août": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12",
}
_DATE_PATTERN = _re_mod.compile(
    r"(?:1er|(\d{1,2}))\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})",
    _re_mod.IGNORECASE,
)


def _extract_content_date(text: str) -> str | None:
    """Extract the most recent date from a chunk text (YYYY-MM-DD format).

    Looks for French date patterns like '1er février 2021' or '15 mars 2023'.
    Returns the most recent date found, or None.
    """
    dates = []
    for m in _DATE_PATTERN.finditer(text):
        day = m.group(1) or "01"  # "1er" → day=01
        month = _FRENCH_MONTHS.get(m.group(2).lower())
        year = m.group(3)
        if month and 1990 <= int(year) <= 2030:
            dates.append(f"{year}-{month}-{day.zfill(2)}")
    return max(dates) if dates else None


async def _get_embeddings_batch(
    texts: list[str],
    api_key: str,
    client: httpx.AsyncClient,
    organisation_id: str | None = None,
    document_id: str | None = None,
    user_id: str | None = None,
) -> list[list[float]]:
    """Get dense embeddings for a single batch (max 128 texts) with retry on 429."""
    url = "https://api.voyageai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES):
        response = await client.post(
            url,
            headers=headers,
            json={"input": texts, "model": EMBEDDING_MODEL},
            timeout=60.0,
        )
        if response.status_code == 429 and attempt < MAX_RETRIES - 1:
            delay = RETRY_BASE_DELAY * (2**attempt)
            logger.warning("Voyage AI rate limit, retrying in %.1fs...", delay)
            await asyncio.sleep(delay)
            continue
        if response.status_code != 200:
            char_lengths = [len(t) for t in texts]
            total_chars = sum(char_lengths)
            logger.error(
                "Voyage AI error %d on batch of %d texts: "
                "total_chars=%d, min_chars=%d, max_chars=%d, avg_chars=%d, "
                "response=%s",
                response.status_code,
                len(texts),
                total_chars,
                min(char_lengths),
                max(char_lengths),
                total_chars // len(texts),
                response.text[:500],
            )
        response.raise_for_status()
        data = response.json()
        # Log embedding cost for ingestion
        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        if total_tokens:
            await cost_tracker.log(
                provider="voyageai",
                model=EMBEDDING_MODEL,
                operation_type="embedding",
                tokens_input=total_tokens,
                organisation_id=organisation_id,
                user_id=user_id,
                context_type="ingestion",
                context_id=document_id,
            )
        return [item["embedding"] for item in data["data"]]

    raise RuntimeError("Voyage AI: max retries exceeded")


async def _get_embeddings(
    texts: list[str],
    api_key: str,
    organisation_id: str | None = None,
    document_id: str | None = None,
) -> list[list[float]]:
    """Get dense embeddings with automatic batching."""
    all_embeddings: list[list[float]] = []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i : i + EMBEDDING_BATCH_SIZE]
            all_embeddings.extend(
                await _get_embeddings_batch(
                    batch, api_key, client,
                    organisation_id=organisation_id,
                    document_id=document_id,
                )
            )
    return all_embeddings


EMBEDDING_CONCURRENCY = 4  # max concurrent Voyage AI requests


async def _get_embeddings_with_progress(
    texts: list[str],
    api_key: str,
    doc: Document,
    db: AsyncSession,
) -> list[list[float]]:
    """Get dense embeddings with progress updates (15% → 80%) and concurrency."""
    total_batches = math.ceil(len(texts) / EMBEDDING_BATCH_SIZE)
    results: list[list[list[float]]] = [[] for _ in range(total_batches)]
    semaphore = asyncio.Semaphore(EMBEDDING_CONCURRENCY)
    db_lock = asyncio.Lock()
    done_count = 0

    org_id_str = str(doc.organisation_id) if doc.organisation_id else None
    doc_id_str = str(doc.id)
    user_id_str = str(doc.uploaded_by) if doc.uploaded_by else None

    async def _process_batch(
        batch_idx: int, client: httpx.AsyncClient
    ) -> None:
        nonlocal done_count
        start = batch_idx * EMBEDDING_BATCH_SIZE
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        async with semaphore:
            results[batch_idx] = await _get_embeddings_batch(
                batch, api_key, client,
                organisation_id=org_id_str,
                document_id=doc_id_str,
                user_id=user_id_str,
            )
        async with db_lock:
            done_count += 1
            # Update progress: 15% → 80% proportional to batches done
            progress = 15 + int(65 * done_count / total_batches)
            doc.indexation_progress = progress
            await db.commit()

    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *[_process_batch(i, client) for i in range(total_batches)]
        )

    # Flatten results in order
    all_embeddings: list[list[float]] = []
    for batch_result in results:
        all_embeddings.extend(batch_result)
    return all_embeddings


def _get_sparse_vectors(texts: list[str]) -> list[dict]:
    """Get BM25 sparse vectors using fastembed (cached singleton model)."""
    from app.rag.search import _get_sparse_model

    model = _get_sparse_model()
    results = list(model.embed(texts))
    sparse_vectors = []
    for embedding in results:
        sparse_vectors.append({
            "indices": embedding.indices.tolist(),
            "values": embedding.values.tolist(),
        })
    return sparse_vectors


class IngestionPipeline:
    """Pipeline d'ingestion de documents dans Qdrant."""

    def __init__(self) -> None:
        self.extractor = TextExtractor()
        self.chunker = LegalChunker()
        self.article_chunker = ArticleChunker()
        self.jurisprudence_chunker = JurisprudenceChunker()
        self.storage = StorageService()
        self.qdrant = get_qdrant_client()
        ensure_collection(self.qdrant)

    async def _update_progress(
        self, doc: Document, db: AsyncSession, progress: int
    ) -> None:
        doc.indexation_progress = progress
        await db.commit()

    async def ingest(self, document_id: uuid.UUID, db: AsyncSession) -> None:
        # 1. Load document from PostgreSQL
        result = await db.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            logger.error("Document %s not found in DB", document_id)
            return

        start_time = time.time()

        try:
            # 2. Update status to indexing
            doc.indexation_status = "indexing"
            doc.indexation_progress = 0
            await db.commit()

            # 3. Download from MinIO
            file_bytes = self.storage.get_file_bytes(doc.storage_path)
            await self._update_progress(doc, db, 5)

            # 4. Extract text
            raw_text = self.extractor.extract(file_bytes, doc.file_format or "pdf")
            await self._update_progress(doc, db, 10)

            # 5. Clean text
            cleaned_text = clean_text(raw_text)

            if not cleaned_text.strip():
                logger.warning("Document %s: no text extracted", document_id)
                doc.indexation_status = "error"
                doc.indexation_error = "Aucun texte extrait du document"
                doc.indexation_progress = None
                await db.commit()
                return

            # 6. Chunk (route to specialized chunker by source type)
            if doc.source_type in JURISPRUDENCE_SOURCE_TYPES:
                metadata_header = self._build_jurisprudence_header(doc)
                chunks = self.jurisprudence_chunker.chunk(
                    cleaned_text, metadata_header=metadata_header,
                )
            elif doc.source_type in ARTICLE_AWARE_SOURCE_TYPES:
                chunks = self.article_chunker.chunk(cleaned_text)
            else:
                chunks = self.chunker.chunk(cleaned_text)
            if not chunks:
                logger.warning("Document %s: no chunks produced", document_id)
                doc.indexation_status = "error"
                doc.indexation_error = "Aucun chunk produit après extraction du texte"
                doc.indexation_progress = None
                await db.commit()
                return

            chunk_char_lengths = [len(c) for c in chunks]
            total_chars = sum(chunk_char_lengths)
            logger.info(
                "Document %s: %d chunks produced — "
                "total_chars=%d, min=%d, max=%d, avg=%d",
                document_id,
                len(chunks),
                total_chars,
                min(chunk_char_lengths),
                max(chunk_char_lengths),
                total_chars // len(chunks),
            )
            await self._update_progress(doc, db, 15)

            # 7. Generate embeddings (dense + sparse) — 15% → 80%
            dense_embeddings = await _get_embeddings_with_progress(
                chunks, settings.voyage_api_key, doc, db
            )
            sparse_vectors = _get_sparse_vectors(chunks)
            await self._update_progress(doc, db, 85)

            # 8. Build Qdrant points with metadata
            org_id_str = str(doc.organisation_id) if doc.organisation_id else "common"
            new_point_ids: list[str] = []
            points = []
            for i, (chunk_text, dense_emb, sparse_vec) in enumerate(
                zip(chunks, dense_embeddings, sparse_vectors)
            ):
                point_id = str(uuid.uuid4())
                new_point_ids.append(point_id)
                payload = {
                    "text": chunk_text,
                    "organisation_id": org_id_str,
                    "document_id": str(doc.id),
                    "doc_name": doc.name,
                    "source_type": doc.source_type,
                    "norme_niveau": doc.norme_niveau,
                    "norme_poids": doc.norme_poids,
                    "chunk_index": i,
                }
                # Propagate CCN IDCC into Qdrant payload for per-org filtering
                if doc.source_type in ARTICLE_AWARE_SOURCE_TYPES:
                    import re as _re
                    idcc_match = _re.search(r"IDCC\s+(\d{4})", doc.name)
                    if idcc_match:
                        payload["idcc"] = idcc_match.group(1)
                    # Extract most recent date from chunk for recency boosting
                    content_date = _extract_content_date(chunk_text)
                    if content_date:
                        payload["content_date"] = content_date

                # Propagate jurisprudence metadata into Qdrant payload
                if doc.source_type in JURISPRUDENCE_SOURCE_TYPES:
                    payload["juridiction"] = doc.juridiction
                    payload["chambre"] = doc.chambre
                    payload["formation"] = doc.formation
                    payload["numero_pourvoi"] = doc.numero_pourvoi
                    if doc.date_decision:
                        payload["date_decision"] = doc.date_decision.isoformat()
                    payload["solution"] = doc.solution
                    payload["publication"] = doc.publication

                points.append(
                    PointStruct(
                        id=point_id,
                        vector={
                            "dense": dense_emb,
                            "sparse-bm25": sparse_vec,
                        },
                        payload=payload,
                    )
                )

            # 9. Upsert NEW chunks into Qdrant (batch by 100)
            batch_size = 100
            for i in range(0, len(points), batch_size):
                self.qdrant.upsert(
                    collection_name=COLLECTION_NAME,
                    points=points[i : i + batch_size],
                )
            await self._update_progress(doc, db, 95)

            # 10. Delete OLD chunks (insert-then-swap: old data stays intact until new is in)
            self._cleanup_old_chunks(str(doc.id), set(new_point_ids))

            # 11. Update status to indexed
            duration_ms = int((time.time() - start_time) * 1000)
            doc.indexation_status = "indexed"
            doc.indexation_duration_ms = duration_ms
            doc.chunk_count = len(chunks)
            doc.indexation_progress = 100
            doc.indexation_error = None
            await db.commit()
            logger.info(
                "Document %s indexed successfully (%d chunks, %dms)",
                document_id,
                len(chunks),
                duration_ms,
            )

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.exception("Failed to index document %s (%dms)", document_id, duration_ms)
            doc.indexation_status = "error"
            doc.indexation_duration_ms = duration_ms
            doc.indexation_error = str(exc)[:500]
            doc.indexation_progress = None
            await db.commit()

    def _cleanup_old_chunks(
        self, document_id: str, new_point_ids: set[str]
    ) -> None:
        """Delete old Qdrant points for a document, keeping only new_point_ids."""
        try:
            old_point_ids: list[str] = []
            offset = None
            while True:
                results, next_offset = self.qdrant.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="document_id",
                                match=MatchValue(value=document_id),
                            )
                        ]
                    ),
                    limit=500,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                for point in results:
                    pid = str(point.id)
                    if pid not in new_point_ids:
                        old_point_ids.append(pid)
                if next_offset is None:
                    break
                offset = next_offset

            if old_point_ids:
                logger.info(
                    "Document %s: deleting %d old chunks from Qdrant",
                    document_id,
                    len(old_point_ids),
                )
                for i in range(0, len(old_point_ids), 500):
                    self.qdrant.delete(
                        collection_name=COLLECTION_NAME,
                        points_selector=old_point_ids[i : i + 500],
                    )
        except Exception:
            logger.warning(
                "Failed to cleanup old Qdrant chunks for document %s",
                document_id,
            )

    @staticmethod
    def _build_jurisprudence_header(doc: Document) -> str:
        """Build a citation header for a court decision (e.g. 'Cass. soc., 15 mars 2023, n° 21-14.490')."""
        parts: list[str] = []
        if doc.juridiction:
            label = doc.juridiction
            if doc.chambre:
                label = f"{label} {doc.chambre}"
            if doc.formation:
                label = f"{label} ({doc.formation})"
            parts.append(label)
        if doc.date_decision:
            parts.append(doc.date_decision.strftime("%d/%m/%Y"))
        if doc.numero_pourvoi:
            parts.append(f"n° {doc.numero_pourvoi}")
        return ", ".join(parts) if parts else ""
