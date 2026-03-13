import logging
import uuid

from fastapi import HTTPException, status
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.invitation import Invitation
from app.models.ccn import OrganisationConvention
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
from app.schemas.organisation import (
    MembershipCreate,
    MembershipUpdate,
    OrganisationCreate,
    OrganisationUpdate,
)
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class OrganisationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_organisation(
        self, data: OrganisationCreate, user: User
    ) -> Organisation:
        org = Organisation(
            name=data.name,
            forme_juridique=data.forme_juridique.value if data.forme_juridique else None,
            taille=data.taille.value if data.taille else None,
            convention_collective=data.convention_collective,
            secteur_activite=data.secteur_activite,
            account_id=user.owned_account.id if user.owned_account else None,
        )
        self.db.add(org)
        await self.db.flush()

        membership = Membership(
            user_id=user.id,
            organisation_id=org.id,
            role_in_org="manager",
        )
        self.db.add(membership)
        await self.db.flush()

        # Sync account members with access_all=true into this new org
        if org.account_id:
            from app.services.account_member_service import AccountMemberService

            account_service = AccountMemberService(self.db)
            await account_service.sync_memberships_for_new_org(org)

        await self.db.commit()
        await self.db.refresh(org)
        return org

    async def list_organisations(self, user: User) -> list[Organisation]:
        if user.role == "admin":
            result = await self.db.execute(select(Organisation))
            return list(result.scalars().all())

        result = await self.db.execute(
            select(Organisation)
            .join(Membership, Membership.organisation_id == Organisation.id)
            .where(Membership.user_id == user.id)
        )
        return list(result.scalars().all())

    async def get_organisation(
        self, org_id: uuid.UUID, user: User
    ) -> Organisation:
        result = await self.db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = result.scalar_one_or_none()
        if org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organisation non trouvée",
            )

        if user.role != "admin":
            member_result = await self.db.execute(
                select(Membership).where(
                    Membership.organisation_id == org_id,
                    Membership.user_id == user.id,
                )
            )
            if member_result.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Vous n'êtes pas membre de cette organisation",
                )
        return org

    async def update_organisation(
        self, org_id: uuid.UUID, data: OrganisationUpdate, user: User
    ) -> Organisation:
        org = await self.get_organisation(org_id, user)

        if user.role != "admin":
            member_result = await self.db.execute(
                select(Membership).where(
                    Membership.organisation_id == org_id,
                    Membership.user_id == user.id,
                )
            )
            membership = member_result.scalar_one_or_none()
            if membership is None or membership.role_in_org != "manager":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Seul un manager peut modifier l'organisation",
                )

        update_data = data.model_dump(exclude_unset=True)
        if "forme_juridique" in update_data and update_data["forme_juridique"] is not None:
            update_data["forme_juridique"] = update_data["forme_juridique"].value
        if "taille" in update_data and update_data["taille"] is not None:
            update_data["taille"] = update_data["taille"].value

        for field, value in update_data.items():
            setattr(org, field, value)

        await self.db.commit()
        await self.db.refresh(org)
        return org

    async def delete_organisation(
        self, org_id: uuid.UUID, user: User
    ) -> None:
        org = await self.get_organisation(org_id, user)

        if user.role != "admin":
            member_result = await self.db.execute(
                select(Membership).where(
                    Membership.organisation_id == org_id,
                    Membership.user_id == user.id,
                )
            )
            membership = member_result.scalar_one_or_none()
            if membership is None or membership.role_in_org != "manager":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Seul un manager peut supprimer l'organisation",
                )

        # 1. Delete Qdrant vectors for this organisation
        try:
            client = get_qdrant_client()
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="organisation_id",
                                match=MatchValue(value=str(org_id)),
                            )
                        ]
                    )
                ),
            )
        except Exception:
            logger.warning("Failed to delete Qdrant vectors for org %s", org_id)

        # 2. Delete MinIO files for each document
        docs_result = await self.db.execute(
            select(Document).where(Document.organisation_id == org_id)
        )
        documents = docs_result.scalars().all()
        storage = StorageService()
        for doc in documents:
            try:
                storage.delete_file(doc.storage_path)
            except Exception:
                logger.warning("Failed to delete file %s", doc.storage_path)

        # 3. Delete messages via conversation_ids
        conv_result = await self.db.execute(
            select(Conversation.id).where(Conversation.organisation_id == org_id)
        )
        conv_ids = [row[0] for row in conv_result.all()]
        if conv_ids:
            await self.db.execute(
                delete(Message).where(Message.conversation_id.in_(conv_ids))
            )

        # 4. Delete conversations
        await self.db.execute(
            delete(Conversation).where(Conversation.organisation_id == org_id)
        )

        # 5. Delete documents
        await self.db.execute(
            delete(Document).where(Document.organisation_id == org_id)
        )

        # 6. Delete invitations
        await self.db.execute(
            delete(Invitation).where(Invitation.organisation_id == org_id)
        )

        # 7. Delete organisation_conventions
        await self.db.execute(
            delete(OrganisationConvention).where(OrganisationConvention.organisation_id == org_id)
        )

        # 8. Delete memberships (NOT users)
        await self.db.execute(
            delete(Membership).where(Membership.organisation_id == org_id)
        )

        # 9. Delete organisation
        await self.db.delete(org)
        await self.db.commit()

    # --- Member management ---

    async def list_members(self, org_id: uuid.UUID) -> list[dict]:
        result = await self.db.execute(
            select(Membership)
            .options(selectinload(Membership.user))
            .where(Membership.organisation_id == org_id)
        )
        memberships = result.scalars().all()
        return [
            {
                "id": m.id,
                "user_id": m.user_id,
                "organisation_id": m.organisation_id,
                "role_in_org": m.role_in_org,
                "created_at": m.created_at,
                "user_email": m.user.email if m.user else None,
                "user_full_name": m.user.full_name if m.user else None,
            }
            for m in memberships
        ]

    async def add_member(self, org_id: uuid.UUID, data: MembershipCreate) -> dict:
        result = await self.db.execute(
            select(User).where(User.email == data.email)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aucun utilisateur trouvé avec cet email",
            )

        existing = await self.db.execute(
            select(Membership).where(
                Membership.organisation_id == org_id,
                Membership.user_id == user.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cet utilisateur est déjà membre de l'organisation",
            )

        membership = Membership(
            user_id=user.id,
            organisation_id=org_id,
            role_in_org=data.role_in_org.value,
        )
        self.db.add(membership)
        await self.db.commit()
        await self.db.refresh(membership)

        return {
            "id": membership.id,
            "user_id": membership.user_id,
            "organisation_id": membership.organisation_id,
            "role_in_org": membership.role_in_org,
            "created_at": membership.created_at,
            "user_email": user.email,
            "user_full_name": user.full_name,
        }

    async def update_member_role(
        self, org_id: uuid.UUID, membership_id: uuid.UUID, data: MembershipUpdate
    ) -> dict:
        result = await self.db.execute(
            select(Membership)
            .options(selectinload(Membership.user))
            .where(
                Membership.id == membership_id,
                Membership.organisation_id == org_id,
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membre non trouvé",
            )

        membership.role_in_org = data.role_in_org.value
        await self.db.commit()
        await self.db.refresh(membership)

        return {
            "id": membership.id,
            "user_id": membership.user_id,
            "organisation_id": membership.organisation_id,
            "role_in_org": membership.role_in_org,
            "created_at": membership.created_at,
            "user_email": membership.user.email if membership.user else None,
            "user_full_name": membership.user.full_name if membership.user else None,
        }

    async def remove_member(
        self, org_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        result = await self.db.execute(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.organisation_id == org_id,
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membre non trouvé",
            )

        if membership.role_in_org == "manager":
            count_result = await self.db.execute(
                select(func.count(Membership.id)).where(
                    Membership.organisation_id == org_id,
                    Membership.role_in_org == "manager",
                )
            )
            manager_count = count_result.scalar()
            if manager_count is not None and manager_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Impossible de retirer le dernier manager de l'organisation",
                )

        await self.db.delete(membership)
        await self.db.commit()
