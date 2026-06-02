"""Endpoints publics d'emailing (sans authentification) : désinscription.

Le lien de désinscription est signé (HMAC du recipient_id) pour empêcher de
désinscrire quelqu'un d'autre. Pour éviter qu'un scanner d'emails ne désinscrive
par simple pré-chargement, le GET affiche une page de confirmation et seul le
POST effectue réellement la désinscription.
"""
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.emailing import EmailCampaignRecipient
from app.services.emailing_service import (
    process_unsubscribe,
    verify_unsubscribe_signature,
)

router = APIRouter()


def _page(title: str, message: str, button: str | None = None, action: str | None = None) -> str:
    btn = (
        f'<form method="post" action="{action}">'
        f'<button type="submit">{button}</button></form>'
        if button and action
        else ""
    )
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f5f5f7;
    margin:0; display:flex; min-height:100vh; align-items:center; justify-content:center; }}
  .card {{ background:#fff; max-width:440px; width:90%; padding:40px 32px; border-radius:16px;
    box-shadow:0 4px 24px rgba(0,0,0,.06); text-align:center; }}
  h1 {{ font-size:20px; margin:0 0 12px; color:#1a1a1a; }}
  p {{ color:#555; line-height:1.5; margin:0 0 24px; }}
  button {{ background:#6d28d9; color:#fff; border:0; border-radius:10px; padding:12px 24px;
    font-size:15px; cursor:pointer; }}
  button:hover {{ background:#5b21b6; }}
  .muted {{ font-size:13px; color:#999; margin-top:24px; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p>{btn}
<div class="muted">Aoria RH</div></div></body></html>"""


def _invalid() -> HTMLResponse:
    return HTMLResponse(
        _page("Lien invalide", "Ce lien de désinscription n'est pas valide ou a expiré."),
        status_code=400,
    )


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_confirm(
    rid: str,
    sig: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        recipient_id = uuid.UUID(rid)
    except ValueError:
        return _invalid()
    if not verify_unsubscribe_signature(recipient_id, sig):
        return _invalid()

    recipient = (
        await db.execute(
            select(EmailCampaignRecipient).where(EmailCampaignRecipient.id == recipient_id)
        )
    ).scalar_one_or_none()
    if not recipient:
        return _invalid()

    if recipient.status == "unsubscribed":
        return HTMLResponse(
            _page("Déjà désinscrit", "Cette adresse est déjà désinscrite. Vous ne recevrez plus nos emails.")
        )

    return HTMLResponse(_page(
        "Se désinscrire",
        f"Confirmez-vous la désinscription de <strong>{recipient.email}</strong> ? "
        "Vous ne recevrez plus aucun email de notre part.",
        button="Confirmer la désinscription",
        action=f"/api/v1/emailing/unsubscribe?rid={rid}&sig={sig}",
    ))


@router.post("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_action(
    rid: str,
    sig: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        recipient_id = uuid.UUID(rid)
    except ValueError:
        return _invalid()
    if not verify_unsubscribe_signature(recipient_id, sig):
        return _invalid()

    recipient = await process_unsubscribe(db, recipient_id)
    if not recipient:
        return _invalid()

    return HTMLResponse(_page(
        "Désinscription confirmée",
        "C'est fait. Vous ne recevrez plus aucun email de notre part. À bientôt.",
    ))
