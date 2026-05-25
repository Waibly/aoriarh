import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.plan_invitation import (
    PlanInvitationRedeemResponse,
    PlanInvitationValidateResponse,
)
from app.services.plan_invitation_service import PlanInvitationService

router = APIRouter()


@router.get(
    "/plan-invitations/{token}/validate",
    response_model=PlanInvitationValidateResponse,
)
async def validate_plan_invitation(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PlanInvitationValidateResponse:
    service = PlanInvitationService(db)
    result = await service.validate_token(token)
    return PlanInvitationValidateResponse(**result)


@router.post(
    "/plan-invitations/{token}/redeem",
    response_model=PlanInvitationRedeemResponse,
)
async def redeem_plan_invitation(
    token: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlanInvitationRedeemResponse:
    service = PlanInvitationService(db)
    result = await service.redeem(token, user)
    return PlanInvitationRedeemResponse(**result)
