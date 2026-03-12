import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.account import Account
from app.models.conversation import Conversation, Message
from app.models.invitation import Invitation
from app.models.user import User
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.schemas.account import AccountRead
from app.schemas.organisation import PlanAssign
from app.services.plan_service import assign_plan, resolve_expired_plans

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

    updated = await assign_plan(
        db,
        account_id=account_id,
        plan=body.plan.value,
        duration_months=body.duration_months,
    )
    return AccountRead.model_validate(updated)


@router.delete("/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    _admin: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a user and their related data (memberships, conversations, account)."""
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Impossible de supprimer votre propre compte")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    if user.role == "admin":
        raise HTTPException(status_code=400, detail="Impossible de supprimer un administrateur")

    # 1. Delete messages from user's conversations
    conv_result = await db.execute(
        select(Conversation.id).where(Conversation.user_id == user_id)
    )
    conv_ids = [row[0] for row in conv_result.all()]
    if conv_ids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))

    # 2. Delete conversations
    await db.execute(delete(Conversation).where(Conversation.user_id == user_id))

    # 3. Delete invitations sent by user
    await db.execute(delete(Invitation).where(Invitation.invited_by == user_id))

    # 4. Delete memberships
    await db.execute(delete(Membership).where(Membership.user_id == user_id))

    # 5. Delete account
    if user.owned_account:
        await db.delete(user.owned_account)

    # 6. Delete user
    await db.delete(user)
    await db.commit()

    return {"detail": "Utilisateur supprimé"}
