import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.account_member import AccountInvitationCreate, AccountMemberUpdate
from app.services.email.sender import send_email
from app.services.email.templates import render_team_invitation_email

INVITATION_EXPIRY_DAYS = 7


class AccountMemberService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_account(self, account_id: uuid.UUID) -> Account:
        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Compte non trouvé",
            )
        return account

    async def list_members(self, account_id: uuid.UUID) -> list[dict]:
        result = await self.db.execute(
            select(AccountMember)
            .options(selectinload(AccountMember.user))
            .where(AccountMember.account_id == account_id)
            .order_by(AccountMember.created_at)
        )
        members = result.scalars().all()

        # Fetch org names for members with specific access
        account_orgs_result = await self.db.execute(
            select(Organisation).where(Organisation.account_id == account_id)
        )
        account_orgs = {
            org.id: org.name for org in account_orgs_result.scalars().all()
        }

        items = []
        for m in members:
            org_names: list[str] = []
            if m.access_all:
                org_names = list(account_orgs.values())
            elif m.selected_org_ids:
                selected_ids = json.loads(m.selected_org_ids)
                org_names = [
                    account_orgs[uuid.UUID(oid)]
                    for oid in selected_ids
                    if uuid.UUID(oid) in account_orgs
                ]

            items.append(
                {
                    "id": m.id,
                    "account_id": m.account_id,
                    "user_id": m.user_id,
                    "role_in_org": m.role_in_org,
                    "access_all": m.access_all,
                    "created_at": m.created_at,
                    "user_email": m.user.email if m.user else None,
                    "user_full_name": m.user.full_name if m.user else None,
                    "organisation_names": org_names,
                }
            )
        return items

    async def invite_member(
        self,
        account_id: uuid.UUID,
        data: AccountInvitationCreate,
        inviter: User,
    ) -> Invitation:
        account = await self._get_account(account_id)

        # Enforce plan user limit (belt-and-braces with the API layer).
        # Admins bypass because they may seed test accounts via the same
        # helper without being subject to the quota.
        if inviter.role != "admin":
            from app.services.billing_service import BillingService
            billing = BillingService(self.db)
            billing.ensure_plan_active(account)
            await billing.check_user_limit(account)

        # Check if already an account member
        existing_member = await self.db.execute(
            select(AccountMember)
            .join(User, User.id == AccountMember.user_id)
            .where(
                AccountMember.account_id == account_id,
                User.email == data.email,
            )
        )
        if existing_member.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cet utilisateur est déjà membre de l'équipe",
            )

        # Check for existing pending invitation
        existing_invite = await self.db.execute(
            select(Invitation).where(
                Invitation.email == data.email,
                Invitation.account_id == account_id,
                Invitation.status == "pending",
            )
        )
        if existing_invite.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Une invitation est déjà en attente pour cet email",
            )

        selected_org_ids_json = None
        if not data.access_all and data.organisation_ids:
            selected_org_ids_json = json.dumps([str(oid) for oid in data.organisation_ids])

        invitation = Invitation(
            email=data.email,
            account_id=account_id,
            organisation_id=None,
            invited_by=inviter.id,
            role_in_org=data.role_in_org.value,
            access_all=data.access_all,
            selected_org_ids=selected_org_ids_json,
            expires_at=datetime.now(UTC) + timedelta(days=INVITATION_EXPIRY_DAYS),
        )
        self.db.add(invitation)
        await self.db.flush()

        accept_url = f"{settings.frontend_url}/invite/accept/{invitation.token}"

        subject, html = render_team_invitation_email(
            inviter_name=inviter.full_name,
            account_name=account.name,
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

    async def remove_member(
        self, account_id: uuid.UUID, member_id: uuid.UUID
    ) -> None:
        result = await self.db.execute(
            select(AccountMember).where(
                AccountMember.id == member_id,
                AccountMember.account_id == account_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membre non trouvé",
            )

        # Delete all Memberships in account's orgs
        org_result = await self.db.execute(
            select(Organisation.id).where(Organisation.account_id == account_id)
        )
        org_ids = [row[0] for row in org_result.all()]

        if org_ids:
            memberships_result = await self.db.execute(
                select(Membership).where(
                    Membership.user_id == member.user_id,
                    Membership.organisation_id.in_(org_ids),
                )
            )
            for ms in memberships_result.scalars().all():
                await self.db.delete(ms)

        await self.db.delete(member)
        await self.db.commit()

    async def update_member(
        self,
        account_id: uuid.UUID,
        member_id: uuid.UUID,
        data: AccountMemberUpdate,
    ) -> dict:
        result = await self.db.execute(
            select(AccountMember)
            .options(selectinload(AccountMember.user))
            .where(
                AccountMember.id == member_id,
                AccountMember.account_id == account_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membre non trouvé",
            )

        if data.role_in_org is not None:
            member.role_in_org = data.role_in_org.value
        if data.access_all is not None:
            member.access_all = data.access_all
        if data.organisation_ids is not None:
            member.selected_org_ids = json.dumps([str(oid) for oid in data.organisation_ids])
        elif data.access_all:
            member.selected_org_ids = None

        await self.db.flush()
        await self._sync_memberships(member)
        await self.db.commit()

        # Return updated data
        members = await self.list_members(account_id)
        return next(m for m in members if m["id"] == member_id)

    async def _sync_memberships(self, account_member: AccountMember) -> None:
        """Create/delete Memberships to match AccountMember's access configuration."""
        org_result = await self.db.execute(
            select(Organisation.id).where(
                Organisation.account_id == account_member.account_id
            )
        )
        all_org_ids = {row[0] for row in org_result.all()}

        if account_member.access_all:
            target_org_ids = all_org_ids
        elif account_member.selected_org_ids:
            selected = set(uuid.UUID(oid) for oid in json.loads(account_member.selected_org_ids))
            target_org_ids = selected & all_org_ids
        else:
            target_org_ids = set()

        # Get existing memberships in account's orgs
        existing_result = await self.db.execute(
            select(Membership).where(
                Membership.user_id == account_member.user_id,
                Membership.organisation_id.in_(all_org_ids) if all_org_ids else Membership.id == None,
            )
        )
        existing_memberships = {ms.organisation_id: ms for ms in existing_result.scalars().all()}

        # Create missing memberships
        for org_id in target_org_ids:
            if org_id not in existing_memberships:
                self.db.add(
                    Membership(
                        user_id=account_member.user_id,
                        organisation_id=org_id,
                        role_in_org=account_member.role_in_org,
                    )
                )

        # Remove memberships no longer needed
        for org_id, ms in existing_memberships.items():
            if org_id not in target_org_ids:
                await self.db.delete(ms)

    async def sync_memberships_for_new_org(self, org: Organisation) -> None:
        """Called when a new org is created: create Memberships for access_all AccountMembers."""
        if not org.account_id:
            return

        result = await self.db.execute(
            select(AccountMember).where(
                AccountMember.account_id == org.account_id,
                AccountMember.access_all == True,  # noqa: E712
            )
        )
        for am in result.scalars().all():
            # Check if membership already exists
            existing = await self.db.execute(
                select(Membership).where(
                    Membership.user_id == am.user_id,
                    Membership.organisation_id == org.id,
                )
            )
            if not existing.scalar_one_or_none():
                self.db.add(
                    Membership(
                        user_id=am.user_id,
                        organisation_id=org.id,
                        role_in_org=am.role_in_org,
                    )
                )

    async def accept_account_invitation(
        self, invitation: Invitation, user: User
    ) -> dict:
        """Create AccountMember + sync Memberships when accepting an account-level invitation."""
        # Check if already an account member
        existing = await self.db.execute(
            select(AccountMember).where(
                AccountMember.account_id == invitation.account_id,
                AccountMember.user_id == user.id,
            )
        )
        if existing.scalar_one_or_none():
            invitation.status = "accepted"
            await self.db.commit()
            return {"status": "already_member", "account_id": str(invitation.account_id)}

        # Re-check the user limit at acceptance time. This protects against
        # the race where several pending invitations were created while the
        # account still had free slots, then accepted later when the slots
        # are all taken (e.g. other invitations accepted in between or the
        # account downgraded to a smaller plan).
        account_for_limit = await self._get_account(invitation.account_id)
        from app.services.billing_service import BillingService
        billing = BillingService(self.db)
        billing.ensure_plan_active(account_for_limit)
        await billing.check_user_limit(account_for_limit)

        account_member = AccountMember(
            account_id=invitation.account_id,
            user_id=user.id,
            role_in_org=invitation.role_in_org,
            access_all=invitation.access_all,
            selected_org_ids=invitation.selected_org_ids,
        )
        self.db.add(account_member)
        await self.db.flush()

        await self._sync_memberships(account_member)

        invitation.status = "accepted"
        await self.db.commit()

        account = await self._get_account(invitation.account_id)

        return {
            "status": "accepted",
            "account_id": str(invitation.account_id),
            "account_name": account.name,
        }

    async def list_invitations(self, account_id: uuid.UUID) -> list[Invitation]:
        result = await self.db.execute(
            select(Invitation)
            .where(
                Invitation.account_id == account_id,
            )
            .order_by(Invitation.created_at.desc())
        )
        invitations = list(result.scalars().all())

        now = datetime.now(UTC)
        for inv in invitations:
            if inv.status == "pending":
                expires = inv.expires_at
                if expires.tzinfo is None:
                    expired = expires < now.replace(tzinfo=None)
                else:
                    expired = expires < now
                if expired:
                    inv.status = "expired"
        await self.db.commit()
        return invitations

    async def cancel_invitation(
        self, account_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> None:
        result = await self.db.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.account_id == account_id,
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
        self,
        account_id: uuid.UUID,
        invitation_id: uuid.UUID,
        inviter: User,
    ) -> Invitation:
        result = await self.db.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.account_id == account_id,
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

        account = await self._get_account(account_id)

        accept_url = f"{settings.frontend_url}/invite/accept/{invitation.token}"
        subject, html = render_team_invitation_email(
            inviter_name=inviter.full_name,
            account_name=account.name,
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
