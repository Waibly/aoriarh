from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import TRIAL_DURATION_DAYS
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.account import Account
from app.models.invitation import Invitation
from app.models.user import User
from app.schemas.auth import GoogleAuthRequest, LoginRequest, RegisterRequest, TokenResponse


def _new_trial_account(name: str, owner_id) -> Account:
    """Factory for a freshly-created account in the 14-day trial window."""
    now = datetime.now(UTC)
    return Account(
        name=name,
        owner_id=owner_id,
        plan="gratuit",
        plan_assigned_at=now,
        plan_expires_at=now + timedelta(days=TRIAL_DURATION_DAYS),
        status="trialing",
    )


def _build_token_response(user_id: str) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(subject=user_id),
        refresh_token=create_refresh_token(subject=user_id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, data: RegisterRequest) -> TokenResponse:
        email = data.email.lower().strip()
        result = await self.db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Un compte avec cet email existe déjà",
            )

        if data.invited:
            # Invited user: no Account, role=user
            user = User(
                email=email,
                hashed_password=hash_password(data.password),
                full_name=data.full_name,
                role="user",
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
            return _build_token_response(str(user.id))

        # Self-registration: create Account + role=manager
        user = User(
            email=email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role="manager",
        )
        self.db.add(user)
        await self.db.flush()

        account = _new_trial_account(
            name=data.workspace_name or f"Espace de {user.full_name}",
            owner_id=user.id,
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(user)
        return _build_token_response(str(user.id))

    async def login(self, data: LoginRequest) -> TokenResponse | None:
        email = data.email.lower().strip()
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not user.hashed_password or not verify_password(data.password, user.hashed_password):
            return None
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Compte désactivé",
            )
        return _build_token_response(str(user.id))

    async def google_auth(self, data: GoogleAuthRequest) -> TokenResponse:
        """Login or register a user via Google OAuth."""
        email = data.email.lower().strip()
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            # Existing user — update provider if needed and return tokens
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Compte désactivé",
                )
            if user.auth_provider == "credentials":
                # Link Google to existing credentials account
                user.auth_provider = "google"
                await self.db.commit()
            return _build_token_response(str(user.id))

        # Check if there's a pending invitation for this email
        inv_result = await self.db.execute(
            select(Invitation).where(
                Invitation.email.ilike(email),
                Invitation.status == "pending",
            )
        )
        has_pending_invitation = inv_result.scalar_one_or_none() is not None

        if has_pending_invitation:
            # Invited user via Google — no Account, role=user
            user = User(
                email=email,
                hashed_password=None,
                full_name=data.full_name,
                auth_provider="google",
                role="user",
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
            return _build_token_response(str(user.id))

        # Self-registration via Google — create Account + role=manager
        user = User(
            email=email,
            hashed_password=None,
            full_name=data.full_name,
            auth_provider="google",
            role="manager",
        )
        self.db.add(user)
        await self.db.flush()

        account = _new_trial_account(
            name=f"Espace de {user.full_name}",
            owner_id=user.id,
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(user)
        return _build_token_response(str(user.id))
