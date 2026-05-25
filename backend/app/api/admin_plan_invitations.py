import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.user import User
from app.schemas.plan_invitation import (
    PlanInvitationCreate,
    PlanInvitationDetail,
    PlanInvitationRead,
    RedemptionItem,
)
from app.services.plan_invitation_service import PlanInvitationService

router = APIRouter()


def _inv_to_dict(inv) -> dict:
    return {
        "id": inv.id,
        "token": inv.token,
        "label": inv.label,
        "plan": inv.plan,
        "duration_months": inv.duration_months,
        "email": inv.email,
        "max_uses": inv.max_uses,
        "use_count": inv.use_count,
        "status": inv.status,
        "expires_at": inv.expires_at,
        "created_at": inv.created_at,
    }


def _to_read(inv, service: PlanInvitationService) -> PlanInvitationRead:
    data = _inv_to_dict(inv)
    data["shareable_url"] = service.build_shareable_url(inv)
    return PlanInvitationRead(**data)


@router.post("", response_model=PlanInvitationRead, status_code=status.HTTP_201_CREATED)
async def create_plan_invitation(
    data: PlanInvitationCreate,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> PlanInvitationRead:
    service = PlanInvitationService(db)
    invitation = await service.create(
        label=data.label,
        plan=data.plan,
        duration_months=data.duration_months,
        created_by=user.id,
        email=data.email,
        max_uses=data.max_uses,
        expires_in_days=data.expires_in_days,
    )
    return _to_read(invitation, service)


@router.get("", response_model=dict)
async def list_plan_invitations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = PlanInvitationService(db)
    items, total = await service.list_all(page, page_size, status_filter)
    return {
        "items": [_to_read(inv, service) for inv in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{invitation_id}", response_model=PlanInvitationDetail)
async def get_plan_invitation(
    invitation_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> PlanInvitationDetail:
    service = PlanInvitationService(db)
    detail = await service.get_detail(invitation_id)
    inv = detail["invitation"]
    data = _inv_to_dict(inv)
    data["shareable_url"] = service.build_shareable_url(inv)
    data["redemptions"] = [RedemptionItem(**r) for r in detail["redemptions"]]
    return PlanInvitationDetail(**data)


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_plan_invitation(
    invitation_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = PlanInvitationService(db)
    await service.revoke(invitation_id)
