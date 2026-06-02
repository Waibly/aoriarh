import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.emailing import (
    EmailCampaign,
    EmailCampaignEvent,
    EmailCampaignRecipient,
    EmailCampaignWave,
    EmailSequence,
    EmailSequenceStep,
    EmailSequenceStepBranch,
    EmailTemplate,
)

logger = logging.getLogger(__name__)

BREVO_BASE = "https://api.brevo.com/v3"

# Limite quotidienne du plan Brevo (mails / jour, tout compte confondu).
BREVO_DAILY_LIMIT = 300
# Taille maximale d'une vague d'envoi.
WAVE_MAX_SIZE = 100
# Plafond d'envois par passage du moteur (toutes les heures) : on ne touche
# jamais plus de 100 personnes d'un coup, vagues ET relances confondues.
MAX_PER_RUN = 100
# Marge réservée aux mails transactionnels (inscription, etc.) qui consomment
# aussi le quota Brevo. Le moteur de campagnes ne dépasse pas (limite - marge)
# envois par jour.
DAILY_SEND_RESERVE = 20
# Nombre d'échecs d'envoi consécutifs avant d'abandonner un contact ("failed").
MAX_SEND_ATTEMPTS = 3


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

    async def create(self, name: str, subject: str, html_body: str, preview_text: str | None = None) -> EmailTemplate:
        tpl = EmailTemplate(name=name, subject=subject, preview_text=preview_text, html_body=html_body)
        self.db.add(tpl)
        await self.db.commit()
        await self.db.refresh(tpl)
        return tpl

    async def update(
        self,
        template_id: uuid.UUID,
        name: str | None = None,
        subject: str | None = None,
        preview_text: str | None = None,
        html_body: str | None = None,
    ) -> EmailTemplate:
        tpl = await self.get(template_id)
        if name is not None:
            tpl.name = name
        if subject is not None:
            tpl.subject = subject
        if preview_text is not None:
            tpl.preview_text = preview_text
        if html_body is not None:
            tpl.html_body = html_body
        await self.db.commit()
        await self.db.refresh(tpl)
        return tpl

    async def delete(self, template_id: uuid.UUID) -> None:
        tpl = await self.get(template_id)
        await self.db.delete(tpl)
        await self.db.commit()

    async def send_test(self, template_id: uuid.UUID, to_emails: list[str]) -> list[dict]:
        tpl = await self.get(template_id)
        html = _render_variables(tpl.html_body, {
            "prenom": "Jean",
            "nom": "Dupont",
            "entreprise": "Entreprise Test",
            "poste": "DRH",
        })
        preview = _render_variables(tpl.preview_text, {
            "prenom": "Jean",
            "nom": "Dupont",
            "entreprise": "Entreprise Test",
            "poste": "DRH",
        }) if tpl.preview_text else None
        results = []
        for email in to_emails:
            result = await _send_via_brevo(email, None, tpl.subject, html, preview_text=preview)
            results.append({"email": email, "sent": result == "ok"})
        return results


# ──────────────────────────────────────────────
#  Sequences
# ──────────────────────────────────────────────


def _sequence_load_options():
    return (
        selectinload(EmailSequence.steps)
        .selectinload(EmailSequenceStep.template),
        selectinload(EmailSequence.steps)
        .selectinload(EmailSequenceStep.branches)
        .selectinload(EmailSequenceStepBranch.template),
    )


class EmailSequenceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[EmailSequence]:
        result = await self.db.execute(
            select(EmailSequence)
            .options(*_sequence_load_options())
            .order_by(EmailSequence.updated_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get(self, sequence_id: uuid.UUID) -> EmailSequence:
        result = await self.db.execute(
            select(EmailSequence)
            .options(*_sequence_load_options())
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
                template_id=step_data.get("template_id"),
                position=step_data["position"],
                delay_days=step_data.get("delay_days", 0),
            )
            self.db.add(step)
            await self.db.flush()

            for branch_data in step_data.get("branches", []):
                branch = EmailSequenceStepBranch(
                    step_id=step.id,
                    condition=branch_data["condition"],
                    template_id=branch_data["template_id"],
                )
                self.db.add(branch)

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
                    template_id=step_data.get("template_id"),
                    position=step_data["position"],
                    delay_days=step_data.get("delay_days", 0),
                )
                self.db.add(step)
                await self.db.flush()

                for branch_data in step_data.get("branches", []):
                    branch = EmailSequenceStepBranch(
                        step_id=step.id,
                        condition=branch_data["condition"],
                        template_id=branch_data["template_id"],
                    )
                    self.db.add(branch)

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
                .selectinload(EmailSequenceStep.template),
                # Les branches + leur template sont nécessaires à get_stats ;
                # sans ce préchargement, l'accès déclenche un lazy-load IO
                # interdit en async (MissingGreenlet).
                selectinload(EmailCampaign.sequence)
                .selectinload(EmailSequence.steps)
                .selectinload(EmailSequenceStep.branches)
                .selectinload(EmailSequenceStepBranch.template),
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

            branch_stats = []
            if step.branches:
                for branch in step.branches:
                    br_events = await self.db.execute(
                        select(
                            EmailCampaignEvent.event_type,
                            func.count(),
                        ).where(
                            EmailCampaignEvent.campaign_id == campaign_id,
                            EmailCampaignEvent.step_position == step.position,
                            EmailCampaignEvent.branch_condition == branch.condition,
                        ).group_by(EmailCampaignEvent.event_type)
                    )
                    br_counts = dict(br_events.all())
                    branch_stats.append({
                        "condition": branch.condition,
                        "template_name": branch.template.name if branch.template else None,
                        "sent": br_counts.get("sent", 0),
                        "opened": br_counts.get("opened", 0),
                        "clicked": br_counts.get("clicked", 0),
                        "bounced": br_counts.get("bounced", 0),
                        "unsubscribed": br_counts.get("unsubscribed", 0),
                    })

            steps_stats.append({
                "step_position": step.position,
                "template_name": step.template.name if step.template else None,
                "delay_days": step.delay_days,
                "sent": counts.get("sent", 0),
                "opened": counts.get("opened", 0),
                "clicked": counts.get("clicked", 0),
                "bounced": counts.get("bounced", 0),
                "unsubscribed": counts.get("unsubscribed", 0),
                "branches": branch_stats,
            })

        return {
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "status": campaign.status,
            "total_recipients": total_recipients,
            "steps": steps_stats,
        }

    # ──────────────────────────────────────────
    #  Vagues d'envoi (envoi par tranches de 100)
    # ──────────────────────────────────────────

    async def get_waves(self, campaign_id: uuid.UUID) -> dict:
        campaign = await self.get(campaign_id)

        waves_result = await self.db.execute(
            select(EmailCampaignWave)
            .where(EmailCampaignWave.campaign_id == campaign_id)
            .order_by(EmailCampaignWave.number)
        )
        waves = list(waves_result.scalars().all())

        # Agrégats par vague (démarrés / terminés) en une seule requête.
        agg_result = await self.db.execute(
            select(
                EmailCampaignRecipient.wave_id,
                func.count().label("total"),
                func.count()
                .filter(EmailCampaignRecipient.current_step > 0)
                .label("started"),
                func.count()
                .filter(EmailCampaignRecipient.status == "completed")
                .label("done"),
            )
            .where(
                EmailCampaignRecipient.campaign_id == campaign_id,
                EmailCampaignRecipient.wave_id.isnot(None),
            )
            .group_by(EmailCampaignRecipient.wave_id)
        )
        agg = {row.wave_id: row for row in agg_result.all()}

        wave_items = []
        for w in waves:
            row = agg.get(w.id)
            started = row.started if row else 0
            done = row.done if row else 0
            if w.recipient_count > 0 and done >= w.recipient_count:
                status_label = "done"
            elif started > 0:
                status_label = "sending"
            else:
                status_label = "scheduled"
            wave_items.append({
                "id": w.id,
                "number": w.number,
                "scheduled_at": w.scheduled_at,
                "recipient_count": w.recipient_count,
                "sent_count": started,
                "done_count": done,
                "status": status_label,
            })

        total_result = await self.db.execute(
            select(func.count()).select_from(EmailCampaignRecipient)
            .where(EmailCampaignRecipient.campaign_id == campaign_id)
        )
        total_recipients = total_result.scalar() or 0

        pending_result = await self.db.execute(
            select(func.count()).select_from(EmailCampaignRecipient)
            .where(
                EmailCampaignRecipient.campaign_id == campaign_id,
                EmailCampaignRecipient.wave_id.is_(None),
                EmailCampaignRecipient.status == "active",
            )
        )
        pending_count = pending_result.scalar() or 0

        return {
            "campaign_id": campaign_id,
            "status": campaign.status,
            "total_recipients": total_recipients,
            "pending_count": pending_count,
            "daily_limit": BREVO_DAILY_LIMIT,
            "wave_max_size": WAVE_MAX_SIZE,
            "waves": wave_items,
        }

    @staticmethod
    def _contact_dict(r: EmailCampaignRecipient) -> dict:
        return {
            "email": r.email,
            "first_name": r.first_name,
            "last_name": r.last_name,
            "company": r.company,
        }

    async def preview_next_contacts(
        self, campaign_id: uuid.UUID, count: int
    ) -> list[dict]:
        """Les N prochains contacts du stock — ceux qui partiront dans la
        prochaine vague. Même ordre que schedule_wave, pour montrer « qui »
        avant de valider."""
        await self.get(campaign_id)
        count = min(max(count, 1), WAVE_MAX_SIZE)
        result = await self.db.execute(
            select(EmailCampaignRecipient)
            .where(
                EmailCampaignRecipient.campaign_id == campaign_id,
                EmailCampaignRecipient.wave_id.is_(None),
                EmailCampaignRecipient.status == "active",
            )
            .order_by(EmailCampaignRecipient.created_at, EmailCampaignRecipient.id)
            .limit(count)
        )
        return [self._contact_dict(r) for r in result.scalars().all()]

    async def list_wave_contacts(
        self, campaign_id: uuid.UUID, wave_id: uuid.UUID
    ) -> list[dict]:
        wave = (
            await self.db.execute(
                select(EmailCampaignWave).where(
                    EmailCampaignWave.id == wave_id,
                    EmailCampaignWave.campaign_id == campaign_id,
                )
            )
        ).scalar_one_or_none()
        if not wave:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vague introuvable")
        result = await self.db.execute(
            select(EmailCampaignRecipient)
            .where(EmailCampaignRecipient.wave_id == wave_id)
            .order_by(EmailCampaignRecipient.created_at, EmailCampaignRecipient.id)
        )
        return [self._contact_dict(r) for r in result.scalars().all()]

    async def schedule_wave(
        self,
        campaign_id: uuid.UUID,
        count: int,
        scheduled_at: datetime,
    ) -> EmailCampaignWave:
        campaign = await self.get(campaign_id)
        if campaign.status != "running":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Lancez la campagne avant de programmer un envoi.",
            )

        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=UTC)

        count = min(max(count, 1), WAVE_MAX_SIZE)

        # Garde-fou Brevo : 300 mails / jour, toutes campagnes confondues.
        day_start = scheduled_at.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        already_result = await self.db.execute(
            select(func.coalesce(func.sum(EmailCampaignWave.recipient_count), 0))
            .where(
                EmailCampaignWave.scheduled_at >= day_start,
                EmailCampaignWave.scheduled_at < day_end,
            )
        )
        already = already_result.scalar() or 0
        if already + count > BREVO_DAILY_LIMIT:
            remaining = max(BREVO_DAILY_LIMIT - already, 0)
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Limite Brevo de {BREVO_DAILY_LIMIT} mails/jour atteinte pour le "
                f"{day_start.date().isoformat()} : il reste {remaining} envoi(s) "
                "possible(s) ce jour-là.",
            )

        # Verrouille les N prochains contacts en stock. Un contact = une seule
        # vague : SKIP LOCKED + passage en wave_id non nul rendent impossible
        # qu'il soit pris par deux vagues.
        picked_result = await self.db.execute(
            select(EmailCampaignRecipient)
            .where(
                EmailCampaignRecipient.campaign_id == campaign_id,
                EmailCampaignRecipient.wave_id.is_(None),
                EmailCampaignRecipient.status == "active",
            )
            .order_by(EmailCampaignRecipient.created_at, EmailCampaignRecipient.id)
            .limit(count)
            .with_for_update(skip_locked=True)
        )
        recipients = list(picked_result.scalars().all())
        if not recipients:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Plus aucun contact en attente dans cette campagne.",
            )

        number_result = await self.db.execute(
            select(func.coalesce(func.max(EmailCampaignWave.number), 0))
            .where(EmailCampaignWave.campaign_id == campaign_id)
        )
        next_number = (number_result.scalar() or 0) + 1

        wave = EmailCampaignWave(
            campaign_id=campaign_id,
            number=next_number,
            scheduled_at=scheduled_at,
            recipient_count=len(recipients),
        )
        self.db.add(wave)
        await self.db.flush()

        for r in recipients:
            r.wave_id = wave.id
            r.scheduled_at = scheduled_at

        await self.db.commit()
        await self.db.refresh(wave)
        return wave

    async def cancel_wave(
        self, campaign_id: uuid.UUID, wave_id: uuid.UUID
    ) -> None:
        wave_result = await self.db.execute(
            select(EmailCampaignWave).where(
                EmailCampaignWave.id == wave_id,
                EmailCampaignWave.campaign_id == campaign_id,
            )
        )
        wave = wave_result.scalar_one_or_none()
        if not wave:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vague introuvable")

        started_result = await self.db.execute(
            select(func.count()).select_from(EmailCampaignRecipient).where(
                EmailCampaignRecipient.wave_id == wave_id,
                EmailCampaignRecipient.current_step > 0,
            )
        )
        if (started_result.scalar() or 0) > 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cette vague est déjà partie, impossible de l'annuler.",
            )

        # Remet les contacts en stock.
        await self.db.execute(
            update(EmailCampaignRecipient)
            .where(EmailCampaignRecipient.wave_id == wave_id)
            .values(wave_id=None, scheduled_at=None)
        )
        await self.db.delete(wave)
        await self.db.commit()


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
            "total_subscribers": lst.get("uniqueSubscribers", 0),
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
        # Récupère TOUS les contacts de la liste (la valeur par défaut de
        # fetch_brevo_list_contacts plafonne à 500, ce qui tronquerait une
        # grosse liste). Une campagne doit charger l'intégralité du stock.
        contacts = await fetch_brevo_list_contacts(list_id, limit=1_000_000)
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
    preview_text: str | None = None,
) -> str:
    """Envoie un mail via Brevo. Renvoie un statut :

    - "ok"    : envoyé (HTTP 2xx)
    - "quota" : quota Brevo atteint (HTTP 429) → arrêter le run, réessayer plus tard
    - "skip"  : pas de clé API configurée → rien à faire
    - "error" : autre échec (réseau, 4xx/5xx) → réessayer ce contact
    """
    if not settings.brevo_api_key:
        logger.warning("Brevo API key not configured, skipping email to %s", to_email)
        return "skip"

    payload: dict = {
        "sender": {"name": "Aoria RH", "email": "noreply@aoriarh.fr"},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    if preview_text:
        payload["previewText"] = preview_text

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BREVO_BASE}/smtp/email",
                json=payload,
                headers=_brevo_headers(),
                timeout=10.0,
            )
    except httpx.HTTPError as exc:
        logger.error("Brevo send network error to %s: %s", to_email, exc)
        return "error"

    if response.status_code in (200, 201):
        logger.info("Campaign email sent to %s: %s", to_email, subject)
        return "ok"

    if response.status_code == 429:
        logger.warning("Brevo quota/rate limit reached (429), stopping run")
        return "quota"

    logger.error("Brevo send error %s: %s", response.status_code, response.text)
    return "error"


