import asyncio
import hashlib
import json
import logging
import math
import re
import time
import uuid

import httpx
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.rag.article_chunker import ArticleChunker, ChunkWithMeta
from app.rag.chunker import LegalChunker
from app.rag.config import EMBEDDING_MODEL
from app.rag.jurisprudence_chunker import JurisprudenceChunker
from app.rag.lexical_profile import LEXICAL_PROFILES
from app.rag.norme_hierarchy import JURISPRUDENCE_SOURCE_TYPES
from app.rag.qdrant_store import COLLECTION_NAME, ensure_collection, get_qdrant_client
from app.rag.text_cleaner import clean_text
from app.rag.text_extractor import TextExtractor
from app.services.cost_tracker import cost_tracker
from app.services.storage_service import StorageService

# Source types that use article-aware chunking (Codes, CCN and JORF acts)
ARTICLE_AWARE_SOURCE_TYPES = {
    "code_travail",
    "code_travail_reglementaire",
    "code_civil",
    "code_civil_reglementaire",
    "code_procedure_civile",
    "code_penal",
    "code_securite_sociale",
    "code_securite_sociale_reglementaire",
    "code_action_sociale",
    "code_action_sociale_reglementaire",
    "code_sante_publique",
    "code_sante_publique_reglementaire",
    "code_commerce",
    "code_commerce_reglementaire",
    "code_monetaire_financier",
    "code_monetaire_financier_reglementaire",
    "code_general_collectivites_territoriales",
    "code_general_collectivites_territoriales_reglementaire",
    "code_general_impots",
    "code_general_impots_reglementaire",
    "convention_collective_nationale",
    "accord_branche",
    "accord_national_interprofessionnel",
    "loi",
    "ordonnance",
    "decret",
    "arrete",
}

logger = logging.getLogger(__name__)


class StaleDocumentIngestion(RuntimeError):
    """The source has changed/deleted; this job must not publish or update it."""

# Retry config for Voyage AI rate limits
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
EMBEDDING_BATCH_SIZE = 32  # Reduced from 64 to handle large legal code chunks

# --- Date extraction for recency boosting ---
_FRENCH_MONTHS = {
    "janvier": "01",
    "février": "02",
    "mars": "03",
    "avril": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07",
    "août": "08",
    "septembre": "09",
    "octobre": "10",
    "novembre": "11",
    "décembre": "12",
}
_DATE_PATTERN = re.compile(
    r"(?:1er|(\d{1,2}))\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})",
    re.IGNORECASE,
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
    input_type: str | None = None,
) -> list[list[float]]:
    """Get dense embeddings for a single batch (max 128 texts) with retry on 429."""
    url = "https://api.voyageai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES):
        response = await client.post(
            url,
            headers=headers,
            json={
                "input": texts, "model": EMBEDDING_MODEL,
                **({"input_type": input_type} if input_type else {}),
            },
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
                    batch,
                    api_key,
                    client,
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
    progress_callback=None,
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
    # Progress commits refresh the ORM object while other batches are running.
    # Snapshot source metadata before concurrency; an expired attribute cannot
    # be loaded implicitly from an async SQLAlchemy session.
    input_type = "document" if doc.storage_path.startswith("common/dila/inca/") else None

    async def _process_batch(batch_idx: int, client: httpx.AsyncClient) -> None:
        nonlocal done_count
        start = batch_idx * EMBEDDING_BATCH_SIZE
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        async with semaphore:
            results[batch_idx] = await _get_embeddings_batch(
                batch,
                api_key,
                client,
                organisation_id=org_id_str,
                document_id=doc_id_str,
                user_id=user_id_str,
                input_type=input_type,
            )
        async with db_lock:
            done_count += 1
            # Update progress: 15% → 80% proportional to batches done
            progress = 15 + int(65 * done_count / total_batches)
            if progress_callback is not None:
                await progress_callback(progress)
            else:
                doc.indexation_progress = progress
                await db.commit()

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_process_batch(i, client) for i in range(total_batches)])

    # Flatten results in order
    all_embeddings: list[list[float]] = []
    for batch_result in results:
        all_embeddings.extend(batch_result)
    return all_embeddings


