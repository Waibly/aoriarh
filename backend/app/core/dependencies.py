import uuid

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.account import Account
from app.models.membership import Membership
from app.models.user import User

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise",
        )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def verify_org_membership(
    organisation_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> Membership | None:
    """Return the membership if user belongs to org, else None.
    Admins always bypass (returns None, caller must handle).
    """
    if user.role == "admin":
        return None
    result = await db.execute(
        select(Membership).where(
            Membership.organisation_id == organisation_id,
            Membership.user_id == user.id,
        )
    )
    return result.scalar_one_or_none()


def require_org_role(allowed_org_roles: list[str]):
    """Check that current user has one of the allowed roles in the organisation.
    Admin global role always passes.
    """

    async def checker(
        organisation_id: uuid.UUID = Path(...),
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if user.role == "admin":
            return user
        membership = await verify_org_membership(organisation_id, user, db)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas membre de cette organisation",
            )
        if membership.role_in_org not in allowed_org_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Rôle insuffisant dans cette organisation",
            )
        return user

    return checker


def require_role(allowed_roles: list[str]):
    """Check global user role (admin/manager/user)."""

    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Rôle insuffisant",
            )
        return user

    return role_checker


async def require_account_owner(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Account]:
    """Verify user owns an account. Returns (user, account)."""
    if user.role == "admin":
        # Admin can act on behalf — but needs an account_id from elsewhere
        # For now, admins without owned_account are rejected
        pass

    result = await db.execute(
        select(Account).where(Account.owner_id == user.id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous devez être propriétaire d'un compte pour accéder à cette ressource",
        )
    return user, account
