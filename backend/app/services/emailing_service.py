import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.emailing import (
    EmailCampaign,
    EmailCampaignEvent,
    EmailCampaignRecipient,
    EmailSequence,
    EmailSequenceStep,
    EmailTemplate,
)

logger = logging.getLogger(__name__)

BREVO_BASE = "https://api.brevo.com/v3"


def _brevo_headers() -> dict[str, str]:
    return {
        "api-key": settings.brevo_api_key,
        "Content-Type": "application/json",
    }


# ──────────────────────────────────────────────
#  Templates
# ──────────────────────────────────────────────


class EmailTemplateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[EmailTemplate]:
        result = await self.db.execute(
            select(EmailTemplate).order_by(EmailTemplate.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, template_id: uuid.UUID) -> EmailTemplate:
        result = await self.db.execute(
            select(EmailTemplate).where(EmailTemplate.id == template_id)
        )
        tpl = result.scalar_one_or_none()
        if not tpl:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Template introuvable")
        return tpl

    async def create(self, name: str, subject: str, html_body: str) -> EmailTemplate:
        tpl = EmailTemplate(name=name, subject=subject, html_body=html_body)
        self.db.add(tpl)
        await self.db.commit()
        await self.db.refresh(tpl)
        return tpl

    async def update(
        self,
        template_id: uuid.UUID,
        name: str | None = None,
        subject: str | None = None,
        html_body: str | None = None,
    ) -> EmailTemplate:
        tpl = await self.get(template_id)
        if name is not None:
            tpl.name = name
        if subject is not None:
            tpl.subject = subject
        if html_body is not None:
            tpl.html_body = html_body
        await self.db.commit()
        await self.db.refresh(tpl)
        return tpl

    async def delete(self, template_id: uuid.UUID) -> None:
        tpl = await self.get(template_id)
        await self.db.delete(tpl)
        await self.db.commit()

    async def send_test(self, template_id: uuid.UUID, to_email: str) -> bool:
        tpl = await self.get(template_id)
        html = _render_variables(tpl.html_body, {
            "prenom": "Jean",
            "nom": "Dupont",
            "entreprise": "Entreprise Test",
            "poste": "DRH",
        })
        return await _send_via_brevo(to_email, None, tpl.subject, html)


# ──────────────────────────────────────────────
#  Sequences
# ──────────────────────────────────────────────


class EmailSequenceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[EmailSequence]:
        result = await self.db.execute(
            select(EmailSequence)
            .options(selectinload(EmailSequence.steps).selectinload(EmailSequenceStep.template))
            .order_by(EmailSequence.updated_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get(self, sequence_id: uuid.UUID) -> EmailSequence:
        result = await self.db.execute(
            select(EmailSequence)
            .options(selectinload(EmailSequence.steps).selectinload(EmailSequenceStep.template))
            .where(EmailSequence.id == sequence_id)
        )
        seq = result.scalar_one_or_none()
        if not seq:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Séquence introuvable")
        return seq

    async def create(self, name: str, steps: list[dict]) -> EmailSequence:
        seq = EmailSequence(name=name)
        self.db.add(seq)
        await self.db.flush()

        for step_data in steps:
            step = EmailSequenceStep(
                sequence_id=seq.id,
                template_id=step_data["template_id"],
                position=step_data["position"],
                delay_days=step_data.get("delay_days", 0),
            )
            self.db.add(step)

        await self.db.commit()
        return await self.get(seq.id)

    async def update(
        self,
        sequence_id: uuid.UUID,
        name: str | None = None,
        steps: list[dict] | None = None,
    ) -> EmailSequence:
        seq = await self.get(sequence_id)

        if seq.status == "active":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Impossible de modifier une séquence active. Mettez-la en pause d'abord.",
            )

        if name is not None:
            seq.name = name

        if steps is not None:
            await self.db.execute(
                delete(EmailSequenceStep).where(EmailSequenceStep.sequence_id == sequence_id)
            )
            for step_data in steps:
                step = EmailSequenceStep(
                    sequence_id=sequence_id,
                    template_id=step_data["template_id"],
                    position=step_data["position"],
                    delay_days=step_data.get("delay_days", 0),
                )
                self.db.add(step)

        await self.db.commit()
        return await self.get(sequence_id)

    async def delete(self, sequence_id: uuid.UUID) -> None:
        seq = await self.get(sequence_id)
        if seq.status == "active":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Impossible de supprimer une séquence active.",
            )
        await self.db.delete(seq)
        await self.db.commit()


# ──────────────────────────────────────────────
#  Campaigns
# ──────────────────────────────────────────────


class EmailCampaignService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self, status_filter: str | None = None) -> list[dict]:
        query = select(EmailCampaign).options(
            selectinload(EmailCampaign.sequence)
        ).order_by(EmailCampaign.updated_at.desc())

        if status_filter and status_filter != "all":
            query = query.where(EmailCampaign.status == status_filter)

        result = await self.db.execute(query)
        campaigns = list(result.scalars().unique().all())

        items = []
        for c in campaigns:
            count_result = await self.db.execute(
                select(func.count()).select_from(EmailCampaignRecipient)
                .where(EmailCampaignRecipient.campaign_id == c.id)
            )
            recipient_count = count_result.scalar() or 0

            items.append({
                "id": c.id,
                "name": c.name,
                "sequence_id": c.sequence_id,
                "sequence_name": c.sequence.name if c.sequence else None,
                "brevo_list_ids": c.brevo_list_ids,
                "status": c.status,
                "scheduled_at": c.scheduled_at,
                "current_step": c.current_step,
                "recipient_count": recipient_count,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            })

        return items

    async def get(self, campaign_id: uuid.UUID) -> EmailCampaign:
        result = await self.db.execute(
            select(EmailCampaign)
            .options(
                selectinload(EmailCampaign.sequence)
                .selectinload(EmailSequence.steps)
                .selectinload(EmailSequenceStep.template)
            )
            .where(EmailCampaign.id == campaign_id)
        )
        campaign = result.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campagne introuvable")
        return campaign

    async def create(
        self,
        name: str,
        sequence_id: uuid.UUID,
        brevo_list_ids: list[int],
        scheduled_at: datetime | None = None,
    ) -> EmailCampaign:
        seq_result = await self.db.execute(
            select(EmailSequence).where(EmailSequence.id == sequence_id)
        )
        if not seq_result.scalar_one_or_none():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Séquence introuvable")

        campaign = EmailCampaign(
            name=name,
            sequence_id=sequence_id,
            brevo_list_ids=brevo_list_ids,
            scheduled_at=scheduled_at,
            status="draft",
        )
        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def launch(self, campaign_id: uuid.UUID) -> EmailCampaign:
        campaign = await self.get(campaign_id)

        if campaign.status not in ("draft", "paused"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Impossible de lancer une campagne en statut '{campaign.status}'",
            )

        contacts = await _fetch_brevo_list_contacts(campaign.brevo_list_ids)
        if not contacts:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Aucun contact trouvé dans les listes sélectionnées",
            )

        existing_emails = set()
        result = await self.db.execute(
            select(EmailCampaignRecipient.email)
            .where(EmailCampaignRecipient.campaign_id == campaign_id)
        )
        existing_emails = {row[0] for row in result.all()}

        for contact in contacts:
            if contact["email"] not in existing_emails:
                recipient = EmailCampaignRecipient(
                    campaign_id=campaign_id,
                    email=contact["email"],
                    brevo_contact_id=contact.get("id"),
                    first_name=contact.get("first_name"),
                    last_name=contact.get("last_name"),
                    company=contact.get("company"),
                )
                self.db.add(recipient)

        campaign.status = "running"
        if not campaign.scheduled_at:
            campaign.scheduled_at = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def pause(self, campaign_id: uuid.UUID) -> EmailCampaign:
        campaign = await self.get(campaign_id)
        if campaign.status != "running":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La campagne n'est pas en cours")
        campaign.status = "paused"
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def resume(self, campaign_id: uuid.UUID) -> EmailCampaign:
        campaign = await self.get(campaign_id)
        if campaign.status != "paused":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La campagne n'est pas en pause")
        campaign.status = "running"
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def delete(self, campaign_id: uuid.UUID) -> None:
        campaign = await self.get(campaign_id)
        if campaign.status == "running":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Impossible de supprimer une campagne en cours. Mettez-la en pause d'abord.",
            )
        await self.db.delete(campaign)
        await self.db.commit()

    async def get_stats(self, campaign_id: uuid.UUID) -> dict:
        campaign = await self.get(campaign_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(EmailCampaignRecipient)
            .where(EmailCampaignRecipient.campaign_id == campaign_id)
        )
        total_recipients = count_result.scalar() or 0

        steps_stats = []
        for step in sorted(campaign.sequence.steps, key=lambda s: s.position):
            events_result = await self.db.execute(
                select(
                    EmailCampaignEvent.event_type,
                    func.count(),
                ).where(
                    EmailCampaignEvent.campaign_id == campaign_id,
                    EmailCampaignEvent.step_position == step.position,
                ).group_by(EmailCampaignEvent.event_type)
            )
            counts = dict(events_result.all())

            steps_stats.append({
                "step_position": step.position,
                "template_name": step.template.name if step.template else None,
                "delay_days": step.delay_days,
                "sent": counts.get("sent", 0),
                "opened": counts.get("opened", 0),
                "clicked": counts.get("clicked", 0),
                "bounced": counts.get("bounced", 0),
                "unsubscribed": counts.get("unsubscribed", 0),
            })

        return {
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "status": campaign.status,
            "total_recipients": total_recipients,
            "steps": steps_stats,
        }


