import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.user import User
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.services.user_service import UserService
from app.models.organisation import Organisation
from app.schemas.account import AccountRead
from app.schemas.organisation import PlanAssign
from app.services.plan_service import PlanOverflowError, assign_plan, resolve_expired_plans

router = APIRouter()


class UserOrgItem(BaseModel):
    model_config = {"from_attributes": True}
    organisation_id: str
    organisation_name: str
    role_in_org: str


class AdminUserItem(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: str
    organisations: list[UserOrgItem]
    account_id: str | None = None
    account_name: str | None = None
    plan: str | None = None
    plan_expires_at: str | None = None


class UserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int
    page: int
    page_size: int


@router.get("/", response_model=UserListResponse)
async def list_users(
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: str | None = Query(None),
) -> UserListResponse:
    """List all users with their organisations."""
    await resolve_expired_plans(db)

    base = select(User)
    count_base = select(func.count()).select_from(User)

    if search:
        pattern = f"%{search}%"
        base = base.where(User.email.ilike(pattern) | User.full_name.ilike(pattern))
        count_base = count_base.where(
            User.email.ilike(pattern) | User.full_name.ilike(pattern)
        )

    total = (await db.execute(count_base)).scalar() or 0

    offset = (page - 1) * page_size
    stmt = (
        base.options(
            selectinload(User.memberships).selectinload(Membership.organisation),
            selectinload(User.owned_account),
        )
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    users = result.scalars().all()

    items: list[AdminUserItem] = []
    for u in users:
        orgs = [
            UserOrgItem(
                organisation_id=str(m.organisation_id),
                organisation_name=m.organisation.name if m.organisation else "—",
                role_in_org=m.role_in_org,
            )
            for m in u.memberships
        ]
        account = u.owned_account
        items.append(
            AdminUserItem(
                id=str(u.id),
                email=u.email,
                full_name=u.full_name,
                role=u.role,
                is_active=u.is_active,
                created_at=u.created_at.isoformat(),
                organisations=orgs,
                account_id=str(account.id) if account else None,
                account_name=account.name if account else None,
                plan=account.plan if account else None,
                plan_expires_at=account.plan_expires_at.isoformat() if account and account.plan_expires_at else None,
            )
        )

    return UserListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.put("/accounts/{account_id}/plan", response_model=AccountRead)
async def update_account_plan(
    account_id: uuid.UUID,
    body: PlanAssign,
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> AccountRead:
    """Assign a plan to an account."""
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account non trouvé")

    try:
        updated = await assign_plan(
            db,
            account_id=account_id,
            plan=body.plan.value,
            duration_months=body.duration_months,
        )
    except PlanOverflowError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"Le plan {body.plan.value} est trop petit pour les données actuelles "
                    "du compte. Supprimez les éléments excédentaires avant de changer de plan."
                ),
                "overflow": exc.reasons,
            },
        ) from exc
    return AccountRead.model_validate(updated)


class RoleUpdate(BaseModel):
    role: str


@router.put("/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    body: RoleUpdate,
    current_user: User = Depends(get_current_user),
    _admin: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change a user's role (admin, manager, user). Admin-only."""
    if body.role not in ("admin", "manager", "user"):
        raise HTTPException(status_code=400, detail="Rôle invalide")

    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Impossible de modifier votre propre rôle")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    user.role = body.role
    await db.commit()
    return {"detail": f"Rôle mis à jour : {body.role}"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    _admin: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a user and their related data.

    Rules:
    - Cannot delete yourself or another admin.
    - If the user owns an Account, ownership is transferred to the next
      manager in the account. If no other manager exists, deletion is blocked.
    - Organisation data (documents, CCN links, Qdrant vectors) is NEVER
      deleted when removing a user — only the user's personal data
      (conversations, messages, memberships) is removed.
    - Common documents (org_id=NULL) are never touched.
    - api_usage_logs are preserved (user_id set to NULL, snapshots kept).
    """
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Impossible de supprimer votre propre compte")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    if user.role == "admin":
        # Allow deleting admins, but ensure at least one remains
        admin_count_q = await db.execute(
            select(func.count(User.id)).where(User.role == "admin")
        )
        if (admin_count_q.scalar() or 0) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Impossible de supprimer le dernier administrateur du système.",
            )

    # If the user owns an account, transfer or full-delete.
    if user.owned_account:
        account = user.owned_account
        other_manager_q = await db.execute(
            select(AccountMember).where(
                AccountMember.account_id == account.id,
                AccountMember.user_id != user_id,
                AccountMember.role_in_org == "manager",
            ).limit(1)
        )
        other_manager = other_manager_q.scalar_one_or_none()
        if other_manager is not None:
            # Another manager exists → transfer ownership, keep everything
            account.owner_id = other_manager.user_id
        else:
            # Last manager → block deletion. The account must be deleted
            # separately (or ownership transferred first).
            raise HTTPException(
                status_code=400,
                detail="Cet utilisateur est le dernier manager du compte. "
                       "Supprimez d'abord le compte ou transférez la propriété à un autre membre.",
            )

    service = UserService(db)
    await service.delete_user_data(user.id)
    await db.commit()

    return {"detail": "Utilisateur supprimé"}


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    _admin: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete an entire client account and all associated data.

    Deletes: all organisations (docs, Qdrant vectors, MinIO files, CCN links,
    conversations, messages, memberships), all account members, the account
    itself, and the owner user.
    Common documents and CCN references are never touched.
    api_usage_logs are preserved (FKs set to NULL).
    """
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Compte non trouvé")

    owner = await db.get(User, account.owner_id)

    # Collect all user IDs in this account (owner + members)
    am_result = await db.execute(
        select(AccountMember.user_id).where(AccountMember.account_id == account_id)
    )
    member_user_ids = {row[0] for row in am_result.all()}
    if owner:
        member_user_ids.add(owner.id)

    # Safety: check we're not deleting ourselves
    if current_user.id in member_user_ids:
        raise HTTPException(
            status_code=400,
            detail="Impossible de supprimer un compte dont vous êtes membre. "
                   "Retirez-vous d'abord du compte.",
        )

    # Safety: if any member is an admin, check at least one admin remains
    admin_in_account = []
    for uid in member_user_ids:
        u = await db.get(User, uid)
        if u and u.role == "admin":
            admin_in_account.append(u)
    if admin_in_account:
        admin_count_q = await db.execute(
            select(func.count(User.id)).where(User.role == "admin")
        )
        total_admins = admin_count_q.scalar() or 0
        if total_admins - len(admin_in_account) < 1:
            raise HTTPException(
                status_code=400,
                detail="La suppression de ce compte supprimerait le dernier administrateur du système.",
            )

    # 1. Delete all organisations in this account (Qdrant, MinIO, docs, etc.)
    from app.services.organisation_service import OrganisationService
    org_service = OrganisationService(db)
    org_result = await db.execute(
        select(Organisation).where(Organisation.account_id == account_id)
    )
    for org in org_result.scalars().all():
        await org_service.delete_organisation(org.id, current_user)

    # 2. Delete account-level invitations and account members, then the
    #    account itself — BEFORE user cleanup so delete_user_data step 8
    #    sees owned_account=None and doesn't try to double-delete.
    await db.execute(
        delete(Invitation).where(Invitation.account_id == account_id)
    )
    await db.execute(
        delete(AccountMember).where(AccountMember.account_id == account_id)
    )
    await db.delete(account)
    await db.flush()

    # 3. Delete all member users' data
    service = UserService(db)
    for uid in member_user_ids:
        await service.delete_user_data(uid)

    await db.commit()
    return {"detail": "Compte client supprimé"}
