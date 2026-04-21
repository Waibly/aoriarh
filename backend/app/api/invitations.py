import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_org_role
from app.models.user import User
from app.schemas.invitation import (
    InvitationCreate,
    InvitationRead,
    InvitationValidateResponse,
)
from app.services.billing_service import BillingService
from app.services.invitation_service import InvitationService

router = APIRouter()


# --- Org-scoped endpoints (manager only) ---


@router.post(
    "/organisations/{organisation_id}/invitations",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    organisation_id: uuid.UUID,
    data: InvitationCreate,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> InvitationRead:
    # Enforce plan user limit on the underlying account.
    if user.role != "admin":
        billing = BillingService(db)
        account = await billing.get_account_for_organisation(organisation_id)
        billing.ensure_plan_active(account)
        await billing.check_user_limit(account)

    service = InvitationService(db)
    invitation = await service.create_invitation(organisation_id, data, user)
    return invitation  # type: ignore[return-value]


@router.get(
    "/organisations/{organisation_id}/invitations",
    response_model=list[InvitationRead],
)
async def list_invitations(
    organisation_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationRead]:
    service = InvitationService(db)
    return await service.list_invitations(organisation_id)  # type: ignore[return-value]


@router.delete(
    "/organisations/{organisation_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_invitation(
    organisation_id: uuid.UUID,
    invitation_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = InvitationService(db)
    await service.cancel_invitation(organisation_id, invitation_id)


@router.post(
    "/organisations/{organisation_id}/invitations/{invitation_id}/resend",
    response_model=InvitationRead,
)
async def resend_invitation(
    organisation_id: uuid.UUID,
    invitation_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> InvitationRead:
    service = InvitationService(db)
    return await service.resend_invitation(organisation_id, invitation_id, user)  # type: ignore[return-value]


# --- Public endpoints (token-based) ---


@router.get(
    "/invitations/{token}/validate",
    response_model=InvitationValidateResponse,
)
async def validate_invitation(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> InvitationValidateResponse:
    service = InvitationService(db)
    return await service.validate_token(token)  # type: ignore[return-value]


@router.post("/invitations/{token}/accept")
async def accept_invitation(
    token: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = InvitationService(db)
    return await service.accept_invitation(token, user)