# ──────────────────────────────────────────────
#  Brevo API helpers
# ──────────────────────────────────────────────


async def fetch_brevo_lists() -> list[dict]:
    if not settings.brevo_api_key:
        return []

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BREVO_BASE}/contacts/lists",
            headers=_brevo_headers(),
            params={"limit": 50, "offset": 0},
            timeout=10.0,
        )

    if response.status_code != 200:
        logger.error("Brevo lists API error %s: %s", response.status_code, response.text)
        return []

    data = response.json()
    return [
        {
            "id": lst["id"],
            "name": lst["name"],
            "total_subscribers": lst.get("totalSubscribers", 0),
            "total_blacklisted": lst.get("totalBlacklisted", 0),
        }
        for lst in data.get("lists", [])
    ]


async def fetch_brevo_list_contacts(list_id: int, limit: int = 500) -> list[dict]:
    if not settings.brevo_api_key:
        return []

    contacts = []
    offset = 0

    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                f"{BREVO_BASE}/contacts/lists/{list_id}/contacts",
                headers=_brevo_headers(),
                params={"limit": min(limit - len(contacts), 500), "offset": offset},
                timeout=15.0,
            )

            if response.status_code != 200:
                logger.error("Brevo contacts API error %s: %s", response.status_code, response.text)
                break

            data = response.json()
            for c in data.get("contacts", []):
                attrs = c.get("attributes", {})
                contacts.append({
                    "id": c.get("id"),
                    "email": c.get("email", ""),
                    "first_name": attrs.get("PRENOM") or attrs.get("FIRSTNAME"),
                    "last_name": attrs.get("NOM") or attrs.get("LASTNAME"),
                    "company": attrs.get("ENTREPRISE") or attrs.get("COMPANY") or attrs.get("SMS"),
                })

            if len(data.get("contacts", [])) < 500 or len(contacts) >= limit:
                break
            offset += 500

    return contacts


