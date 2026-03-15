"""Endpoint de support / feedback utilisateur."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.account import Account
from app.models.user import User
from app.services.email.sender import send_email

router = APIRouter()

_TYPE_LABELS = {
    "bug": "Bug",
    "idea": "Idée",
    "feedback": "Feedback",
    "question": "Question",
}


class SupportRequest(BaseModel):
    type: str = Field(pattern=r"^(bug|idea|feedback|question)$")
    message: str = Field(min_length=5, max_length=2000)
    page_url: str = ""
    user_agent: str = ""


@router.post("/")
async def send_support_message(
    data: SupportRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a support message via email to the support team."""

    # Resolve plan
    plan = "gratuit"
    workspace = "—"
    if user.owned_account:
        plan = user.owned_account.plan
        workspace = user.owned_account.name
    elif user.account_memberships:
        acc_result = await db.execute(
            select(Account).where(Account.id == user.account_memberships[0].account_id)
        )
        acc = acc_result.scalar_one_or_none()
        if acc:
            plan = acc.plan
            workspace = acc.name

    type_label = _TYPE_LABELS.get(data.type, data.type)

    # Build email
    subject = f"[AORIA RH] {type_label} — {user.email}"
    html_content = f"""
    <div style="font-family: sans-serif; max-width: 600px;">
        <h2 style="color: #9952b8; margin-bottom: 4px;">{type_label}</h2>
        <p style="color: #666; font-size: 13px; margin-top: 0;">
            De <strong>{user.full_name}</strong> ({user.email})
        </p>

        <div style="background: #f5f5f5; border-left: 4px solid #9952b8; padding: 16px; margin: 16px 0; border-radius: 4px;">
            <p style="margin: 0; white-space: pre-wrap;">{data.message}</p>
        </div>

        <table style="font-size: 13px; color: #555; border-collapse: collapse;">
            <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Espace de travail</td><td>{workspace}</td></tr>
            <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Plan</td><td>{plan}</td></tr>
            <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Rôle</td><td>{user.role}</td></tr>
            <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Page</td><td>{data.page_url or '—'}</td></tr>
            <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Navigateur</td><td>{data.user_agent or '—'}</td></tr>
        </table>
    </div>
    """

    success = await send_email(
        to_email=settings.support_email,
        to_name="Support AORIA RH",
        subject=subject,
        html_content=html_content,
    )

    if not success:
        raise HTTPException(status_code=503, detail="Impossible d'envoyer le message. Réessayez plus tard.")

    return {"detail": "Message envoyé"}
