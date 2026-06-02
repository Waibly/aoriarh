import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.emailing import (
    EmailCampaign,
    EmailCampaignEvent,
    EmailCampaignRecipient,
    EmailSequence,
)

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

    # Attribuer l'événement à la POSITION réelle de la dernière étape envoyée.
    # current_step est un index dans la liste triée des étapes, pas une
    # position : on convertit via la séquence (les positions ne commencent pas
    # forcément à 0).
    campaign = (
        await db.execute(
            select(EmailCampaign)
            .options(
                selectinload(EmailCampaign.sequence).selectinload(EmailSequence.steps)
            )
            .where(EmailCampaign.id == recipient.campaign_id)
        )
    ).scalar_one_or_none()

    step_position = 0
    if campaign and campaign.sequence and campaign.sequence.steps:
        steps = sorted(campaign.sequence.steps, key=lambda s: s.position)
        idx = min(max(recipient.current_step - 1, 0), len(steps) - 1)
        step_position = steps[idx].position

    # Dédup : Brevo peut renvoyer plusieurs fois la même ouverture / le même
    # clic. On ne compte qu'une fois par (contact, étape, type) pour éviter des
    # taux > 100 %.
    if event_type != "sent":
        existing = await db.execute(
            select(func.count())
            .select_from(EmailCampaignEvent)
            .where(
                EmailCampaignEvent.recipient_id == recipient.id,
                EmailCampaignEvent.step_position == step_position,
                EmailCampaignEvent.event_type == event_type,
            )
        )
        if (existing.scalar() or 0) > 0:
            return {"status": "ok", "event_type": event_type, "deduped": True}

    event = EmailCampaignEvent(
        campaign_id=recipient.campaign_id,
        recipient_id=recipient.id,
        step_position=step_position,
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
