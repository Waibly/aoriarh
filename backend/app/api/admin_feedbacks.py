from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.models.organisation import Organisation

router = APIRouter()


class FeedbackItem(BaseModel):
    model_config = {"from_attributes": True}

    message_id: str
    user_email: str
    organisation_name: str
    question: str
    answer: str
    feedback: str
    feedback_comment: str | None
    created_at: str


class FeedbackListResponse(BaseModel):
    items: list[FeedbackItem]
    total: int
    page: int
    page_size: int


@router.get("/", response_model=FeedbackListResponse)
async def list_feedbacks(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> FeedbackListResponse:
    """List all messages with feedback, ordered by most recent first."""
    # Count total
    count_q = select(func.count()).select_from(Message).where(
        Message.feedback.isnot(None)
    )
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch paginated results
    offset = (page - 1) * page_size
    stmt = (
        select(Message)
        .where(Message.feedback.isnot(None))
        .options(
            selectinload(Message.conversation).selectinload(Conversation.user),
            selectinload(Message.conversation).selectinload(Conversation.organisation),
        )
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    items: list[FeedbackItem] = []
    for msg in messages:
        conv = msg.conversation
        # Find the user question (previous message in conversation)
        q_stmt = (
            select(Message)
            .where(
                Message.conversation_id == msg.conversation_id,
                Message.role == "user",
                Message.created_at < msg.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        q_result = await db.execute(q_stmt)
        user_msg = q_result.scalar_one_or_none()

        items.append(
            FeedbackItem(
                message_id=str(msg.id),
                user_email=conv.user.email if conv.user else "—",
                organisation_name=conv.organisation.name if conv.organisation else "—",
                question=user_msg.content if user_msg else "—",
                answer=msg.content,
                feedback=msg.feedback,
                feedback_comment=msg.feedback_comment,
                created_at=msg.created_at.isoformat(),
            )
        )

    return FeedbackListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
