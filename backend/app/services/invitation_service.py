import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.account import Account
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.invitation import InvitationCreate
from app.services.email.sender import send_email
from app.services.email.templates import render_invitation_email

INVITATION_EXPIRY_DAYS = 7


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_expired(expires_at: datetime) -> bool:
    """Compare expires_at with current time, handling tz-naive values (SQLite)."""
    now = _utcnow()
    if expires_at.tzinfo is None:
        return expires_at < now.replace(tzinfo=None)
    return expires_at < now


class InvitationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_invitation(
        self, org_id: uuid.UUID, data: InvitationCreate, inviter: User
    ) -> Invitation:
        # Check if already a member
        existing_member = await self.db.execute(
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organisation_id == org_id,
                User.email == data.email,
            )
        )
        if existing_member.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cet utilisateur est déjà membre de l'organisation",
            )

        # Check for existing pending invitation
        existing_invite = await self.db.execute(
            select(Invitation).where(
                Invitation.email == data.email,
                Invitation.organisation_id == org_id,
                Invitation.status == "pending",
            )
        )
        if existing_invite.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Une invitation est déjà en attente pour cet email",
            )

        # Fetch org name for email
        org_result = await self.db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = org_result.scalar_one()

        invitation = Invitation(
            email=data.email,
            organisation_id=org_id,
            invited_by=inviter.id,
            role_in_org=data.role_in_org.value,
            expires_at=datetime.now(UTC) + timedelta(days=INVITATION_EXPIRY_DAYS),
        )
        self.db.add(invitation)
        await self.db.flush()

        accept_url = f"{settings.frontend_url}/invite/accept/{invitation.token}"

        subject, html = render_invitation_email(
            inviter_name=inviter.full_name,
            organisation_name=org.name,
            role_in_org=data.role_in_org.value,
            accept_url=accept_url,
        )
        await send_email(
            to_email=data.email,
            to_name=None,
            subject=subject,
            html_content=html,
        )

        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def list_invitations(self, org_id: uuid.UUID) -> list[Invitation]:
        result = await self.db.execute(
            select(Invitation)
            .where(Invitation.organisation_id == org_id)
            .order_by(Invitation.created_at.desc())
        )
        invitations = list(result.scalars().all())

        # Auto-expire old invitations
        for inv in invitations:
            if inv.status == "pending" and _is_expired(inv.expires_at):
                inv.status = "expired"
        await self.db.commit()

        return invitations

    async def cancel_invitation(
        self, org_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> None:
        result = await self.db.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.organisation_id == org_id,
                Invitation.status == "pending",
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation non trouvée ou déjà traitée",
            )
        invitation.status = "cancelled"
        await self.db.commit()

    async def resend_invitation(
        self, org_id: uuid.UUID, invitation_id: uuid.UUID, inviter: User
    ) -> Invitation:
        result = await self.db.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.organisation_id == org_id,
                Invitation.status == "pending",
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation non trouvée ou déjà traitée",
            )

        invitation.expires_at = datetime.now(UTC) + timedelta(days=INVITATION_EXPIRY_DAYS)
        invitation.token = uuid.uuid4()

        org_result = await self.db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = org_result.scalar_one()

        accept_url = f"{settings.frontend_url}/invite/accept/{invitation.token}"

        subject, html = render_invitation_email(
            inviter_name=inviter.full_name,
            organisation_name=org.name,
            role_in_org=invitation.role_in_org,
            accept_url=accept_url,
        )
        await send_email(
            to_email=invitation.email,
            to_name=None,
            subject=subject,
            html_content=html,
        )

        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def validate_token(self, token: uuid.UUID) -> dict:
        result = await self.db.execute(
            select(Invitation).where(Invitation.token == token)
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            return {"valid": False, "status": None, "email": None, "organisation_name": None, "account_name": None}

        if invitation.status == "pending" and _is_expired(invitation.expires_at):
            invitation.status = "expired"
            await self.db.commit()

        organisation_name = None
        account_name = None

        if invitation.account_id:
            account_result = await self.db.execute(
                select(Account).where(Account.id == invitation.account_id)
            )
            account = account_result.scalar_one_or_none()
            account_name = account.name if account else None
        elif invitation.organisation_id:
            org_result = await self.db.execute(
                select(Organisation).where(Organisation.id == invitation.organisation_id)
            )
            org = org_result.scalar_one_or_none()
            organisation_name = org.name if org else None

        return {
            "valid": invitation.status == "pending",
            "status": invitation.status,
            "email": invitation.email,
            "organisation_name": organisation_name,
            "account_name": account_name,
        }

    async def accept_invitation(self, token: uuid.UUID, user: User) -> dict:
        result = await self.db.execute(
            select(Invitation).where(
                Invitation.token == token,
                Invitation.status == "pending",
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation invalide, expirée ou déjà utilisée",
            )

        if _is_expired(invitation.expires_at):
            invitation.status = "expired"
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Cette invitation a expiré",
            )

        if user.email.lower() != invitation.email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cette invitation a été envoyée à {invitation.email}. Connectez-vous avec cette adresse pour l'accepter.",
            )

        # Account-level invitation
        if invitation.account_id:
            from app.services.account_member_service import AccountMemberService

            account_service = AccountMemberService(self.db)
            return await account_service.accept_account_invitation(invitation, user)

        # Org-level invitation (existing behavior)
        existing = await self.db.execute(
            select(Membership).where(
                Membership.organisation_id == invitation.organisation_id,
                Membership.user_id == user.id,
            )
        )
        if existing.scalar_one_or_none():
            invitation.status = "accepted"
            await self.db.commit()
            return {"status": "already_member", "organisation_id": str(invitation.organisation_id)}

        # Re-check the user limit against the Account that owns the org.
        # Prevents accepting an invitation after the account has been
        # downgraded or filled up by concurrent acceptances.
        from app.services.billing_service import BillingService
        billing = BillingService(self.db)
        org_account = await billing.get_account_for_organisation(
            invitation.organisation_id
        )
        billing.ensure_plan_active(org_account)
        await billing.check_user_limit(org_account)

        membership = Membership(
            user_id=user.id,
            organisation_id=invitation.organisation_id,
            role_in_org=invitation.role_in_org,
        )
        self.db.add(membership)
        invitation.status = "accepted"
        await self.db.commit()

        org_result = await self.db.execute(
            select(Organisation).where(Organisation.id == invitation.organisation_id)
        )
        org = org_result.scalar_one()

        return {
            "status": "accepted",
            "organisation_id": str(invitation.organisation_id),
            "organisation_name": org.name,
        }
