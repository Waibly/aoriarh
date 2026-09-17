"""Technical recovery, never response/content repair. No bucket-wide deletion."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.storage_operation import StorageOperation
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


async def finish_storage_io(awaitable):
    """Keep the publication lock until a storage write really finishes on cancellation.

    Cancelling asyncio.to_thread does not stop its underlying PUT. Releasing the
    SQL lock early could let recovery delete the object BEFORE that late PUT.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Repeated cancellation (e.g. request cancellation then worker shutdown)
        # must not release the lock while the underlying thread is still writing.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            task.exception()  # Consume a transport exception; cancellation still propagates.
        raise


class StorageOperationService:
    def __init__(self, db: AsyncSession, storage: StorageService):
        self.db = db
        self.storage = storage

    async def reserve(self, document_id: uuid.UUID, path: str, purpose: str) -> uuid.UUID:
        operation = StorageOperation(
            id=uuid.uuid4(),
            document_id=document_id,
            target_path=path,
            purpose=purpose,
            status="writing",
            attempts=0,
        )
        self.db.add(operation)
        # Must exist DURABLY before the PUT; caller rechecks its source afterwards.
        await self.db.commit()
        return operation.id

    async def lock_write(self, operation_id: uuid.UUID) -> StorageOperation:
        operation = (
            await self.db.execute(
                select(StorageOperation)
                .where(StorageOperation.id == operation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if operation.status != "writing":
            raise RuntimeError("storage_write_reservation_expired")
        return operation

    async def schedule_delete(self, document_id: uuid.UUID, path: str) -> uuid.UUID:
        operation = (
            await self.db.execute(
                select(StorageOperation)
                .where(StorageOperation.target_path == path)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if operation is None:
            operation = StorageOperation(
                id=uuid.uuid4(),
                document_id=document_id,
                target_path=path,
                purpose="retired_source",
                attempts=0,
            )
            self.db.add(operation)
        operation.status = "delete_pending"
        operation.error_code = None
        # The owning document mutation and this intent commit together.
        await self.db.flush()
        return operation.id

    async def recover(
        self,
        *,
        limit: int = 25,
        grace_seconds: int = 600,
        operation_ids: list[uuid.UUID] | None = None,
    ) -> dict:
        if not 1 <= limit <= 100 or grace_seconds < 0:
            raise ValueError("invalid_recovery_budget")
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
        eligible = or_(
            StorageOperation.status == "delete_pending",
            and_(
                StorageOperation.status == "writing",
                StorageOperation.created_at < cutoff,
            ),
        )
        query = select(StorageOperation.id).where(eligible, StorageOperation.attempts < 5)
        if operation_ids is not None:
            query = query.where(StorageOperation.id.in_(operation_ids))
        ids = (
            (await self.db.execute(query.order_by(StorageOperation.created_at).limit(limit)))
            .scalars()
            .all()
        )
        await self.db.commit()
        summary = dict(deleted=0, retained=0, failed=0, skipped=0)
        for operation_id in ids:
            operation = (
                await self.db.execute(
                    select(StorageOperation)
                    .where(
                        StorageOperation.id == operation_id, eligible, StorageOperation.attempts < 5
                    )
                    .with_for_update(skip_locked=True)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if operation is None:
                await self.db.rollback()
                summary["skipped"] += 1
                continue
            source = (
                await self.db.execute(
                    select(Document.id)
                    .where(
                        Document.storage_path == operation.target_path,
                    )
                    .limit(1)
                )
            ).first()
            extraction = (
                await self.db.execute(
                    select(DocumentExtraction.id)
                    .where(
                        DocumentExtraction.text_storage_path == operation.target_path,
                    )
                    .limit(1)
                )
            ).first()
            if source or extraction:
                if operation.status == "writing":
                    operation.status = "retained"
                else:
                    # Quarantine a contradictory deletion intent; do not let it
                    # occupy the first recovery batch forever or delete live data.
                    operation.status = "blocked_reference"
                    logger.error("Storage deletion blocked by live reference: %s", operation.id)
                operation.error_code = "still_referenced"
                await self.db.commit()
                summary["retained"] += 1
                continue
            operation.attempts += 1
            try:
                await finish_storage_io(
                    asyncio.to_thread(self.storage.delete_file, operation.target_path)
                )
            except Exception:
                operation.status = "delete_pending"
                operation.error_code = "storage_delete_failed"
                if operation.attempts >= 5:
                    operation.error_code = "storage_delete_exhausted"
                    logger.error("Storage deletion exhausted its retry budget: %s", operation.id)
                summary["failed"] += 1
            else:
                # The object no longer needs recovery. Do not retain its filename
                # or owner identifier indefinitely after successful erasure.
                await self.db.delete(operation)
                summary["deleted"] += 1
            await self.db.commit()
        return summary


async def queue_storage_delete(
    db: AsyncSession, storage: StorageService, document_id: uuid.UUID, path: str
) -> None:
    operation_id = await StorageOperationService(db, storage).schedule_delete(document_id, path)
    db.info.setdefault("storage_cleanup_ids", []).append(operation_id)


async def finish_pending_storage_deletes(db: AsyncSession, storage: StorageService) -> dict:
    """Run only AFTER the owning deletion commits. Failures remain in the journal."""
    operation_ids = list(dict.fromkeys(db.info.pop("storage_cleanup_ids", [])))
    if not operation_ids:
        return dict(deleted=0, retained=0, failed=0, skipped=0, pending=0)
    summary = await StorageOperationService(db, storage).recover(
        limit=100,
        operation_ids=operation_ids,
    )
    pending = (
        (
            await db.execute(
                select(StorageOperation.id).where(
                    StorageOperation.id.in_(operation_ids),
                    StorageOperation.status != "deleted",
                )
            )
        )
        .scalars()
        .all()
    )
    summary["pending"] = len(pending)
    await db.commit()
    if pending:
        logger.warning("Physical storage erasure incomplete: %d operations pending", len(pending))
    return summary
