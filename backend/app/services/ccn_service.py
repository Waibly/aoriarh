"""Service métier pour la gestion des conventions collectives par organisation."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.ccn import CcnReference, OrganisationConvention
from app.models.document import Document
from app.models.membership import Membership


class CcnService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search_ccn(self, query: str, limit: int = 20) -> list[CcnReference]:
        """Search CCN reference by IDCC or title."""
        q = query.strip()
        if not q:
            # Return most common ones
            result = await self.db.execute(
                select(CcnReference)
                .where(CcnReference.etat.ilike("VIGUEUR%"))
                .order_by(CcnReference.titre)
                .limit(limit)
            )
            return list(result.scalars().all())

        # Search by IDCC exact match or title ILIKE
        result = await self.db.execute(
            select(CcnReference)
            .where(
                CcnReference.etat.ilike("VIGUEUR%"),
                (CcnReference.idcc == q)
                | CcnReference.titre.ilike(f"%{q}%")
                | CcnReference.idcc.ilike(f"%{q}%"),
            )
            .order_by(CcnReference.titre)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_org_conventions(
        self, organisation_id: uuid.UUID
    ) -> list[OrganisationConvention]:
        """List all conventions installed for an organisation."""
        result = await self.db.execute(
            select(OrganisationConvention)
            .options(joinedload(OrganisationConvention.ccn))
            .where(OrganisationConvention.organisation_id == organisation_id)
            .order_by(OrganisationConvention.created_at)
        )
        return list(result.scalars().all())

    async def install_convention(
        self, organisation_id: uuid.UUID, idcc: str, user_id: uuid.UUID
    ) -> OrganisationConvention:
        """Add a convention to an organisation and enqueue installation."""
        # Verify IDCC exists in reference
        ccn = await self.db.get(CcnReference, idcc)
        if ccn is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"IDCC {idcc} introuvable dans le référentiel",
            )

        # Check not already installed
        existing = await self.db.execute(
            select(OrganisationConvention).where(
                OrganisationConvention.organisation_id == organisation_id,
                OrganisationConvention.idcc == idcc,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La convention IDCC {idcc} est déjà installée",
            )

        org_conv = OrganisationConvention(
            organisation_id=organisation_id,
            idcc=idcc,
            status="pending",
        )
        self.db.add(org_conv)
        await self.db.commit()
        await self.db.refresh(org_conv, ["ccn"])

        # Enqueue background task
        from app.rag.tasks import enqueue_kali_install
        await enqueue_kali_install(
            str(org_conv.id),
            str(user_id),
        )

        return org_conv

    async def remove_convention(
        self, organisation_id: uuid.UUID, idcc: str
    ) -> None:
        """Remove a convention from an organisation and clean up documents/vectors."""
        result = await self.db.execute(
            select(OrganisationConvention).where(
                OrganisationConvention.organisation_id == organisation_id,
                OrganisationConvention.idcc == idcc,
            )
        )
        org_conv = result.scalar_one_or_none()
        if org_conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Convention IDCC {idcc} non trouvée pour cette organisation",
            )

        # Delete associated CCN documents
        await self.db.execute(
            delete(Document).where(
                Document.organisation_id == organisation_id,
                Document.source_type == "convention_collective_nationale",
                Document.name.ilike(f"%IDCC {idcc}%"),
            )
        )

        # Delete Qdrant vectors (async, best effort)
        try:
            from app.rag.qdrant_store import delete_documents_by_filter
            await delete_documents_by_filter(
                organisation_id=str(organisation_id),
                source_type="convention_collective_nationale",
                idcc=idcc,
            )
        except Exception:
            pass  # Non-blocking, documents are already deleted

        await self.db.delete(org_conv)
        await self.db.commit()

    async def sync_convention(
        self, organisation_id: uuid.UUID, idcc: str, user_id: uuid.UUID
    ) -> OrganisationConvention:
        """Re-sync an already installed convention."""
        result = await self.db.execute(
            select(OrganisationConvention)
            .options(joinedload(OrganisationConvention.ccn))
            .where(
                OrganisationConvention.organisation_id == organisation_id,
                OrganisationConvention.idcc == idcc,
            )
        )
        org_conv = result.scalar_one_or_none()
        if org_conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Convention IDCC {idcc} non trouvée",
            )

        # Reset status and re-enqueue
        org_conv.status = "pending"
        org_conv.error_message = None
        await self.db.commit()

        from app.rag.tasks import enqueue_kali_install
        await enqueue_kali_install(str(org_conv.id), str(user_id))

        return org_conv

    async def verify_org_membership(
        self, organisation_id: uuid.UUID, user_id: uuid.UUID, role: str = "manager"
    ) -> None:
        """Verify user has the required role in the organisation."""
        result = await self.db.execute(
            select(Membership).where(
                Membership.organisation_id == organisation_id,
                Membership.user_id == user_id,
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas membre de cette organisation",
            )
        if role == "manager" and membership.role_in_org != "manager":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul un manager peut gérer les conventions collectives",
            )
