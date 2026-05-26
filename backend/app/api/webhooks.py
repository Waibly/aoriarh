import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.database import get_db
from app.models.emailing import EmailCampaignEvent, EmailCampaignRecipient

logger = logging.getLogger(__name__)

router = APIRouter()

EVENT_MAP = {
    "delivered": "sent",
    "request": "sent",
    "opened": "opened",
    "unique_opened": "opened",
    "click": "clicked",
    "hard_bounce": "bounced",
    "soft_bounce": "bounced",
    "spam": "unsubscribed",
    "unsubscribed": "unsubscribed",
}


@router.post("/brevo", status_code=status.HTTP_200_OK)
async def brevo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "invalid payload"}

    brevo_event = payload.get("event")
    email = payload.get("email")

    if not brevo_event or not email:
        return {"status": "ignored", "reason": "missing event or email"}

    event_type = EVENT_MAP.get(brevo_event)
    if not event_type:
        return {"status": "ignored", "reason": f"unmapped event: {brevo_event}"}

    result = await db.execute(
        select(EmailCampaignRecipient)
        .where(
            EmailCampaignRecipient.email == email,
            EmailCampaignRecipient.status.in_(["active", "completed"]),
        )
        .order_by(EmailCampaignRecipient.last_sent_at.desc())
        .limit(1)
    )
    recipient = result.scalar_one_or_none()

    if not recipient:
        return {"status": "ignored", "reason": "recipient not found"}

    event = EmailCampaignEvent(
        campaign_id=recipient.campaign_id,
        recipient_id=recipient.id,
        step_position=max(recipient.current_step - 1, 0),
        event_type=event_type,
        occurred_at=datetime.now(UTC),
    )
    db.add(event)

    if event_type in ("bounced", "unsubscribed"):
        recipient.status = event_type
        logger.info(
            "Recipient %s marked as %s (campaign %s)",
            email, event_type, recipient.campaign_id,
        )

    await db.commit()
    return {"status": "ok", "event_type": event_type, "email": email}
