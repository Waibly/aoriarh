"""API routes pour la gestion des conventions collectives."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_org_role, require_role
from app.models.user import User
from app.schemas.ccn import (
    CcnReferenceRead,
    CcnSearchResult,
    InstallConventionRequest,
    OrganisationConventionRead,
)
from app.services.billing_service import BillingService
from app.services.ccn_service import CcnService

router = APIRouter()


# --- CCN Reference (public search) ---


@router.get("/search", response_model=CcnSearchResult)
async def search_ccn(
    q: str = Query("", description="Recherche par nom ou IDCC"),
    limit: int = Query(20, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CcnSearchResult:
    """Search available conventions collectives by name or IDCC."""
    service = CcnService(db)
    results = await service.search_ccn(q, limit)
    return CcnSearchResult(
        results=[CcnReferenceRead.model_validate(r) for r in results],
        total=len(results),
    )


# --- Organisation conventions ---


@router.get(
    "/organisations/{organisation_id}",
    response_model=list[OrganisationConventionRead],
)
async def list_org_conventions(
    organisation_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager", "user"])),
    db: AsyncSession = Depends(get_db),
) -> list[OrganisationConventionRead]:
    """List installed conventions for an organisation."""
    service = CcnService(db)
    items = await service.list_org_conventions(organisation_id)
    return [OrganisationConventionRead.from_orm_with_ccn(item) for item in items]


@router.post(
    "/organisations/{organisation_id}",
    response_model=OrganisationConventionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def install_convention(
    organisation_id: uuid.UUID,
    body: InstallConventionRequest,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> OrganisationConventionRead:
    """Install a convention collective for an organisation."""
    if user.role != "admin":
        billing = BillingService(db)
        account = await billing.get_account_for_organisation(organisation_id)
        billing.ensure_plan_active(account)
        from app.models.organisation import Organisation
        org = await db.get(Organisation, organisation_id)
        if org is not None:
            await billing.check_ccn_limit(org)

    service = CcnService(db)
    org_conv = await service.install_convention(organisation_id, body.idcc, user.id)
    return OrganisationConventionRead.from_orm_with_ccn(org_conv)


@router.delete(
    "/organisations/{organisation_id}/{idcc}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_convention(
    organisation_id: uuid.UUID,
    idcc: str,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a convention from an organisation."""
    service = CcnService(db)
    await service.remove_convention(organisation_id, idcc)


@router.post(
    "/organisations/{organisation_id}/{idcc}/sync",
    response_model=OrganisationConventionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_convention(
    organisation_id: uuid.UUID,
    idcc: str,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> OrganisationConventionRead:
    """Force re-sync of an installed convention."""
    service = CcnService(db)
    org_conv = await service.sync_convention(organisation_id, idcc, user.id)
    return OrganisationConventionRead.from_orm_with_ccn(org_conv)


# --- Admin ---


@router.post("/admin/refresh-reference", status_code=status.HTTP_200_OK)
async def refresh_ccn_reference(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Refresh the CCN reference table from the KALI API (admin only)."""
    from app.services.kali_service import KaliService

    service = KaliService()
    count = await service.refresh_ccn_reference(db)
    return {"refreshed": count}


@router.post("/admin/seed-reference", status_code=status.HTTP_200_OK)
async def seed_ccn_reference(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Seed the CCN reference table from static data (no API call, admin only)."""
    from app.services.kali_service import KaliService

    count = await KaliService.seed_ccn_reference(db)
    return {"seeded": count}
