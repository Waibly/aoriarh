from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.account import Account
from app.models.user import User
from app.schemas.user import PasswordChange, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    # Resolve effective plan: team account takes priority over personal account
    plan = None
    plan_expires_at = None

    if user.account_memberships:
        # User is a team member — use the team account's plan
        team_account_id = user.account_memberships[0].account_id
        result = await db.execute(
            select(Account).where(Account.id == team_account_id)
        )
        team_account = result.scalar_one_or_none()
        if team_account:
            plan = team_account.plan
            plan_expires_at = team_account.plan_expires_at

    # Fallback to personal account
    if plan is None and user.owned_account:
        plan = user.owned_account.plan
        plan_expires_at = user.owned_account.plan_expires_at

    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        auth_provider=user.auth_provider,
        profil_metier=user.profil_metier,
        plan=plan,
        plan_expires_at=plan_expires_at,
    )


@router.patch("/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    service = UserService(db)
    return await service.update_profile(user, data)


@router.post("/me/password")
async def change_password(
    data: PasswordChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = UserService(db)
    await service.change_password(user, data)
    return {"detail": "Mot de passe modifié"}
