import logging
import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Path, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.account import Account
from app.models.auth_session import AuthSession
from app.models.membership import Membership
from app.models.user import User

security_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

_ADMIN_BUSINESS_PREFIXES = (
    "/api/v1/admin/business",
    "/api/v1/admin/billing",
    "/api/v1/admin/emailing",
    "/api/v1/admin/linkedin",
    "/api/v1/admin/plan-invitations",
    "/api/v1/admin/users",
    "/api/v1/admin/workspaces",
    "/api/v1/admin/costs",
)
_ADMIN_TECH_PREFIXES = (
    "/api/v1/admin/documents",
    "/api/v1/admin/qdrant",
    "/api/v1/admin/jurisprudence",
    "/api/v1/admin/syncs",
    "/api/v1/admin/ccn",
    "/api/v1/admin/quality",
    "/api/v1/admin/corpus",
    "/api/v1/documents/common",
    "/api/v1/conventions/admin",
)


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
        session_id: str | None = payload.get("sid")
        if user_id is None or session_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except (InvalidTokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            User.id == uuid.UUID(user_id),
            AuthSession.id == uuid.UUID(session_id),
            AuthSession.revoked.is_(False),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
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

    async def role_checker(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        async def audit(decision: str) -> None:
            if "admin" not in allowed_roles:
                return
            try:
                from app.services.audit_service import log_admin_action

                await log_admin_action(
                    db,
                    user_id=user.id,
                    action=f"admin_api_{decision}",
                    resource_type="admin_api",
                    resource_id=request.url.path[:255],
                    ip_address=request.client.host if request.client else None,
                    details=request.method,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("Unable to write admin access audit log")

        if user.role not in allowed_roles:
            await audit("denied")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Rôle insuffisant",
            )
        if user.role == "admin" and user.staff_role in {"business", "tech"}:
            forbidden = (
                _ADMIN_TECH_PREFIXES if user.staff_role == "business" else _ADMIN_BUSINESS_PREFIXES
            )
            if request.url.path.startswith(forbidden):
                await audit("denied")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Ce profil administrateur n'est pas autorisé à accéder à cette fonction",
                )

        await audit("allowed")
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

    result = await db.execute(select(Account).where(Account.owner_id == user.id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous devez être propriétaire d'un compte pour accéder à cette ressource",
        )
    return user, account