# ──────────────────────────────────────────────
#  Cron job : process active campaigns
# ──────────────────────────────────────────────


CONDITION_LABELS = {
    "opened_and_clicked": "Ouvert + cliqué",
    "opened_not_clicked": "Ouvert, pas cliqué",
    "not_opened": "Pas ouvert",
}


def _determine_recipient_condition(
    events: list[EmailCampaignEvent],
    prev_step_position: int,
) -> str:
    prev_events = [e for e in events if e.step_position == prev_step_position]
    event_types = {e.event_type for e in prev_events}

    has_opened = "opened" in event_types
    has_clicked = "clicked" in event_types

    if has_opened and has_clicked:
        return "opened_and_clicked"
    elif has_opened:
        return "opened_not_clicked"
    else:
        return "not_opened"


def _resolve_template_for_step(step, steps, next_step_index, events):
    """Retourne (template, branch_condition) pour l'étape courante d'un contact.

    Gère le branchement conditionnel (en fonction du comportement à l'étape
    précédente). branch_condition est None hors branchement.
    """
    if step.branches and next_step_index > 0:
        prev_step = steps[next_step_index - 1]
        condition = _determine_recipient_condition(events, prev_step.position)
        for branch in step.branches:
            if branch.condition == condition:
                return (branch.template or step.template), condition
        return step.template, condition
    return step.template, None


