"""Admin endpoints for CCN reference management."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.ccn import CcnReference, OrganisationConvention
from app.models.document import Document
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class InstalledCcnItem(BaseModel):
    idcc: str
    titre: str
    titre_court: str | None
    documents_count: int
    orgs_count: int
    articles_count: int | None
    source_date: str | None
    status: str


class InstalledCcnListResponse(BaseModel):
    items: list[InstalledCcnItem]
    total: int


@router.get("/installed", response_model=InstalledCcnListResponse)
async def list_installed_ccn(
    search: str | None = Query(None),
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> InstalledCcnListResponse:
    """List all CCN that have been installed in the shared reference."""
    # Find all IDCCs that have common documents
    doc_q = await db.execute(
        select(
            Document.name,
            func.count(Document.id).label("doc_count"),
        )
        .where(
            Document.organisation_id.is_(None),
            Document.source_type == "convention_collective_nationale",
        )
        .group_by(Document.name)
    )
    # Group by IDCC extracted from name
    import re
    idcc_docs: dict[str, int] = {}
    for row in doc_q.all():
        match = re.search(r"IDCC\s+(\d{4})", row.name)
        if match:
            idcc = match.group(1)
            idcc_docs[idcc] = idcc_docs.get(idcc, 0) + 1

    # Get org counts per IDCC
    org_q = await db.execute(
        select(
            OrganisationConvention.idcc,
            func.count(OrganisationConvention.id).label("orgs"),
            func.max(OrganisationConvention.articles_count).label("articles"),
            func.max(OrganisationConvention.source_date).label("source_date"),
            func.max(OrganisationConvention.status).label("status"),
        )
        .group_by(OrganisationConvention.idcc)
    )
    org_data: dict[str, dict] = {}
    for row in org_q.all():
        org_data[row.idcc] = {
            "orgs": row.orgs,
            "articles": row.articles,
            "source_date": row.source_date,
            "status": row.status or "ready",
        }

    # Merge: all IDCCs from docs + org_conventions
    all_idcc = set(idcc_docs.keys()) | set(org_data.keys())

    # Get CCN reference info
    ref_q = await db.execute(
        select(CcnReference).where(CcnReference.idcc.in_(all_idcc))
    )
    refs = {r.idcc: r for r in ref_q.scalars().all()}

    items: list[InstalledCcnItem] = []
    for idcc in sorted(all_idcc):
        ref = refs.get(idcc)
        od = org_data.get(idcc, {})

        if search:
            q = search.lower()
            titre = (ref.titre if ref else "").lower()
            titre_court = (ref.titre_court if ref else "").lower() or ""
            if q not in idcc and q not in titre and q not in titre_court:
                continue

        items.append(InstalledCcnItem(
            idcc=idcc,
            titre=ref.titre if ref else f"IDCC {idcc}",
            titre_court=ref.titre_court if ref else None,
            documents_count=idcc_docs.get(idcc, 0),
            orgs_count=od.get("orgs", 0),
            articles_count=od.get("articles"),
            source_date=od.get("source_date"),
            status=od.get("status", "ready"),
        ))

    return InstalledCcnListResponse(items=items, total=len(items))


class InstallCcnRequest(BaseModel):
    idcc: str


@router.post("/install")
async def admin_install_ccn(
    body: InstallCcnRequest,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Install a CCN into the shared reference (admin-triggered)."""
    from app.services.kali_service import KaliService

    ccn_ref = await db.get(CcnReference, body.idcc)
    if not ccn_ref:
        raise HTTPException(status_code=404, detail=f"IDCC {body.idcc} introuvable")

    # Check if already installed
    existing = await db.execute(
        select(Document).where(
            Document.organisation_id.is_(None),
            Document.source_type == "convention_collective_nationale",
            Document.name.ilike(f"%IDCC {body.idcc}%"),
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"La CCN IDCC {body.idcc} est déjà installée")

    # Create a temporary OrganisationConvention to use the existing install flow
    # We'll use a fake org_id (NULL) — the docs will be common anyway
    from app.rag.tasks import enqueue_kali_install

    # Create a temp org_conv record for the install job
    temp_conv = OrganisationConvention(
        organisation_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # placeholder
        idcc=body.idcc,
        status="pending",
    )
    db.add(temp_conv)
    await db.commit()
    await db.refresh(temp_conv)

    await enqueue_kali_install(str(temp_conv.id), str(user.id))
    return {"detail": f"Installation de la CCN IDCC {body.idcc} lancée"}


@router.post("/{idcc}/sync")
async def admin_sync_ccn(
    idcc: str,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force re-sync a CCN from KALI."""
    # Find any org_conv for this IDCC to trigger sync
    result = await db.execute(
        select(OrganisationConvention).where(
            OrganisationConvention.idcc == idcc,
        ).limit(1)
    )
    org_conv = result.scalar_one_or_none()
    if not org_conv:
        raise HTTPException(status_code=404, detail=f"CCN IDCC {idcc} non trouvée")

    org_conv.status = "pending"
    org_conv.error_message = None
    await db.commit()

    from app.rag.tasks import enqueue_kali_install
    await enqueue_kali_install(str(org_conv.id), str(user.id), force_refetch=True)
    return {"detail": f"Mise à jour de la CCN IDCC {idcc} lancée"}


@router.delete("/{idcc}")
async def admin_delete_ccn(
    idcc: str,
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a CCN from the shared reference. Only if no org uses it."""
    from sqlalchemy import delete
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
    from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client

    # Check if any org uses this CCN
    orgs_q = await db.execute(
        select(func.count(OrganisationConvention.id)).where(
            OrganisationConvention.idcc == idcc,
        )
    )
    orgs_count = orgs_q.scalar() or 0
    if orgs_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Impossible de supprimer : {orgs_count} organisation(s) utilisent cette CCN",
        )

    # Find and delete common docs
    docs_q = await db.execute(
        select(Document).where(
            Document.organisation_id.is_(None),
            Document.source_type == "convention_collective_nationale",
            Document.name.ilike(f"%IDCC {idcc}%"),
        )
    )
    docs = docs_q.scalars().all()

    # Delete Qdrant vectors
    client = get_qdrant_client()
    for doc in docs:
        try:
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[FieldCondition(key="document_id", match=MatchValue(value=str(doc.id)))]
                    )
                ),
            )
        except Exception:
            logger.warning("Failed to delete Qdrant vectors for doc %s", doc.id)

    # Delete docs from DB
    await db.execute(
        delete(Document).where(
            Document.organisation_id.is_(None),
            Document.source_type == "convention_collective_nationale",
            Document.name.ilike(f"%IDCC {idcc}%"),
        )
    )
    await db.commit()

    return {"detail": f"CCN IDCC {idcc} supprimée ({len(docs)} documents)"}
