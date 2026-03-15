from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.account import Account
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.user import PasswordChange, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    organisation_id: str | None = Query(None, description="Current org to resolve plan/workspace"),
) -> UserRead:
    # Resolve plan and workspace from the current organisation's Account
    plan = None
    plan_expires_at = None
    workspace_name = None
    workspace_id = None

    # If an organisation is specified, find its parent Account
    if organisation_id:
        org_result = await db.execute(
            select(Organisation).where(Organisation.id == organisation_id)
        )
        org = org_result.scalar_one_or_none()
        if org and org.account_id:
            acc_result = await db.execute(
                select(Account).where(Account.id == org.account_id)
            )
            account = acc_result.scalar_one_or_none()
            if account:
                plan = account.plan
                plan_expires_at = account.plan_expires_at
                workspace_name = account.name
                workspace_id = account.id

    # Fallback: user's own account
    if plan is None and user.owned_account:
        plan = user.owned_account.plan
        plan_expires_at = user.owned_account.plan_expires_at
        workspace_name = user.owned_account.name
        workspace_id = user.owned_account.id

    # Fallback: first team account membership
    if plan is None and user.account_memberships:
        team_account_id = user.account_memberships[0].account_id
        acc_result = await db.execute(
            select(Account).where(Account.id == team_account_id)
        )
        team_acc = acc_result.scalar_one_or_none()
        if team_acc:
            plan = team_acc.plan
            plan_expires_at = team_acc.plan_expires_at
            if not workspace_name:
                workspace_name = team_acc.name
                workspace_id = team_acc.id

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
        workspace_name=workspace_name,
        workspace_id=workspace_id,
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


class WorkspaceRename(BaseModel):
    name: str


@router.put("/me/workspace")
async def rename_workspace(
    data: WorkspaceRename,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.owned_account:
        raise HTTPException(status_code=403, detail="Vous n'êtes pas propriétaire d'un espace de travail")
    user.owned_account.name = data.name.strip()
    await db.commit()
    return {"detail": "Espace de travail renommé", "name": user.owned_account.name}


class DeleteAccountConfirmation(BaseModel):
    confirmation: str


@router.delete("/me")
async def delete_own_account(
    body: DeleteAccountConfirmation,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete the current user's own account and all associated data.

    If the user owns an Account (manager), all organisations under that
    account will also be deleted (documents, vectors, conversations, etc.).

    Requires body: {"confirmation": "SUPPRIMER MON COMPTE"}
    """
    if body.confirmation != "SUPPRIMER MON COMPTE":
        raise HTTPException(
            status_code=400,
            detail="Veuillez confirmer en envoyant 'SUPPRIMER MON COMPTE'",
        )

    service = UserService(db)
    await service.delete_own_account(user)
    return {"detail": "Compte supprimé"}