async def process_campaign_emails(db: AsyncSession) -> int:
    now = datetime.now(UTC)

    # 1) Budget du passage : jamais plus de MAX_PER_RUN d'un coup, et au global
    #    on ne dépasse pas (limite Brevo - marge transactionnels) par jour.
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        await db.execute(
            select(func.count()).select_from(EmailCampaignEvent).where(
                EmailCampaignEvent.event_type == "sent",
                EmailCampaignEvent.occurred_at >= day_start,
            )
        )
    ).scalar() or 0
    daily_remaining = max(0, (BREVO_DAILY_LIMIT - DAILY_SEND_RESERVE) - sent_today)
    run_budget = min(MAX_PER_RUN, daily_remaining)
    if run_budget <= 0:
        logger.info(
            "Campaign cron: plafond journalier atteint (%d envoyés aujourd'hui)",
            sent_today,
        )
        return 0

    # 2) Campagnes actives + leurs séquences
    result = await db.execute(
        select(EmailCampaign)
        .options(
            selectinload(EmailCampaign.sequence)
            .selectinload(EmailSequence.steps)
            .selectinload(EmailSequenceStep.template),
            selectinload(EmailCampaign.sequence)
            .selectinload(EmailSequence.steps)
            .selectinload(EmailSequenceStep.branches)
            .selectinload(EmailSequenceStepBranch.template),
        )
        .where(EmailCampaign.status == "running")
    )
    campaigns = list(result.scalars().unique().all())

    # 3) Collecte de TOUS les envois dus, toutes campagnes confondues. On
    #    capture des VALEURS simples (pas d'objet ORM) pour pouvoir commiter
    #    après chaque envoi sans souci d'expiration de session.
    pending: list[dict] = []
    for campaign in campaigns:
        steps = sorted(campaign.sequence.steps, key=lambda s: s.position)
        if not steps:
            continue

        # Seuls les contacts rattachés à une vague programmée (scheduled_at non
        # nul) sont envoyés ; le stock (scheduled_at NULL) attend sa vague.
        recipients_result = await db.execute(
            select(EmailCampaignRecipient)
            .options(selectinload(EmailCampaignRecipient.events))
            .where(
                EmailCampaignRecipient.campaign_id == campaign.id,
                EmailCampaignRecipient.status == "active",
                EmailCampaignRecipient.scheduled_at.isnot(None),
            )
        )
        for recipient in recipients_result.scalars().unique().all():
            idx = recipient.current_step
            if idx >= len(steps):
                continue

            step = steps[idx]
            # Le calendrier (mail 1 puis relances J+N) est ancré sur la date de
            # la vague du contact, propre à chaque vague.
            wave_date = recipient.scheduled_at
            if wave_date.tzinfo is None:
                wave_date = wave_date.replace(tzinfo=UTC)
            send_after = wave_date + timedelta(days=step.delay_days)
            if now < send_after:
                continue

            template, branch_condition = _resolve_template_for_step(
                step, steps, idx, recipient.events
            )
            if not template:
                continue

            pending.append({
                "send_after": send_after,
                "recipient_id": recipient.id,
                "campaign_id": campaign.id,
                "email": recipient.email,
                "first_name": recipient.first_name,
                "last_name": recipient.last_name,
                "company": recipient.company,
                "current_step": idx,
                "len_steps": len(steps),
                "send_attempts": recipient.send_attempts or 0,
                "step_position": step.position,
                "branch_condition": branch_condition,
                "html_body": template.html_body,
                "subject": template.subject,
                "preview_text": template.preview_text,
            })

    # 4) Les plus anciens d'abord : relances et vieilles vagues prioritaires.
    pending.sort(key=lambda p: p["send_after"])

    # 5) Envoi dans la limite du budget, avec persistance APRÈS chaque envoi
    #    (un crash ne peut plus re-déclencher des mails déjà partis).
    total_sent = 0
    for p in pending:
        if total_sent >= run_budget:
            break

        variables = {
            "prenom": p["first_name"] or "",
            "nom": p["last_name"] or "",
            "entreprise": p["company"] or "",
            "poste": "",
        }
        html = _render_variables(p["html_body"], variables)
        subject = _render_variables(p["subject"], variables)
        preview = _render_variables(p["preview_text"], variables) if p["preview_text"] else None

        status_result = await _send_via_brevo(
            to_email=p["email"],
            to_name=p["first_name"],
            subject=subject,
            html_content=html,
            preview_text=preview,
        )

        if status_result == "ok":
            new_step = p["current_step"] + 1
            await db.execute(
                update(EmailCampaignRecipient)
                .where(EmailCampaignRecipient.id == p["recipient_id"])
                .values(
                    current_step=new_step,
                    last_sent_at=now,
                    send_attempts=0,
                    status="completed" if new_step >= p["len_steps"] else "active",
                )
            )
            db.add(EmailCampaignEvent(
                campaign_id=p["campaign_id"],
                recipient_id=p["recipient_id"],
                step_position=p["step_position"],
                event_type="sent",
                branch_condition=p["branch_condition"],
                occurred_at=now,
            ))
            await db.commit()
            total_sent += 1
        elif status_result in ("quota", "skip"):
            # Quota Brevo atteint (429) ou pas de clé : on stoppe, on reprendra
            # au prochain passage. Les envois déjà faits restent persistés.
            logger.warning("Campaign cron: arrêt du run (%s)", status_result)
            break
        else:  # "error"
            new_attempts = p["send_attempts"] + 1
            new_status = "failed" if new_attempts >= MAX_SEND_ATTEMPTS else "active"
            await db.execute(
                update(EmailCampaignRecipient)
                .where(EmailCampaignRecipient.id == p["recipient_id"])
                .values(send_attempts=new_attempts, status=new_status)
            )
            await db.commit()
            if new_status == "failed":
                logger.error(
                    "Recipient %s marqué 'failed' après %d échecs",
                    p["email"], new_attempts,
                )

    # 6) Marquer terminées les campagnes sans contact actif restant (ni stock,
    #    ni séquence en cours). Tant qu'il reste du stock, on garde "running".
    for campaign in campaigns:
        steps = campaign.sequence.steps
        if not steps:
            continue
        remaining = (
            await db.execute(
                select(func.count()).select_from(EmailCampaignRecipient).where(
                    EmailCampaignRecipient.campaign_id == campaign.id,
                    EmailCampaignRecipient.status == "active",
                    EmailCampaignRecipient.current_step < len(steps),
                )
            )
        ).scalar() or 0
        total = (
            await db.execute(
                select(func.count()).select_from(EmailCampaignRecipient).where(
                    EmailCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).scalar() or 0
        if total > 0 and remaining == 0 and campaign.status == "running":
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == campaign.id)
                .values(status="completed")
            )
    await db.commit()

    logger.info(
        "Campaign cron: %d envoyés (budget passage=%d, déjà %d aujourd'hui)",
        total_sent, run_budget, sent_today,
    )
    return total_sent
