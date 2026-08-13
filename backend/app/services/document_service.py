import hashlib
import logging
import re
import unicodedata
import uuid
import zipfile
from datetime import date
from io import BytesIO
from pathlib import PurePath

from fastapi import HTTPException, UploadFile, status
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 Mo
MAX_FILE_SIZE_ADMIN = 20 * 1024 * 1024  # 20 Mo

storage = StorageService()

_MAX_ARCHIVE_UNCOMPRESSED = 100 * 1024 * 1024
_MAX_ARCHIVE_RATIO = 100
_MAX_PDF_PAGES = 2_000


def _safe_storage_filename(filename: str | None, file_format: str) -> str:
    raw_name = PurePath(filename or f"document.{file_format}").name
    normalized = unicodedata.normalize("NFKC", raw_name)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("._")
    return (safe[:180] or f"document.{file_format}")


def _invalid_file(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _validate_file_bytes(contents: bytes, file_format: str) -> None:
    if not contents:
        raise _invalid_file("Le fichier est vide")

    if file_format == "pdf":
        if not contents.startswith(b"%PDF-"):
            raise _invalid_file("Le contenu du fichier ne correspond pas à un PDF")
        try:
            import pymupdf

            with pymupdf.open(stream=contents, filetype="pdf") as document:
                if document.needs_pass:
                    raise _invalid_file("Les PDF protégés par mot de passe ne sont pas acceptés")
                if document.page_count == 0 or document.page_count > _MAX_PDF_PAGES:
                    raise _invalid_file("Nombre de pages PDF invalide ou excessif")
        except HTTPException:
            raise
        except Exception as exc:
            raise _invalid_file("Le PDF est invalide ou endommagé") from exc
        return

    if file_format == "docx":
        if not contents.startswith(b"PK"):
            raise _invalid_file("Le contenu du fichier ne correspond pas à un document Word")
        try:
            with zipfile.ZipFile(BytesIO(contents)) as archive:
                infos = archive.infolist()
                names = {info.filename for info in infos}
                if "word/document.xml" not in names:
                    raise _invalid_file("Le document Word est incomplet")
                if any(
                    name.lower().endswith("vbaproject.bin") or "embeddings/" in name.lower()
                    for name in names
                ):
                    raise _invalid_file("Les macros et objets embarqués ne sont pas acceptés")
                total_uncompressed = sum(info.file_size for info in infos)
                total_compressed = max(1, sum(info.compress_size for info in infos))
                if (
                    total_uncompressed > _MAX_ARCHIVE_UNCOMPRESSED
                    or total_uncompressed / total_compressed > _MAX_ARCHIVE_RATIO
                ):
                    raise _invalid_file("Archive Word anormalement compressée")
                for name in names:
                    if name.endswith(".rels"):
                        rels = archive.read(name).lower()
                        if b'targetmode="external"' in rels:
                            raise _invalid_file(
                                "Les liens externes intégrés au document sont interdits"
                            )
                bad_member = archive.testzip()
                if bad_member is not None:
                    raise _invalid_file("Le document Word est endommagé")
        except HTTPException:
            raise
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise _invalid_file("Le document Word est invalide ou endommagé") from exc
        return

    if file_format == "txt":
        if b"\x00" in contents:
            raise _invalid_file("Le fichier texte contient des données binaires")
        try:
            contents.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _invalid_file("Le fichier texte doit être encodé en UTF-8") from exc


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _check_duplicate(
        self,
        file_hash: str,
        org_id: uuid.UUID | None,
    ) -> None:
        if org_id is not None:
            query = select(Document).where(
                Document.organisation_id == org_id,
                Document.file_hash == file_hash,
            )
        else:
            query = select(Document).where(
                Document.organisation_id.is_(None),
                Document.file_hash == file_hash,
            )
        result = await self.db.execute(query)
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ce document existe déjà : {existing.name}",
            )

    async def _upload(
        self,
        file: UploadFile,
        source_type: str,
        user_id: uuid.UUID,
        org_id: uuid.UUID | None,
        *,
        juridiction: str | None = None,
        chambre: str | None = None,
        formation: str | None = None,
        numero_pourvoi: str | None = None,
        date_decision: date | None = None,
        solution: str | None = None,
        publication: str | None = None,
        max_file_size: int = MAX_FILE_SIZE,
    ) -> Document:
        # Validate format
        content_type = file.content_type or ""
        file_format = ALLOWED_FORMATS.get(content_type)
        if not file_format:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Format non supporté. Formats acceptés : PDF, DOCX, TXT",
            )

        # Validate source_type
        hierarchy = DOCUMENT_TYPE_HIERARCHY.get(source_type)
        if not hierarchy:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Type de document invalide",
            )

        # Read file content, compute hash and size
        await file.seek(0)
        contents = await file.read()
        file_size = len(contents)
        if file_size > max_file_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux ({file_size / (1024 * 1024):.1f} Mo). "
                f"Taille maximale : {max_file_size // (1024 * 1024)} Mo",
            )
        _validate_file_bytes(contents, file_format)

        # Reject scanned PDFs (image-only, no text layer) — they cannot be
        # ingested reliably and would degrade RAG quality.
        if file_format == "pdf":
            from app.rag.text_extractor import is_scanned_pdf
            if is_scanned_pdf(contents):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Ce document semble être un PDF scanné (sans couche de texte). "
                        "AORIA RH ne traite pas encore les documents scannés afin de "
                        "garantir la qualité des réponses. Merci de fournir un PDF "
                        "avec texte sélectionnable, un fichier Word (.docx) ou un .txt."
                    ),
                )

        file_hash = hashlib.sha256(contents).hexdigest()

        await self._check_duplicate(file_hash, org_id)

        # Upload to MinIO
        await file.seek(0)
        file_id = uuid.uuid4()
        prefix = str(org_id) if org_id else "common"
        safe_filename = _safe_storage_filename(file.filename, file_format)
        path = f"{prefix}/{file_id}_{safe_filename}"
        await storage.upload_file(file, path)

        # Create DB record
        doc = Document(
            organisation_id=org_id,
            name=file.filename or "document",
            source_type=source_type,
            norme_niveau=hierarchy["niveau"],
            norme_poids=hierarchy["poids"],
            storage_path=path,
            indexation_status="pending",
            uploaded_by=user_id,
            file_size=file_size,
            file_format=file_format,
            file_hash=file_hash,
            juridiction=juridiction,
            chambre=chambre,
            formation=formation,
            numero_pourvoi=numero_pourvoi,
            date_decision=date_decision,
            solution=solution,
            publication=publication,
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def upload_document(
        self,
        file: UploadFile,
        source_type: str,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> Document:
        return await self._upload(file, source_type, user_id, org_id, **kwargs)

    async def list_documents(self, org_id: uuid.UUID) -> list[Document]:
        from sqlalchemy import or_

        from app.models.ccn import OrganisationConvention

        # Get org's installed IDCC list
        idcc_result = await self.db.execute(
            select(OrganisationConvention.idcc).where(
                OrganisationConvention.organisation_id == org_id,
                OrganisationConvention.status.in_(["ready", "indexing", "fetching"]),
            )
        )
        installed_idccs = [row[0] for row in idcc_result.all()]

        # Build filter: org docs + common CCN docs matching installed IDCCs
        conditions = [Document.organisation_id == org_id]
        if installed_idccs:
            # Common CCN docs whose name contains any installed IDCC
            idcc_filters = [
                Document.name.ilike(f"%IDCC {idcc}%")
                for idcc in installed_idccs
            ]
            conditions.append(
                Document.organisation_id.is_(None) & or_(*idcc_filters)
            )

        result = await self.db.execute(
            select(Document)
            .where(or_(*conditions))
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_document(
        self, doc_id: uuid.UUID, org_id: uuid.UUID
    ) -> Document:
        result = await self.db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.organisation_id == org_id,
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document non trouvé")
        return doc

    async def delete_document(
        self, doc_id: uuid.UUID, org_id: uuid.UUID
    ) -> None:
        doc = await self.get_document(doc_id, org_id)
        storage.delete_file(doc.storage_path)
        self._delete_qdrant_chunks(doc_id)
        await self.db.delete(doc)
        await self.db.commit()

    async def get_download_url(
        self, doc_id: uuid.UUID, org_id: uuid.UUID
    ) -> str:
        doc = await self.get_document(doc_id, org_id)
        return storage.get_presigned_url(doc.storage_path)

    # ---- Common documents (admin) ----

    async def upload_common_document(
        self,
        file: UploadFile,
        source_type: str,
        user_id: uuid.UUID,
        **kwargs,
    ) -> Document:
        return await self._upload(file, source_type, user_id, org_id=None, **kwargs)

    async def list_common_documents(self) -> list[Document]:
        result = await self.db.execute(
            select(Document)
            .where(Document.organisation_id.is_(None))
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_common_document(self, doc_id: uuid.UUID) -> Document:
        result = await self.db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.organisation_id.is_(None),
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document commun introuvable",
            )
        return doc

    async def delete_common_document(self, doc_id: uuid.UUID) -> None:
        doc = await self.get_common_document(doc_id)
        storage.delete_file(doc.storage_path)
        self._delete_qdrant_chunks(doc_id)
        await self.db.delete(doc)
        await self.db.commit()

    async def get_common_download_url(self, doc_id: uuid.UUID) -> str:
        doc = await self.get_common_document(doc_id)
        return storage.get_presigned_url(doc.storage_path)

    # ---- Replace (update file, keep same document ID) ----

    async def replace_document(
        self,
        doc_id: uuid.UUID,
        file: UploadFile,
        user_id: uuid.UUID,
        org_id: uuid.UUID | None = None,
        max_file_size: int = MAX_FILE_SIZE,
    ) -> Document:
        """Replace a document's file while keeping the same ID.

        The old Qdrant chunks stay active until the new ingestion completes
        (insert-then-swap handled by IngestionPipeline).
        """
        if org_id is not None:
            doc = await self.get_document(doc_id, org_id)
        else:
            doc = await self.get_common_document(doc_id)

        # Validate format
        content_type = file.content_type or ""
        file_format = ALLOWED_FORMATS.get(content_type)
        if not file_format:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Format non supporté. Formats acceptés : PDF, DOCX, TXT",
            )

        # Read file content
        await file.seek(0)
        contents = await file.read()
        file_size = len(contents)
        if file_size > max_file_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux ({file_size / (1024 * 1024):.1f} Mo). "
                f"Taille maximale : {max_file_size // (1024 * 1024)} Mo",
            )
        _validate_file_bytes(contents, file_format)

        # Reject scanned PDFs (same rule as create_document)
        if file_format == "pdf":
            from app.rag.text_extractor import is_scanned_pdf
            if is_scanned_pdf(contents):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Ce document semble être un PDF scanné (sans couche de texte). "
                        "AORIA RH ne traite pas encore les documents scannés afin de "
                        "garantir la qualité des réponses. Merci de fournir un PDF "
                        "avec texte sélectionnable, un fichier Word (.docx) ou un .txt."
                    ),
                )

        file_hash = hashlib.sha256(contents).hexdigest()

        if file_hash == doc.file_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Le fichier est identique à la version actuelle",
            )

        # Delete old file from MinIO
        old_path = doc.storage_path
        storage.delete_file(old_path)

        # Upload new file to MinIO
        await file.seek(0)
        file_id = uuid.uuid4()
        prefix = str(org_id) if org_id else "common"
        safe_filename = _safe_storage_filename(file.filename, file_format)
        new_path = f"{prefix}/{file_id}_{safe_filename}"
        await storage.upload_file(file, new_path)

        # Update DB record (same document ID)
        doc.name = file.filename or doc.name
        doc.storage_path = new_path
        doc.file_size = file_size
        doc.file_format = file_format
        doc.file_hash = file_hash
        doc.indexation_status = "pending"
        doc.indexation_error = None
        doc.chunk_count = None
        doc.uploaded_by = user_id
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    # ---- Metadata edit ----

    async def update_metadata(
        self,
        doc_id: uuid.UUID,
        org_id: uuid.UUID,
        data: dict,
    ) -> Document:
        """Update human-editable fields on a document. Does not reindex."""
        doc = await self.get_document(doc_id, org_id)

        editable_fields = {
            "name",
            "juridiction",
            "chambre",
            "formation",
            "numero_pourvoi",
            "date_decision",
            "solution",
            "publication",
        }
        for key, value in data.items():
            if key in editable_fields:
                setattr(doc, key, value)

        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    # ---- Reindex ----

    async def reset_for_reindex(
        self, doc_id: uuid.UUID, org_id: uuid.UUID | None = None
    ) -> Document:
        if org_id is not None:
            doc = await self.get_document(doc_id, org_id)
        else:
            doc = await self.get_common_document(doc_id)

        if doc.indexation_status not in ("error", "pending"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seuls les documents en erreur ou en attente peuvent être réindexés",
            )

        # Les anciens chunks Qdrant ne sont plus supprimés ici.
        # Ils seront nettoyés dans IngestionPipeline.ingest() après
        # l'insertion réussie des nouveaux chunks (insert-then-swap).
        doc.indexation_status = "pending"
        doc.indexation_error = None
        doc.chunk_count = None
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    # ---- Qdrant cleanup ----

    @staticmethod
    def _delete_qdrant_chunks(doc_id: uuid.UUID) -> None:
        try:
            client = get_qdrant_client()
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="document_id",
                                match=MatchValue(value=str(doc_id)),
                            )
                        ]
                    )
                ),
            )
        except Exception:
            logger.warning("Failed to delete Qdrant chunks for document %s", doc_id)
