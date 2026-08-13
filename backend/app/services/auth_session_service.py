import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.auth_session import AuthSession


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


async def create_auth_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    family_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> tuple[str, str]:
    raw_token = _new_refresh_token()
    session = AuthSession(
        family_id=family_id or uuid.uuid4(),
        user_id=user_id,
        refresh_token_hash=_hash_refresh_token(raw_token),
        expires_at=expires_at
        or datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    await db.flush()
    access_token = create_access_token(subject=str(user_id), session_id=str(session.id))
    return access_token, raw_token


async def rotate_auth_session(
    db: AsyncSession,
    raw_token: str,
) -> tuple[AuthSession, str, str] | None:
    """Consume a refresh token once and return a rotated pair.

    Reuse of an already-consumed token revokes the whole token family.
    """
    token_hash = _hash_refresh_token(raw_token)
    result = await db.execute(
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == token_hash)
        .with_for_update()
    )
    current = result.scalar_one_or_none()
    if current is None:
        return None

    now = datetime.now(UTC)
    expires_at = current.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if current.revoked:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == current.family_id)
            .values(revoked=True)
        )
        await db.commit()
        return None
    if expires_at <= now:
        current.revoked = True
        await db.commit()
        return None

    current.revoked = True
    current.last_used_at = now
    access_token, new_refresh_token = await create_auth_session(
        db,
        current.user_id,
        family_id=current.family_id,
        expires_at=expires_at,
    )
    await db.commit()
    return current, access_token, new_refresh_token


async def revoke_auth_session(db: AsyncSession, raw_token: str) -> bool:
    token_hash = _hash_refresh_token(raw_token)
    result = await db.execute(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return False
    await db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == session.family_id)
        .values(revoked=True)
    )
    await db.commit()
    return True


async def revoke_all_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked.is_(False))
        .values(revoked=True)
    )
