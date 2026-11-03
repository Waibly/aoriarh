import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.account_member import AccountMember
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.dossier import Dossier
from app.models.fiche import Fiche
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.plan_invitation import PlanInvitationRedemption
from app.models.user import User
from app.schemas.user import PasswordChange, UserUpdate
from app.services.auth_session_service import revoke_all_user_sessions

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return user

        if "email" in update_data and update_data["email"] != user.email:
            existing = await self.db.execute(select(User).where(User.email == update_data["email"]))
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
        if not user.hashed_password or not verify_password(
            data.current_password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe actuel incorrect",
            )

        user.hashed_password = hash_password(data.new_password)
        await revoke_all_user_sessions(self.db, user.id)
        await self.db.commit()

    async def delete_user_data(self, user_id: uuid.UUID) -> None:
        """Delete all data associated with a user. Preserves API cost logs (SET NULL)."""
        from app.services.case_file_service import delete_case_files_for_conversations
        from app.services.document_extraction_service import delete_extraction_artifacts
        from app.services.storage_operation_service import queue_storage_delete
        from app.services.storage_service import StorageService

        conv_ids = list(
            (
                await self.db.scalars(
                    select(Conversation.id).where(Conversation.user_id == user_id)
                )
            ).all()
        )
        dossiers = (
            await self.db.execute(
                select(Dossier.id, Dossier.case_file_id).where(Dossier.user_id == user_id)
            )
        ).all()
        dossier_ids = [row.id for row in dossiers]
        private_docs = list(
            (
                await self.db.scalars(
                    select(Document).where(
                        or_(
                            Document.private_dossier_id.in_(dossier_ids),
                            Document.private_conversation_id.in_(conv_ids),
                        )
                    )
                )
            ).all()
        )
        storage = StorageService()
        private_ids = [doc.id for doc in private_docs]
        await delete_extraction_artifacts(self.db, storage, private_ids)
        for doc in private_docs:
            await queue_storage_delete(self.db, storage, doc.id, doc.storage_path)
        await self.db.execute(delete(Document).where(Document.id.in_(private_ids)))
        self.db.info.setdefault("user_document_cleanup_ids", []).extend(private_ids)
        await self.db.execute(delete(Fiche).where(Fiche.user_id == user_id))
        await self.db.execute(
            update(Conversation)
            .where(Conversation.dossier_id.in_(dossier_ids))
            .values(dossier_id=None)
        )
        await self.db.execute(delete(Dossier).where(Dossier.id.in_(dossier_ids)))
        await delete_case_files_for_conversations(
            self.db, conv_ids, additional_case_ids=[row.case_file_id for row in dossiers]
        )

        # Revoke/delete authentication material before removing the identity.
        await self.db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))

        # 1. Detach documents (keep them, clear uploader reference)
        await self.db.execute(
            Document.__table__.update()
            .where(Document.uploaded_by == user_id)
            .values(uploaded_by=None)
        )

        # 2. Delete audit logs
        await self.db.execute(delete(AuditLog).where(AuditLog.user_id == user_id))

        # 3. Delete messages from user's conversations
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
        await self.db.execute(
            delete(PlanInvitationRedemption).where(PlanInvitationRedemption.user_id == user_id)
        )

        # 8. Delete owned account ONLY if it still belongs to this user
        # (the admin endpoint may have transferred ownership before calling us)
        user = await self.db.get(User, user_id)
        if user and user.owned_account and user.owned_account.owner_id == user_id:
            await self.db.execute(
                delete(Invitation).where(Invitation.account_id == user.owned_account.id)
            )
            await self.db.execute(
                delete(PlanInvitationRedemption).where(
                    PlanInvitationRedemption.account_id == user.owned_account.id
                )
            )
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

        from app.services.organisation_service import OrganisationService
        from app.services.stripe_service import StripeService

        org_service = OrganisationService(self.db)

        # Confirm the end of billing before erasing identifiers or any data.
        # External cancellation cannot roll back with SQL; retries are supported.
        if user.owned_account:
            account = user.owned_account
            await StripeService(self.db).cancel_subscription_now(
                account, include_customer_subscriptions=True
            )

            # Get all orgs in this account
            from app.models.organisation import Organisation

            org_result = await self.db.execute(
                select(Organisation).where(Organisation.account_id == account.id)
            )
            orgs = org_result.scalars().all()

            for org in orgs:
                # Use existing delete logic (Qdrant, MinIO, conversations, docs, etc.)
                await org_service.delete_organisation(org.id, user, commit=False)

            # Delete remaining account members
            await self.db.execute(
                delete(AccountMember).where(AccountMember.account_id == account.id)
            )

        # Now delete the user and their personal data
        await self.delete_user_data(user.id)
        await self.db.commit()
        await self.finish_deletions()
        await org_service.finish_deletions()

    async def finish_deletions(self) -> None:
        """Remove personal document artifacts after relational erasure commits."""
        from app.services.document_service import DocumentService
        from app.services.storage_operation_service import finish_pending_storage_deletes
        from app.services.storage_service import StorageService

        for document_id in self.db.info.pop("user_document_cleanup_ids", []):
            DocumentService._delete_qdrant_chunks(document_id)
        await finish_pending_storage_deletes(self.db, StorageService())
