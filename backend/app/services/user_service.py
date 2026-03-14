import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.user import User
from app.schemas.user import PasswordChange, UserUpdate

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return user

        if "email" in update_data and update_data["email"] != user.email:
            existing = await self.db.execute(
                select(User).where(User.email == update_data["email"])
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cet email est déjà utilisé",
                )

        if "profil_metier" in update_data and update_data["profil_metier"] is not None:
            update_data["profil_metier"] = update_data["profil_metier"].value

        for key, value in update_data.items():
            setattr(user, key, value)

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def change_password(self, user: User, data: PasswordChange) -> None:
        if not user.hashed_password or not verify_password(data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe actuel incorrect",
            )

        user.hashed_password = hash_password(data.new_password)
        await self.db.commit()

    async def delete_user_data(self, user_id: uuid.UUID) -> None:
        """Delete all data associated with a user. Preserves API cost logs (SET NULL)."""
        # 1. Detach documents (keep them, clear uploader reference)
        await self.db.execute(
            Document.__table__.update()
            .where(Document.uploaded_by == user_id)
            .values(uploaded_by=None)
        )

        # 2. Delete audit logs
        await self.db.execute(delete(AuditLog).where(AuditLog.user_id == user_id))

        # 3. Delete messages from user's conversations
        conv_result = await self.db.execute(
            select(Conversation.id).where(Conversation.user_id == user_id)
        )
        conv_ids = [row[0] for row in conv_result.all()]
        if conv_ids:
            await self.db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))

        # 4. Delete conversations
        await self.db.execute(delete(Conversation).where(Conversation.user_id == user_id))

        # 5. Delete invitations sent by user
        await self.db.execute(delete(Invitation).where(Invitation.invited_by == user_id))

        # 6. Delete memberships
        await self.db.execute(delete(Membership).where(Membership.user_id == user_id))

        # 7. Delete account memberships
        await self.db.execute(delete(AccountMember).where(AccountMember.user_id == user_id))

        # 8. Delete owned account (if any)
        user = await self.db.get(User, user_id)
        if user and user.owned_account:
            await self.db.delete(user.owned_account)

        # 9. Delete user
        if user:
            await self.db.delete(user)

    async def delete_own_account(self, user: User) -> None:
        """Self-deletion: user deletes their own account.

        If user owns an Account with organisations, those organisations
        are deleted first via OrganisationService.
        """
        if user.role == "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un administrateur ne peut pas supprimer son propre compte",
            )

        # If user owns an account, delete all its organisations first
        if user.owned_account:
            from app.services.organisation_service import OrganisationService

            org_service = OrganisationService(self.db)
            account = user.owned_account

            # Get all orgs in this account
            from app.models.organisation import Organisation
            org_result = await self.db.execute(
                select(Organisation).where(Organisation.account_id == account.id)
            )
            orgs = org_result.scalars().all()

            for org in orgs:
                # Use existing delete logic (Qdrant, MinIO, conversations, docs, etc.)
                await org_service.delete_organisation(org.id, user)

            # Delete remaining account members
            await self.db.execute(
                delete(AccountMember).where(AccountMember.account_id == account.id)
            )

        # Now delete the user and their personal data
        await self.delete_user_data(user.id)
        await self.db.commit()
