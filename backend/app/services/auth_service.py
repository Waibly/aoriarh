import logging
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
from app.schemas.stripe_billing import BillingCycle, CommercialPlanCode
from app.services.email.sender import send_email
from app.services.email.templates import render_admin_new_signup_email
from app.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


async def _notify_admin_new_signup(
    full_name: str,
    email: str,
    workspace_name: str,
    auth_method: str,
) -> None:
    """Notification interne envoyée à hello@aoriarh.fr lors d'une inscription
    self-service. Fire-and-forget : un échec n'interrompt jamais le signup.
    """
    if not settings.admin_email:
        return
    try:
        subject, html = render_admin_new_signup_email(
            full_name=full_name,
            email=email,
            workspace_name=workspace_name,
            plan_label="Trial (14 jours)",
            auth_method=auth_method,
        )
        await send_email(
            to_email=settings.admin_email,
            to_name="Admin AORIA RH",
            subject=subject,
            html_content=html,
        )
    except Exception:
        # Ne JAMAIS faire échouer un signup à cause d'un souci email.
        logger.exception("Failed to send admin new-signup notification for %s", email)


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


def _build_token_response(user_id: str, checkout_url: str | None = None) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(subject=user_id),
        refresh_token=create_refresh_token(subject=user_id),
        expires_in=settings.access_token_expire_minutes * 60,
        checkout_url=checkout_url,
    )


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _maybe_start_paid_checkout(
        self,
        account: Account,
        owner_email: str,
        requested_plan: CommercialPlanCode | None,
        requested_cycle: BillingCycle | None,
    ) -> str | None:
        """Start a Stripe Checkout session if the user picked a paid plan at signup.

        Returns the hosted checkout URL on success, or None if no paid plan was
        requested or Stripe is unavailable. The trial account stays in place as
        a safety net so an aborted Checkout doesn't leave the user account-less.
        """
        if requested_plan is None or requested_cycle is None:
            return None
        if not StripeService.is_configured():
            logger.warning(
                "Paid plan %s/%s requested at signup but Stripe is not configured — falling back to trial",
                requested_plan, requested_cycle,
            )
            return None
        try:
            stripe_svc = StripeService(self.db)
            result = await stripe_svc.create_subscription_checkout(
                account=account,
                owner_email=owner_email,
                plan=requested_plan.value,
                cycle=requested_cycle.value,
            )
            return result["checkout_url"]
        except Exception:
            logger.exception(
                "Stripe Checkout creation failed at signup for account %s — falling back to trial",
                account.id,
            )
            return None

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
        await self.db.refresh(account)
        await _notify_admin_new_signup(
            full_name=user.full_name,
            email=user.email,
            workspace_name=account.name,
            auth_method="Email + mot de passe",
        )
        checkout_url = await self._maybe_start_paid_checkout(
            account=account,
            owner_email=user.email,
            requested_plan=data.requested_plan,
            requested_cycle=data.requested_cycle,
        )
        return _build_token_response(str(user.id), checkout_url=checkout_url)

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
        await self.db.refresh(account)
        await _notify_admin_new_signup(
            full_name=user.full_name,
            email=user.email,
            workspace_name=account.name,
            auth_method="Google OAuth",
        )
        checkout_url = await self._maybe_start_paid_checkout(
            account=account,
            owner_email=user.email,
            requested_plan=data.requested_plan,
            requested_cycle=data.requested_cycle,
        )
        return _build_token_response(str(user.id), checkout_url=checkout_url)
