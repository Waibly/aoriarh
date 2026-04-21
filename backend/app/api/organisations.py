import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_org_role, require_role
from app.models.user import User
from app.schemas.organisation import (
    MembershipCreate,
    MembershipRead,
    MembershipUpdate,
    OrganisationCreate,
    OrganisationRead,
    OrganisationUpdate,
)
from app.services.billing_service import BillingService
from app.services.organisation_service import OrganisationService

router = APIRouter()


@router.post("/", response_model=OrganisationRead, status_code=status.HTTP_201_CREATED)
async def create_organisation(
    data: OrganisationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganisationRead:
    # Allow: admin, manager (workspace owner), or invited manager in a workspace
    can_create = (
        user.role in ("admin", "manager")
        or any(m.role_in_org == "manager" for m in user.account_memberships)
    )
    if not can_create:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Vous n'avez pas les droits pour créer une organisation")

    # Enforce plan limit on number of organisations per account.
    # Admins (role='admin') are AORIA RH staff and bypass quota checks.
    if user.role != "admin":
        billing = BillingService(db)
        account = await billing.get_primary_account_for_user(user)
        billing.ensure_plan_active(account)
        await billing.check_organisation_limit(account)

    service = OrganisationService(db)
    return await service.create_organisation(data, user)


@router.get("/", response_model=list[OrganisationRead])
async def list_organisations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    service = OrganisationService(db)
    return await service.list_organisations(user)


@router.get("/{organisation_id}", response_model=OrganisationRead)
async def get_organisation(
    organisation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganisationRead:
    service = OrganisationService(db)
    return await service.get_organisation(organisation_id, user)


@router.patch("/{organisation_id}", response_model=OrganisationRead)
async def update_organisation(
    organisation_id: uuid.UUID,
    data: OrganisationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganisationRead:
    service = OrganisationService(db)
    return await service.update_organisation(organisation_id, data, user)


@router.delete("/{organisation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organisation(
    organisation_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = OrganisationService(db)
    await service.delete_organisation(organisation_id, user)


@router.get("/{organisation_id}/members", response_model=list[MembershipRead])
async def list_members(
    organisation_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager", "user"])),
    db: AsyncSession = Depends(get_db),
) -> list:
    service = OrganisationService(db)
    return await service.list_members(organisation_id)


@router.post(
    "/{organisation_id}/members",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    organisation_id: uuid.UUID,
    data: MembershipCreate,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> MembershipRead:
    service = OrganisationService(db)
    return await service.add_member(organisation_id, data)


@router.patch(
    "/{organisation_id}/members/{membership_id}",
    response_model=MembershipRead,
)
async def update_member_role(
    organisation_id: uuid.UUID,
    membership_id: uuid.UUID,
    data: MembershipUpdate,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> MembershipRead:
    service = OrganisationService(db)
    return await service.update_member_role(organisation_id, membership_id, data)


@router.delete(
    "/{organisation_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    organisation_id: uuid.UUID,
    membership_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = OrganisationService(db)
    await service.remove_member(organisation_id, membership_id)
