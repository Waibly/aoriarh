import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.conversation import Message
from app.models.fiche import Fiche
from app.models.organisation import Organisation
from app.models.user import User
from app.services.fiche_service import (
    FicheContent,
    fiche_filename,
    render_fiche_pdf,
    select_fiche_references,
)

router = APIRouter()


class FicheRead(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_id: str | None
    conversation_id: str | None


@router.get("/", response_model=list[FicheRead])
async def list_fiches(
    organisation_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FicheRead]:
    """Liste les fiches de l'utilisateur courant dans cette organisation."""
    rows = (await db.execute(
        select(Fiche, Message.conversation_id)
        .outerjoin(Message, Fiche.message_id == Message.id)
        .where(
            Fiche.organisation_id == organisation_id,
            Fiche.user_id == user.id,
        )
        .order_by(Fiche.created_at.desc())
    )).all()
    return [
        FicheRead(
            id=str(f.id),
            title=f.title,
            created_at=f.created_at,
            updated_at=f.updated_at,
            message_id=str(f.message_id) if f.message_id else None,
            conversation_id=str(conversation_id) if conversation_id else None,
        )
        for f, conversation_id in rows
    ]


async def _get_owned_fiche(
    fiche_id: uuid.UUID, user: User, db: AsyncSession
) -> Fiche:
    fiche = (await db.execute(
        select(Fiche).where(Fiche.id == fiche_id)
    )).scalar_one_or_none()
    if fiche is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fiche non trouvée"
        )
    if fiche.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette fiche",
        )
    return fiche


@router.get("/{fiche_id}/pdf")
async def download_fiche(
    fiche_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Régénère le PDF sans faire passer son ancien contenu pour actualisé."""
    fiche = await _get_owned_fiche(fiche_id, user, db)

    org = (await db.execute(
        select(Organisation.name).where(Organisation.id == fiche.organisation_id)
    )).scalar_one_or_none()

    content = FicheContent(**fiche.content)
    sources = fiche.sources if isinstance(fiche.sources, list) else []
    if not content.body_html and fiche.message_id:
        answer_markdown = (await db.execute(
            select(Message.content).where(Message.id == fiche.message_id)
        )).scalar_one_or_none()
        if answer_markdown:
            sources = select_fiche_references(answer_markdown, sources)
    pdf_bytes = render_fiche_pdf(
        content,
        sources,
        generated_at=fiche.updated_at or fiche.created_at,
        org_name=org,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{fiche_filename(content)}"',
        },
    )


@router.delete("/{fiche_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fiche(
    fiche_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    fiche = await _get_owned_fiche(fiche_id, user, db)
    await db.delete(fiche)
    await db.commit()
