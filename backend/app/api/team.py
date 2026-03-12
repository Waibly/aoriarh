import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_account_owner
from app.models.account import Account
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.account_member import (
    AccountInvitationCreate,
    AccountMemberRead,
    AccountMemberUpdate,
)
from app.schemas.invitation import InvitationRead
from app.schemas.organisation import OrganisationRead
from app.services.account_member_service import AccountMemberService

router = APIRouter()


@router.get("/organisations", response_model=list[OrganisationRead])
async def list_account_organisations(
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> list[OrganisationRead]:
    _, account = owner_data
    result = await db.execute(
        select(Organisation)
        .where(Organisation.account_id == account.id)
        .order_by(Organisation.name)
    )
    return list(result.scalars().all())  # type: ignore[return-value]


@router.get("/members", response_model=list[AccountMemberRead])
async def list_team_members(
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> list[AccountMemberRead]:
    _, account = owner_data
    service = AccountMemberService(db)
    return await service.list_members(account.id)  # type: ignore[return-value]


@router.post(
    "/invite",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
)
async def invite_team_member(
    data: AccountInvitationCreate,
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> InvitationRead:
    user, account = owner_data
    service = AccountMemberService(db)
    invitation = await service.invite_member(account.id, data, user)
    return invitation  # type: ignore[return-value]


@router.delete(
    "/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_team_member(
    member_id: uuid.UUID,
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    _, account = owner_data
    service = AccountMemberService(db)
    await service.remove_member(account.id, member_id)


@router.patch("/members/{member_id}", response_model=AccountMemberRead)
async def update_team_member(
    member_id: uuid.UUID,
    data: AccountMemberUpdate,
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> AccountMemberRead:
    _, account = owner_data
    service = AccountMemberService(db)
    return await service.update_member(account.id, member_id, data)  # type: ignore[return-value]


@router.get("/invitations", response_model=list[InvitationRead])
async def list_team_invitations(
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationRead]:
    _, account = owner_data
    service = AccountMemberService(db)
    return await service.list_invitations(account.id)  # type: ignore[return-value]


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_team_invitation(
    invitation_id: uuid.UUID,
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    _, account = owner_data
    service = AccountMemberService(db)
    await service.cancel_invitation(account.id, invitation_id)


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=InvitationRead,
)
async def resend_team_invitation(
    invitation_id: uuid.UUID,
    owner_data: tuple[User, Account] = Depends(require_account_owner),
    db: AsyncSession = Depends(get_db),
) -> InvitationRead:
    user, account = owner_data
    service = AccountMemberService(db)
    return await service.resend_invitation(account.id, invitation_id, user)  # type: ignore[return-value]
