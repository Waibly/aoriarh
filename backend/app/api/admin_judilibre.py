"""Admin endpoints for Judilibre synchronization."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.document import Document
from app.models.user import User
from app.rag.tasks import (
    enqueue_custom_jurisprudence_sync,
    enqueue_full_jurisprudence_sync,
    enqueue_judilibre_sync,
)
from app.schemas.document import DocumentRead
from app.services.judilibre_service import (
    SOURCE_DEFINITIONS,
    JudilibreService,
    SyncResult,
)

router = APIRouter()


class SyncRequest(BaseModel):
    date_start: date | None = None
    date_end: date | None = None
    chamber: str = "soc"
    publication: str = "b"
    max_decisions: int | None = None


class SyncResponse(BaseModel):
    status: str
    message: str


class JurisprudenceStats(BaseModel):
    total: int
    indexed: int
    pending: int
    indexing: int
    errors: int
    oldest_decision: str | None
    newest_decision: str | None
    last_sync: str | None


@router.get("/stats", response_model=JurisprudenceStats)
async def get_jurisprudence_stats(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> JurisprudenceStats:
    """Get statistics about ingested jurisprudence."""
    service = JudilibreService()
    stats = await service.get_stats(db)
    return JurisprudenceStats(**stats)


@router.post("/sync", response_model=SyncResponse)
async def sync_judilibre(
    body: SyncRequest,
    user: User = Depends(require_role(["admin"])),
) -> SyncResponse:
    """Enqueue a Judilibre synchronization job to the background worker.

    Single chamber/jurisdiction sync. The sync runs asynchronously —
    check the stats endpoint to follow progress.
    """
    await enqueue_judilibre_sync(
        user_id=str(user.id),
        date_start=body.date_start.isoformat() if body.date_start else None,
        date_end=body.date_end.isoformat() if body.date_end else None,
        chamber=body.chamber,
        publication=body.publication,
        max_decisions=body.max_decisions,
    )
    return SyncResponse(
        status="queued",
        message="Synchronisation lancée en arrière-plan. Consultez les statistiques pour suivre la progression.",
    )


@router.post("/sync-all", response_model=SyncResponse)
async def sync_jurisprudence_all(
    user: User = Depends(require_role(["admin"])),
) -> SyncResponse:
    """Enqueue a FULL jurisprudence sync (récurrent, fenêtre 30 jours).

    Lance les passes : Cass. soc / cr / comm / civ2 + Cour d'appel
    chambre sociale (cap 300) + Conseil constitutionnel. Identique à
    ce que fait le cron auto.
    """
    await enqueue_full_jurisprudence_sync(user_id=str(user.id))
    return SyncResponse(
        status="queued",
        message=(
            "Synchronisation jurisprudence complète lancée. "
            "Consultez les statistiques pour suivre la progression."
        ),
    )


@router.post("/initialize", response_model=SyncResponse)
async def initialize_jurisprudence_corpus(
    user: User = Depends(require_role(["admin"])),
) -> SyncResponse:
    """Initialisation one-shot du corpus jurisprudence.

    Lance Cass soc/cr/comm/civ2 sur 1 an publiés + CA chambre sociale
    sur 3 mois (cap 3000). À cliquer UNE seule fois au déploiement de
    la nouvelle config. Idempotent : la dédup par numéro de pourvoi
    empêche les doublons même si on relance.
    """
    from app.rag.tasks import enqueue_jurisprudence_initialization
    await enqueue_jurisprudence_initialization(user_id=str(user.id))
    return SyncResponse(
        status="queued",
        message=(
            "Initialisation du corpus jurisprudence lancée. "
            "Cass 1 an + CA chambre sociale 3 mois. "
            "Suivez l'avancement dans la page Corpus."
        ),
    )


class CustomSyncRequest(BaseModel):
    source: str
    date_start: date
    date_end: date
    max_decisions: int | None = None


class PreviewResponse(BaseModel):
    source: str
    source_label: str
    date_start: str
    date_end: str
    total: int
    warning: str | None = None


@router.get("/preview", response_model=PreviewResponse)
async def preview_jurisprudence_sync(
    source: str = Query(...),
    date_start: date = Query(...),
    date_end: date = Query(...),
    user: User = Depends(require_role(["admin"])),
) -> PreviewResponse:
    """Renvoie le nombre d'arrêts disponibles pour une plage donnée,
    sans rien ingérer. Utilisé par le formulaire admin pour afficher
    un aperçu avant de lancer la synchronisation.
    """
    if source not in SOURCE_DEFINITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Source inconnue : '{source}'. Valides : {sorted(SOURCE_DEFINITIONS)}",
        )
    if date_start > date_end:
        raise HTTPException(status_code=400, detail="date_start doit être ≤ date_end")

    spec = SOURCE_DEFINITIONS[source]
    warning: str | None = None

    try:
        if spec["service"] in ("judilibre", "judilibre_ca"):
            total = await JudilibreService().preview_count(
                jurisdiction=spec["jurisdiction"],
                chamber=spec["chamber"],
                publication=spec["publication"],
                date_start=date_start,
                date_end=date_end,
            )
            if spec["service"] == "judilibre_ca":
                warning = (
                    "Judilibre ne filtre pas les CA par chambre — environ 80 % "
                    "de ces arrêts seront écartés à l'ingestion (chambre non sociale). "
                    "Compte ~20 % d'arrêts réellement ingérés."
                )
                if total >= 10000:
                    warning += (
                        " De plus, l'API Judilibre plafonne à 10 000 résultats par "
                        "fenêtre — réduisez la plage de dates ou utilisez un cap."
                    )
        elif spec["service"] == "conseil_constit":
            from app.services.conseil_constit_service import ConseilConstitService

            total = await ConseilConstitService().preview_count(
                date_start=date_start,
                date_end=date_end,
            )
        else:
            raise HTTPException(status_code=500, detail=f"Service inconnu : {spec['service']}")
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PreviewResponse(
        source=source,
        source_label=spec["label"],
        date_start=date_start.isoformat(),
        date_end=date_end.isoformat(),
        total=total,
        warning=warning,
    )


@router.post("/sync-custom", response_model=SyncResponse)
async def sync_custom(
    body: CustomSyncRequest,
    user: User = Depends(require_role(["admin"])),
) -> SyncResponse:
    """Lance une synchronisation personnalisée sur une plage de dates choisie.

    Source au choix parmi : Cass. soc / cr / com / civ2, CA chambre sociale,
    Conseil constitutionnel. La sync part en arrière-plan ; consulter les
    statistiques pour suivre la progression.
    """
    if body.source not in SOURCE_DEFINITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Source inconnue : '{body.source}'. Valides : {sorted(SOURCE_DEFINITIONS)}",
        )
    if body.date_start > body.date_end:
        raise HTTPException(status_code=400, detail="date_start doit être ≤ date_end")

    await enqueue_custom_jurisprudence_sync(
        user_id=str(user.id),
        source=body.source,
        date_start=body.date_start.isoformat(),
        date_end=body.date_end.isoformat(),
        max_decisions=body.max_decisions,
    )
    label = SOURCE_DEFINITIONS[body.source]["label"]
    return SyncResponse(
        status="queued",
        message=(
            f"Synchronisation lancée : {label} du {body.date_start} au {body.date_end}. "
            "Suivez l'avancement dans la page Corpus."
        ),
    )


@router.get("/decisions", response_model=list[DocumentRead])
async def list_jurisprudence(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> list[DocumentRead]:
    """List ingested jurisprudence decisions (paginated, 1-based)."""
    juris_types = [
        "arret_cour_cassation",
        "arret_conseil_etat",
        "decision_conseil_constitutionnel",
    ]
    result = await db.execute(
        select(Document)
        .where(
            Document.source_type.in_(juris_types),
            Document.organisation_id.is_(None),
        )
        .order_by(Document.date_decision.desc().nullslast(), Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all())  # type: ignore[return-value]
