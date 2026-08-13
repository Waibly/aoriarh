import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import TRIAL_DURATION_DAYS
from app.core.security import (
    hash_password,
    verify_password,
)
from app.models.account import Account
from app.models.invitation import Invitation
from app.models.user import User
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    SignupAttribution,
    TokenResponse,
)
from app.schemas.stripe_billing import BillingCycle, CommercialPlanCode
from app.services.auth_session_service import create_auth_session
from app.services.email.sender import is_test_email, send_email, sync_contact_to_brevo
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
    if is_test_email(email):
        logger.info("Signup notification skipped for test address: %s", email)
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


def apply_attribution(user: User, attribution: SignupAttribution | None) -> None:
    """Pose l'attribution marketing sur un utilisateur, en premier contact
    uniquement : si l'utilisateur porte déjà une attribution, on n'écrase rien.
    """
    if attribution is None or attribution.is_empty():
        return
    if user.attributed_at is not None or user.utm_source or user.gclid or user.msclkid:
        return
    user.utm_source = attribution.utm_source
    user.utm_medium = attribution.utm_medium
    user.utm_campaign = attribution.utm_campaign
    user.utm_term = attribution.utm_term
    user.utm_content = attribution.utm_content
    user.gclid = attribution.gclid
    user.msclkid = attribution.msclkid
    user.referrer = attribution.referrer
    user.landing_page = attribution.landing_page
    user.attributed_at = attribution.attributed_at or datetime.now(UTC)


async def _build_token_response(
    db: AsyncSession, user_id: uuid.UUID, checkout_url: str | None = None
) -> TokenResponse:
    access_token, refresh_token = await create_auth_session(db, user_id)
    await db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
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
                "Paid plan %s/%s requested at signup but Stripe is not configured "
                "— falling back to trial",
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
            apply_attribution(user, data.attribution)
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
            return await _build_token_response(self.db, user.id)

        # Self-registration: create Account + role=manager
        user = User(
            email=email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role="manager",
        )
        apply_attribution(user, data.attribution)
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
        await sync_contact_to_brevo(
            email=user.email,
            full_name=user.full_name,
            auth_method="Email + mot de passe",
            role=user.role,
        )
        checkout_url = await self._maybe_start_paid_checkout(
            account=account,
            owner_email=user.email,
            requested_plan=data.requested_plan,
            requested_cycle=data.requested_cycle,
        )
        return await _build_token_response(self.db, user.id, checkout_url=checkout_url)

    async def login(self, data: LoginRequest) -> TokenResponse | None:
        email = data.email.lower().strip()
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if (
            not user
            or not user.hashed_password
            or not verify_password(data.password, user.hashed_password)
        ):
            return None
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Compte désactivé",
            )
        return await _build_token_response(self.db, user.id)

    async def google_auth(self, data: GoogleAuthRequest) -> TokenResponse:
        """Login/register only after server-side verification of Google's ID token."""
        if not settings.google_client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Connexion Google temporairement indisponible",
            )

        try:
            import anyio
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token

            claims = await anyio.to_thread.run_sync(
                lambda: google_id_token.verify_oauth2_token(
                    data.id_token,
                    google_requests.Request(),
                    settings.google_client_id,
                )
            )
        except Exception:
            logger.warning("Rejected invalid Google ID token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Jeton Google invalide",
            )

        issuer = claims.get("iss")
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise HTTPException(status_code=401, detail="Émetteur Google invalide")
        if claims.get("email_verified") is not True:
            raise HTTPException(status_code=401, detail="Email Google non vérifié")

        email = str(claims.get("email", "")).lower().strip()
        google_sub = str(claims.get("sub", "")).strip()
        full_name = str(claims.get("name") or email.split("@", 1)[0])[:255]
        if not email or not google_sub:
            raise HTTPException(status_code=401, detail="Identité Google incomplète")

        by_sub = await self.db.execute(select(User).where(User.google_sub == google_sub))
        user = by_sub.scalar_one_or_none()
        if user is not None and user.email.lower() != email:
            raise HTTPException(status_code=409, detail="Identité Google déjà liée")

        if user is None:
            result = await self.db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        if user:
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Compte désactivé",
                )
            if user.google_sub and user.google_sub != google_sub:
                raise HTTPException(
                    status_code=409,
                    detail="Compte lié à une autre identité Google",
                )
            user.google_sub = google_sub
            user.auth_provider = "google"
            await self.db.commit()
            return await _build_token_response(self.db, user.id)

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
                full_name=full_name,
                auth_provider="google",
                google_sub=google_sub,
                role="user",
            )
            apply_attribution(user, data.attribution)
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
            return await _build_token_response(self.db, user.id)

        # Self-registration via Google — create Account + role=manager
        user = User(
            email=email,
            hashed_password=None,
            full_name=full_name,
            auth_provider="google",
            google_sub=google_sub,
            role="manager",
        )
        apply_attribution(user, data.attribution)
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
        await sync_contact_to_brevo(
            email=user.email,
            full_name=user.full_name,
            auth_method="Google OAuth",
            role=user.role,
        )
        checkout_url = await self._maybe_start_paid_checkout(
            account=account,
            owner_email=user.email,
            requested_plan=data.requested_plan,
            requested_cycle=data.requested_cycle,
        )
        return await _build_token_response(self.db, user.id, checkout_url=checkout_url)
