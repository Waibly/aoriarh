"""Admin: automated quality review of answers (setting, monthly figures, findings)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.conversation import Conversation, Message
from app.models.organisation import Organisation
from app.models.quality_review import QualityFinding, QualityReview
from app.models.user import User
from app.services.audit_service import log_admin_action
from app.services.platform_settings import (
    QualityReviewSettings,
    get_quality_review_settings,
    save_quality_review_settings,
)
from app.services.quality_review.service import REVIEWER_VERSION, month_spend

router = APIRouter()


class QualityReviewOverview(BaseModel):
    settings: QualityReviewSettings
    force_off: bool
    reviewer_version: str
    month_spend_usd: float
    month_reviews: dict[str, int]
    month_findings: dict[str, int]


class QualityFindingItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    organisation_name: str | None
    check: str
    kind: str
    validation: str
    validation_reason: str | None
    answer_excerpt: str
    source_excerpt: str | None
    source_label: str | None
    explanation: str
    proposed_fix: str | None


def _month_start() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _overview(db: AsyncSession) -> QualityReviewOverview:
    start = _month_start()
    reviews = (
        await db.execute(
            select(QualityReview.status, func.count())
            .where(QualityReview.created_at >= start)
            .group_by(QualityReview.status)
        )
    ).all()
    findings = (
        await db.execute(
            select(QualityFinding.validation, func.count())
            .where(QualityFinding.created_at >= start)
            .group_by(QualityFinding.validation)
        )
    ).all()
    return QualityReviewOverview(
        settings=await get_quality_review_settings(db, use_cache=False),
        force_off=settings.quality_review_force_off,
        reviewer_version=REVIEWER_VERSION,
        month_spend_usd=float(await month_spend(db)),
        month_reviews={status: count for status, count in reviews},
        month_findings={validation: count for validation, count in findings},
    )


@router.get("/settings", response_model=QualityReviewOverview)
async def get_settings(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> QualityReviewOverview:
    return await _overview(db)


@router.put("/settings", response_model=QualityReviewOverview)
async def update_settings(
    data: QualityReviewSettings,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> QualityReviewOverview:
    before = await get_quality_review_settings(db, use_cache=False)
    await log_admin_action(
        db,
        user_id=user.id,
        action="quality_review_settings_updated",
        resource_type="platform_setting",
        resource_id="quality_review",
        ip_address=request.client.host if request.client else None,
        details=json.dumps(
            {"before": before.model_dump(), "after": data.model_dump()}, ensure_ascii=False
        ),
    )
    await save_quality_review_settings(db, data, user_id=user.id)
    return await _overview(db)


@router.get("/findings", response_model=list[QualityFindingItem])
async def list_findings(
    validation: Literal["confirmed", "refuted", "unanchored", "unverified", "all"] = "confirmed",
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[QualityFindingItem]:
    query = (
        select(QualityFinding, Message.conversation_id, Organisation.name)
        .join(Message, Message.id == QualityFinding.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(Organisation, Organisation.id == Conversation.organisation_id)
        .order_by(QualityFinding.created_at.desc())
        .limit(limit)
    )
    if validation != "all":
        query = query.where(QualityFinding.validation == validation)
    rows = (await db.execute(query)).all()
    return [
        QualityFindingItem(
            id=finding.id,
            created_at=finding.created_at,
            message_id=finding.message_id,
            conversation_id=conversation_id,
            organisation_name=organisation_name,
            check=finding.check,
            kind=finding.kind,
            validation=finding.validation,
            validation_reason=finding.validation_reason,
            answer_excerpt=finding.answer_excerpt,
            source_excerpt=finding.source_excerpt,
            source_label=finding.source_label,
            explanation=finding.explanation,
            proposed_fix=finding.proposed_fix,
        )
        for finding, conversation_id, organisation_name in rows
    ]
