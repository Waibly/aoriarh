from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.account import Account
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


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
        result = await self.db.execute(select(User).where(User.email == data.email))
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Un compte avec cet email existe déjà",
            )

        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
        )
        self.db.add(user)
        await self.db.flush()

        account = Account(
            name=f"Compte de {user.full_name}",
            owner_id=user.id,
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(user)
        return _build_token_response(str(user.id))

    async def login(self, data: LoginRequest) -> TokenResponse | None:
        result = await self.db.execute(select(User).where(User.email == data.email))
        user = result.scalar_one_or_none()
        if not user or not verify_password(data.password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        return _build_token_response(str(user.id))
