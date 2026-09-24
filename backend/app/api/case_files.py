import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.case_file import CaseEvent
from app.models.user import User
from app.schemas.case_file import CaseEntryActionRequest, CaseFileRead, CaseHistoryImport
from app.services.case_file_service import CaseFileService

router = APIRouter()


@router.get("/{conversation_id}/case-file/events")
async def case_file_events(
    conversation_id: uuid.UUID,
    response: Response,
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    case_file, _ = await CaseFileService(db).get_case_file(conversation_id, user)
    rows = list(
        (
            await db.execute(
                select(CaseEvent)
                .where(CaseEvent.case_file_id == case_file.id)
                .order_by(CaseEvent.created_at, CaseEvent.id)
                .offset(offset)
                .limit(51)
            )
        ).scalars()
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "has_more": len(rows) > 50,
        "items": [
            {
                "id": event.id,
                "version": event.case_version,
                "type": event.event_type,
                "created_at": event.created_at,
                "source_message_id": event.source_message_id,
                "raw_planner_output": event.raw_planner_output,
                "structured_delta": event.structured_delta,
                "technical_error": event.technical_error,
            }
            for event in rows[:50]
        ],
    }


@router.post("/{conversation_id}/case-file/import-history", response_model=CaseFileRead)
async def import_case_history(
    conversation_id: uuid.UUID,
    data: CaseHistoryImport,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseFileRead:
    service = CaseFileService(db)
    await service.import_history(
        conversation_id, user, data.message_ids, data.expected_case_version
    )
    case_file, inherited_context = await service.get_case_file(conversation_id, user)
    response.headers["Cache-Control"] = "private, no-store"
    return CaseFileRead.model_validate(service.public_payload(case_file, inherited_context))


@router.get("/{conversation_id}/case-file", response_model=CaseFileRead)
async def get_case_file(
    conversation_id: uuid.UUID,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseFileRead:
    service = CaseFileService(db)
    case_file, inherited_context = await service.get_case_file(conversation_id, user)
    response.headers["Cache-Control"] = "private, no-store"
    return CaseFileRead.model_validate(service.public_payload(case_file, inherited_context))


@router.post(
    "/{conversation_id}/case-file/entries/{entry_id}/revisions",
    response_model=CaseFileRead,
)
async def revise_case_entry(
    conversation_id: uuid.UUID,
    entry_id: uuid.UUID,
    data: CaseEntryActionRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseFileRead:
    service = CaseFileService(db)
    await service.apply_user_entry_action(
        conversation_id=conversation_id,
        entry_id=entry_id,
        expected_version=data.expected_case_version,
        user=user,
        operation=data.operation,
        value_text=data.value,
        comment=data.comment,
    )
    case_file, inherited_context = await service.get_case_file(conversation_id, user)
    response.headers["Cache-Control"] = "private, no-store"
    return CaseFileRead.model_validate(service.public_payload(case_file, inherited_context))
