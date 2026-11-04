import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.auth_session import AuthSession
from app.models.user import User

logger = logging.getLogger(__name__)


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

    Reuse of an already-consumed token revokes the whole token family, except
    within a short grace window after a legitimate rotation (concurrent refresh
    of the same session by several Next.js runtimes).
    """
    token_hash = _hash_refresh_token(raw_token)
    # All session issuance takes the user lock before the session lock. A Google
    # claim must not miss a refresh session inserted while it revokes old access.
    user_id = await db.scalar(
        select(AuthSession.user_id).where(AuthSession.refresh_token_hash == token_hash)
    )
    if user_id is None:
        return None
    locked_user = await db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    if locked_user is None:
        return None
    result = await db.execute(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash).with_for_update()
    )
    current = result.scalar_one_or_none()
    if current is None:
        return None

    now = datetime.now(UTC)
    expires_at = current.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if expires_at <= now:
        current.revoked = True
        await db.commit()
        return None

    if current.revoked:
        if await _is_concurrent_rotation(db, current, now):
            # The same client refreshed twice at once (e.g. Next.js middleware
            # and /api/auth/session). Issue a sibling pair in the same family;
            # whichever cookie the browser keeps remains valid.
            access_token, new_refresh_token = await create_auth_session(
                db,
                current.user_id,
                family_id=current.family_id,
                expires_at=expires_at,
            )
            await db.commit()
            return current, access_token, new_refresh_token
        await db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == current.family_id)
            .values(revoked=True)
        )
        await db.commit()
        logger.warning(
            "refresh_token_reuse_detected family=%s user=%s", current.family_id, current.user_id
        )
        return None

    access_token, new_refresh_token = await create_auth_session(
        db,
        current.user_id,
        family_id=current.family_id,
        expires_at=expires_at,
    )
    successor_id = await db.scalar(
        select(AuthSession.id).where(
            AuthSession.refresh_token_hash == _hash_refresh_token(new_refresh_token)
        )
    )
    current.revoked = True
    current.last_used_at = now
    current.replaced_by_id = successor_id
    await db.commit()
    return current, access_token, new_refresh_token


async def _is_concurrent_rotation(db: AsyncSession, current: AuthSession, now: datetime) -> bool:
    """True if `current` was consumed by a rotation moments ago and the session
    it was rotated into is still live (not logged out, not revoked as stolen)."""
    if current.replaced_by_id is None or current.last_used_at is None:
        return False
    rotated_at = current.last_used_at
    if rotated_at.tzinfo is None:
        rotated_at = rotated_at.replace(tzinfo=UTC)
    if now - rotated_at > timedelta(seconds=settings.refresh_token_reuse_grace_seconds):
        return False
    successor_revoked = await db.scalar(
        select(AuthSession.revoked).where(AuthSession.id == current.replaced_by_id)
    )
    return successor_revoked is False


async def revoke_auth_session(db: AsyncSession, raw_token: str) -> bool:
    token_hash = _hash_refresh_token(raw_token)
    result = await db.execute(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return False
    await db.execute(
        update(AuthSession).where(AuthSession.family_id == session.family_id).values(revoked=True)
    )
    await db.commit()
    return True


async def revoke_all_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked.is_(False))
        .values(revoked=True)
    )