def _get_sparse_vectors(texts: list[str], profile_name: str = "legacy-en") -> list[dict]:
    """Get BM25 sparse vectors using fastembed (cached singleton model)."""
    from app.rag.search import _get_sparse_model

    model = _get_sparse_model(profile_name)
    results = list(model.embed(texts))
    sparse_vectors = []
    for embedding in results:
        sparse_vectors.append(
            {
                "indices": embedding.indices.tolist(),
                "values": embedding.values.tolist(),
            }
        )
    return sparse_vectors


class IngestionPipeline:
    """Pipeline d'ingestion de documents dans Qdrant."""

    embedding_provider = None

    def __init__(self, embedding_provider=None, *, storage=None, qdrant_client=None) -> None:
        self.extractor = TextExtractor()
        self.chunker = LegalChunker()
        self.article_chunker = ArticleChunker()
        self.jurisprudence_chunker = JurisprudenceChunker()
        self.storage = storage if storage is not None else StorageService()
        self.qdrant = qdrant_client if qdrant_client is not None else get_qdrant_client()
        self.embedding_provider = embedding_provider
        if qdrant_client is None:
            ensure_collection(self.qdrant)

    async def _update_progress(self, doc: Document, db: AsyncSession, progress: int) -> None:
        await self._update_current(doc, db, indexation_progress=progress)

    def _current_source_conditions(self):
        doc_id, path, digest = self._ingestion_source
        return (Document.id == doc_id, Document.storage_path == path, Document.file_hash == digest)

    async def _update_current(self, doc: Document, db: AsyncSession, **values) -> None:
        result = await db.execute(
            update(Document).where(*self._current_source_conditions()).values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await db.rollback()
            raise StaleDocumentIngestion("source_version_changed")
        await db.commit()
        # Refresh through SQLAlchemy after the guarded commit, not dirty assignments
        # that could later flush an old status over a replacement.
        await db.refresh(doc)

    async def _lock_publication(self, db: AsyncSession) -> None:
        current = (await db.execute(
            select(Document.id).where(*self._current_source_conditions()).with_for_update()
        )).first()
        if current is None:
            raise StaleDocumentIngestion("source_version_changed")

    async def ingest(self, document_id: uuid.UUID, db: AsyncSession,
                     expected_source: str | None = None,
                     max_embedding_tokens: int | None = None) -> None:
        # 1. Load document from PostgreSQL
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            logger.error("Document %s not found in DB", document_id)
            return

        if expected_source is not None and doc.storage_path != expected_source:
            logger.info("Ignoring obsolete queued ingestion for document %s", document_id)
            return
        self._ingestion_source = (doc.id, doc.storage_path, doc.file_hash)

        start_time = time.time()

        try:
            # 2. Update status to indexing
            await self._update_current(doc, db, indexation_status="indexing", indexation_progress=0)

            # 3. Download from MinIO
            file_bytes = self.storage.get_file_bytes(doc.storage_path)
            await self._update_progress(doc, db, 5)

            # 4. Extract text
            from app.services.social_ca_source import CA_SOURCE_PREFIX, verified_ca_source

            ca_source = (
                doc.organisation_id is None
                and doc.source_type == "arret_cour_appel"
                and doc.file_format == "txt"
                and doc.storage_path.startswith(CA_SOURCE_PREFIX)
            )
            ca_metadata = {}
            if ca_source:
                sidecar = self.storage.get_file_bytes_bounded(
                    doc.storage_path + ".source.json", 64 * 1024 * 1024
                )
                sealed_source = verified_ca_source(doc, file_bytes, sidecar)
                raw_text = sealed_source.text
                ca_metadata = sealed_source.metadata()
            else:
                raw_text = await self._extract_document_text(doc, file_bytes, db)
            await self._update_progress(doc, db, 10)

            # 5. Clean text
            from app.services.dila_cass_service import SOURCE_PREFIXES, source_chunks

            dila_source = (
                doc.organisation_id is None
                and doc.source_type == "arret_cour_cassation"
                and doc.file_format == "xml"
                and doc.storage_path.startswith(SOURCE_PREFIXES)
            )
            lossless_source = dila_source or ca_source
            cleaned_text = raw_text if lossless_source else clean_text(raw_text)
            dila_metadata = {}
            if dila_source:
                from app.services.dila_cass_service import INCA_RECONCILED_PREFIX
                from app.services.dila_jurisprudence_metadata import source_metadata

                reference_reconciliation = None
                if doc.storage_path.startswith(INCA_RECONCILED_PREFIX):
                    identity_bytes = self.storage.get_file_bytes_bounded(
                        doc.storage_path + ".identity.json", 256 * 1024
                    )
                    expected_identity_hash = doc.storage_path.rsplit("/", 1)[-1][:-4].split(".")[-1]
                    if hashlib.sha256(identity_bytes).hexdigest() != expected_identity_hash:
                        raise ValueError("Source-reference reconciliation artifact changed")
                    reference_reconciliation = json.loads(identity_bytes)
                dila_metadata = source_metadata(
                    file_bytes, reference_reconciliation=reference_reconciliation
                )
                if dila_metadata["source_xml_sha256"] != doc.file_hash:
                    raise ValueError("DILA source hash differs from document metadata")
                from app.services.document_case_references import store_case_references

                await store_case_references(db, doc, dila_metadata["numero_pourvois"])

            if not cleaned_text.strip():
                logger.warning("Document %s: no text extracted", document_id)
                await self._update_current(doc, db, indexation_status="error",
                                           indexation_error="Aucun texte extrait du document",
                                           indexation_progress=None)
                return

            # 6. Chunk (route to specialized chunker by source type)
            chunks_meta: list[ChunkWithMeta] | None = None
            if lossless_source:
                # All source characters and complete table structures survive reindexing.
                header = self._build_jurisprudence_header(doc) + "\n\n"
                chunks = [header + part for part in source_chunks(cleaned_text)]
            elif doc.source_type in JURISPRUDENCE_SOURCE_TYPES:
                metadata_header = self._build_jurisprudence_header(doc)
                chunks = self.jurisprudence_chunker.chunk(
                    cleaned_text,
                    metadata_header=metadata_header,
                )
            elif doc.source_type in ARTICLE_AWARE_SOURCE_TYPES:
                chunks_meta = self.article_chunker.chunk_with_meta(cleaned_text)
                chunks = [c.text for c in chunks_meta]
            else:
                chunks = self.chunker.chunk(cleaned_text)
            if not chunks:
                logger.warning("Document %s: no chunks produced", document_id)
                await self._update_current(doc, db, indexation_status="error",
                                           indexation_error="Aucun chunk produit après extraction du texte",
                                           indexation_progress=None)
                return

            chunk_char_lengths = [len(c) for c in chunks]
            total_chars = sum(chunk_char_lengths)
            logger.info(
                "Document %s: %d chunks produced — total_chars=%d, min=%d, max=%d, avg=%d",
                document_id,
                len(chunks),
                total_chars,
                min(chunk_char_lengths),
                max(chunk_char_lengths),
                total_chars // len(chunks),
            )
            await self._update_progress(doc, db, 15)

            if max_embedding_tokens is not None:
                import tiktoken
                encoder = tiktoken.get_encoding("cl100k_base")
                tokens = sum(len(encoder.encode(c, disallowed_special=())) for c in chunks)
                if tokens > max_embedding_tokens or max_embedding_tokens < 1:
                    raise ValueError("Source maintenance embedding budget exceeded")

            # 7. Generate embeddings (dense + sparse) — 15% → 80%
            embedding_provider = self.embedding_provider or _get_embeddings_with_progress
            dense_embeddings = await embedding_provider(
                chunks, settings.voyage_api_key, doc, db,
                progress_callback=lambda progress: self._update_progress(doc, db, progress),
            )
            sparse_vectors = _get_sparse_vectors(chunks)
            # When both fields exist in the destination, keep both profiles
            # available after cutover. No query vector is compared against a
            # corpus encoded in a different language.
            sparse_fields = self.qdrant.get_collection(
                COLLECTION_NAME,
            ).config.params.sparse_vectors or {}
            extra_sparse = {
                profile.vector_name: _get_sparse_vectors(chunks, name)
                for name, profile in LEXICAL_PROFILES.items()
                if name != "legacy-en" and profile.vector_name in sparse_fields
            }
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
                from app.rag.chunker import contains_markdown_table

                payload = {
                    "text": chunk_text,
                    "organisation_id": org_id_str,
                    "private": bool(doc.private_dossier_id or doc.private_conversation_id),
                    "document_id": str(doc.id),
                    "doc_name": doc.name,
                    "source_type": doc.source_type,
                    "norme_niveau": doc.norme_niveau,
                    "norme_poids": doc.norme_poids,
                    "chunk_index": i,
                    "has_table": contains_markdown_table(chunk_text) or (
                        lossless_source and "<table" in chunk_text
                    ),
                }
                if dila_source:
                    payload.update(dila_metadata)
                if ca_source:
                    payload.update(ca_metadata)
                # Propagate CCN IDCC + article metadata into Qdrant payload
                if doc.source_type in ARTICLE_AWARE_SOURCE_TYPES:
                    idcc_match = re.search(r"IDCC\s+(\d{4})", doc.name)
                    if idcc_match:
                        payload["idcc"] = idcc_match.group(1)
                    # Extract most recent date from chunk for recency boosting
                    content_date = _extract_content_date(chunk_text)
                    if content_date:
                        payload["content_date"] = content_date
                    # Structural metadata from ArticleChunker
                    if chunks_meta:
                        meta = chunks_meta[i]
                        from app.rag.article_chunker import ARTICLE_METADATA_FIELDS

                        for key in ARTICLE_METADATA_FIELDS:
                            value = getattr(meta, key)
                            if value:
                                payload[key] = value
                        if meta.article_nums:
                            payload["article_nums"] = meta.article_nums
                        if meta.section_path:
                            payload["section_path"] = meta.section_path
                        if meta.instrument_id:
                            payload["instrument_id"] = meta.instrument_id
                        if meta.instrument_title:
                            payload["instrument_title"] = meta.instrument_title
                        if meta.effective_from:
                            payload["effective_from"] = meta.effective_from
                            # A reliable parent date is preferable to a date
                            # guessed from the body of a salary table.
                            payload["content_date"] = meta.effective_from
                        if meta.effective_to:
                            payload["effective_to"] = meta.effective_to
                        if meta.instrument_status:
                            payload["instrument_status"] = meta.instrument_status

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
                            **{name: vectors[i] for name, vectors in extra_sparse.items()},
                        },
                        payload=payload,
                    )
                )

            # 9. Upsert NEW chunks into Qdrant (batch by 100)
            # Replacement/deletion cannot commit while this short publication
            # transaction runs. No intermediate progress commit releases its lock.
            await self._lock_publication(db)
            batch_size = 100
            for i in range(0, len(points), batch_size):
                self.qdrant.upsert(
                    collection_name=COLLECTION_NAME,
                    points=points[i : i + batch_size],
                )

            # 10. Delete OLD chunks (insert-then-swap: old data stays intact until new is in)
            self._cleanup_old_chunks(str(doc.id), set(new_point_ids), strict=True)

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
            from app.services.document_extraction_service import ExtractionError

            if (isinstance(exc, StaleDocumentIngestion)
                    or isinstance(exc, ExtractionError) and str(exc) == "source_version_changed"):
                await db.rollback()
                logger.warning(
                    "Extraction cancelled: document %s changed during ingestion", document_id,
                )
                return
            duration_ms = int((time.time() - start_time) * 1000)
            logger.exception("Failed to index document %s (%dms)", document_id, duration_ms)
            await db.rollback()
            try:
                await self._update_current(
                    doc, db, indexation_status="error", indexation_duration_ms=duration_ms,
                    indexation_error=str(exc)[:500], indexation_progress=None,
                )
            except StaleDocumentIngestion:
                logger.info("Discarded error from obsolete job for document %s", document_id)

    async def _extract_document_text(
        self, doc: Document, file_bytes: bytes, db: AsyncSession,
    ) -> str:
        if not settings.document_extraction_enabled_for(doc.organisation_id):
            return self.extractor.extract(file_bytes, doc.file_format or "pdf")
        from app.services.document_extraction_service import (
            DocumentExtractionService,
            SourceSnapshot,
        )

        return await DocumentExtractionService(db, self.storage).extract(
            SourceSnapshot.from_document(doc), file_bytes, self.extractor,
        )

    def _cleanup_old_chunks(self, document_id: str, new_point_ids: set[str],
                            strict: bool = False) -> None:
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
            if strict:
                raise
            logger.warning(
                "Failed to cleanup old Qdrant chunks for document %s",
                document_id,
            )

    @staticmethod
    def _build_jurisprudence_header(doc: Document) -> str:
        """Build the citation header displayed for a court decision."""
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
