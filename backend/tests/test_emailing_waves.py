"""Tests du découpage des campagnes en vagues d'envoi de 100 contacts."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models.emailing import (
    EmailCampaign,
    EmailCampaignRecipient,
    EmailSequence,
    EmailSequenceStep,
    EmailTemplate,
)
from app.services.emailing_service import (
    BREVO_DAILY_LIMIT,
    WAVE_MAX_SIZE,
    EmailCampaignService,
    process_campaign_emails,
)

from tests.conftest import test_session_factory


async def _make_campaign(session, n_recipients: int, *, delay_days: int = 0) -> EmailCampaign:
    template = EmailTemplate(
        name="Tpl", subject="Bonjour {{prenom}}", html_body="<p>Hello {{prenom}}</p>"
    )
    session.add(template)
    await session.flush()

    sequence = EmailSequence(name="Seq", status="active")
    session.add(sequence)
    await session.flush()

    step = EmailSequenceStep(
        sequence_id=sequence.id, template_id=template.id, position=0, delay_days=delay_days
    )
    session.add(step)

    campaign = EmailCampaign(
        name="Campagne test",
        sequence_id=sequence.id,
        brevo_list_ids=[1],
        status="running",
        scheduled_at=datetime.now(UTC),
    )
    session.add(campaign)
    await session.flush()

    for i in range(n_recipients):
        session.add(
            EmailCampaignRecipient(
                campaign_id=campaign.id,
                email=f"contact{i}@example.com",
                first_name=f"Prenom{i}",
            )
        )
    await session.commit()
    return campaign


async def test_schedule_wave_locks_exactly_n_contacts():
    async with test_session_factory() as session:
        campaign = await _make_campaign(session, 250)
        service = EmailCampaignService(session)

        when = datetime.now(UTC) + timedelta(days=1)
        wave = await service.schedule_wave(campaign.id, count=100, scheduled_at=when)

        assert wave.recipient_count == 100
        overview = await service.get_waves(campaign.id)
        assert overview["pending_count"] == 150  # 250 - 100 en stock


async def test_wave_count_capped_at_max():
    async with test_session_factory() as session:
        campaign = await _make_campaign(session, 250)
        service = EmailCampaignService(session)
        when = datetime.now(UTC) + timedelta(days=1)
        # On demande plus que le maximum autorisé.
        wave = await service.schedule_wave(campaign.id, count=500, scheduled_at=when)
        assert wave.recipient_count == WAVE_MAX_SIZE


async def test_waves_never_overlap():
    """Un contact ne peut jamais tomber dans deux vagues."""
    async with test_session_factory() as session:
        campaign = await _make_campaign(session, 250)
        service = EmailCampaignService(session)
        d1 = datetime.now(UTC) + timedelta(days=1)
        d2 = datetime.now(UTC) + timedelta(days=2)

        w1 = await service.schedule_wave(campaign.id, count=100, scheduled_at=d1)
        w2 = await service.schedule_wave(campaign.id, count=100, scheduled_at=d2)

        from sqlalchemy import select

        ids1 = {
            r for (r,) in (
                await session.execute(
                    select(EmailCampaignRecipient.id).where(
                        EmailCampaignRecipient.wave_id == w1.id
                    )
                )
            ).all()
        }
        ids2 = {
            r for (r,) in (
                await session.execute(
                    select(EmailCampaignRecipient.id).where(
                        EmailCampaignRecipient.wave_id == w2.id
                    )
                )
            ).all()
        }
        assert len(ids1) == 100
        assert len(ids2) == 100
        assert ids1.isdisjoint(ids2)  # aucun chevauchement


async def test_last_wave_takes_remaining_stock():
    async with test_session_factory() as session:
        campaign = await _make_campaign(session, 150)
        service = EmailCampaignService(session)
        await service.schedule_wave(
            campaign.id, count=100, scheduled_at=datetime.now(UTC) + timedelta(days=1)
        )
        # Il ne reste que 50 contacts : la vague suivante en prend 50.
        w2 = await service.schedule_wave(
            campaign.id, count=100, scheduled_at=datetime.now(UTC) + timedelta(days=2)
        )
        assert w2.recipient_count == 50

        # Plus rien en stock : programmer encore lève une erreur.
        with pytest.raises(HTTPException):
            await service.schedule_wave(
                campaign.id, count=100, scheduled_at=datetime.now(UTC) + timedelta(days=3)
            )


async def test_daily_limit_guard():
    async with test_session_factory() as session:
        campaign = await _make_campaign(session, 500)
        service = EmailCampaignService(session)
        day = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)

        # 3 vagues de 100 le même jour = 300, OK (= limite Brevo).
        await service.schedule_wave(campaign.id, count=100, scheduled_at=day)
        await service.schedule_wave(campaign.id, count=100, scheduled_at=day + timedelta(hours=1))
        await service.schedule_wave(campaign.id, count=100, scheduled_at=day + timedelta(hours=2))

        # La 4e dépasse 300 sur la journée → refus.
        with pytest.raises(HTTPException) as exc:
            await service.schedule_wave(
                campaign.id, count=100, scheduled_at=day + timedelta(hours=3)
            )
        assert str(BREVO_DAILY_LIMIT) in exc.value.detail


async def test_cron_respects_wave_schedule(monkeypatch):
    """Le cron n'envoie que les vagues échues ; le stock et le futur attendent."""
    sent_to: list[str] = []

    async def fake_send(to_email, to_name, subject, html_content, preview_text=None):
        sent_to.append(to_email)
        return True

    monkeypatch.setattr(
        "app.services.emailing_service._send_via_brevo", fake_send
    )

    async with test_session_factory() as session:
        campaign = await _make_campaign(session, 250)
        service = EmailCampaignService(session)

        # Vague 1 : échéance passée → doit partir.
        await service.schedule_wave(
            campaign.id, count=100, scheduled_at=datetime.now(UTC) - timedelta(hours=1)
        )
        # Vague 2 : échéance future → ne doit pas partir.
        await service.schedule_wave(
            campaign.id, count=100, scheduled_at=datetime.now(UTC) + timedelta(days=1)
        )
        # 50 contacts restent en stock (jamais envoyés).

    async with test_session_factory() as session:
        total = await process_campaign_emails(session)

    assert total == 100  # uniquement la vague échue
    assert len(sent_to) == 100