async def _fetch_brevo_list_contacts(list_ids: list[int]) -> list[dict]:
    seen_emails: set[str] = set()
    all_contacts: list[dict] = []

    for list_id in list_ids:
        contacts = await fetch_brevo_list_contacts(list_id)
        for c in contacts:
            if c["email"] and c["email"] not in seen_emails:
                seen_emails.add(c["email"])
                all_contacts.append(c)

    return all_contacts


def _render_variables(html: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        html = html.replace("{{" + key + "}}", value or "")
    return html


async def _send_via_brevo(
    to_email: str,
    to_name: str | None,
    subject: str,
    html_content: str,
) -> bool:
    if not settings.brevo_api_key:
        logger.warning("Brevo API key not configured, skipping email to %s", to_email)
        return False

    payload = {
        "sender": {"name": "AORIA RH", "email": "noreply@aoriarh.fr"},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BREVO_BASE}/smtp/email",
            json=payload,
            headers=_brevo_headers(),
            timeout=10.0,
        )

    if response.status_code in (200, 201):
        logger.info("Campaign email sent to %s: %s", to_email, subject)
        return True

    logger.error("Brevo send error %s: %s", response.status_code, response.text)
    return False


# ──────────────────────────────────────────────
#  Cron job : process active campaigns
# ──────────────────────────────────────────────


async def process_campaign_emails(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    total_sent = 0

    result = await db.execute(
        select(EmailCampaign)
        .options(
            selectinload(EmailCampaign.sequence)
            .selectinload(EmailSequence.steps)
            .selectinload(EmailSequenceStep.template)
        )
        .where(EmailCampaign.status == "running")
    )
    campaigns = list(result.scalars().unique().all())

    for campaign in campaigns:
        if not campaign.scheduled_at:
            continue

        steps = sorted(campaign.sequence.steps, key=lambda s: s.position)
        if not steps:
            continue

        recipients_result = await db.execute(
            select(EmailCampaignRecipient).where(
                EmailCampaignRecipient.campaign_id == campaign.id,
                EmailCampaignRecipient.status == "active",
            )
        )
        recipients = list(recipients_result.scalars().all())

        all_done = True

        for recipient in recipients:
            next_step_index = recipient.current_step
            if next_step_index >= len(steps):
                continue

            all_done = False
            step = steps[next_step_index]
            send_after = campaign.scheduled_at + timedelta(days=step.delay_days)

            if now < send_after:
                continue

            variables = {
                "prenom": recipient.first_name or "",
                "nom": recipient.last_name or "",
                "entreprise": recipient.company or "",
                "poste": "",
            }
            html = _render_variables(step.template.html_body, variables)
            subject = _render_variables(step.template.subject, variables)

            success = await _send_via_brevo(
                to_email=recipient.email,
                to_name=recipient.first_name,
                subject=subject,
                html_content=html,
            )

            if success:
                recipient.current_step = next_step_index + 1
                recipient.last_sent_at = now

                event = EmailCampaignEvent(
                    campaign_id=campaign.id,
                    recipient_id=recipient.id,
                    step_position=step.position,
                    event_type="sent",
                    occurred_at=now,
                )
                db.add(event)
                total_sent += 1

                if recipient.current_step >= len(steps):
                    recipient.status = "completed"

        if all_done and recipients:
            campaign.status = "completed"

        await db.commit()

    logger.info("Campaign cron: %d emails sent", total_sent)
    return total_sent
