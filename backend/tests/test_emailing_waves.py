"""Tests du découpage des campagnes en vagues d'envoi de 100 contacts."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models.emailing import (
    EmailCampaign,
    EmailCampaignEvent,
    EmailCampaignRecipient,
    EmailSequence,
    EmailSequenceStep,
    EmailSequenceStepBranch,
    EmailTemplate,
    EmailUnsubscribe,
)
from app.services.emailing_service import (
    BREVO_DAILY_LIMIT,
    MAX_SEND_ATTEMPTS,
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


async def test_preview_matches_locked_contacts():
    """L'aperçu montre exactement les contacts qui seront verrouillés."""
    async with test_session_factory() as session:
        campaign = await _make_campaign(session, 250)
        service = EmailCampaignService(session)

        preview = await service.preview_next_contacts(campaign.id, 100)
        assert len(preview) == 100

        wave = await service.schedule_wave(
            campaign.id, count=100, scheduled_at=datetime.now(UTC) + timedelta(days=1)
        )
        locked = await service.list_wave_contacts(campaign.id, wave.id)

        assert {c["email"] for c in locked} == {c["email"] for c in preview}

        # L'aperçu suivant ne remontre pas les contacts déjà verrouillés.
        preview2 = await service.preview_next_contacts(campaign.id, 100)
        assert {c["email"] for c in preview2}.isdisjoint({c["email"] for c in preview})


async def test_get_stats_with_branches_does_not_lazyload():
    """get_stats doit précharger branches + template (sinon MissingGreenlet async)."""
    async with test_session_factory() as session:
        tpl = EmailTemplate(name="T", subject="x", html_body="y")
        tpl_branch = EmailTemplate(name="T2", subject="x2", html_body="y2")
        session.add_all([tpl, tpl_branch])
        await session.flush()

        seq = EmailSequence(name="S", status="active")
        session.add(seq)
        await session.flush()

        step0 = EmailSequenceStep(sequence_id=seq.id, template_id=tpl.id, position=0)
        step1 = EmailSequenceStep(sequence_id=seq.id, template_id=tpl.id, position=1, delay_days=3)
        session.add_all([step0, step1])
        await session.flush()
        session.add(
            EmailSequenceStepBranch(
                step_id=step1.id, condition="opened_not_clicked", template_id=tpl_branch.id
            )
        )

        campaign = EmailCampaign(
            name="test", sequence_id=seq.id, brevo_list_ids=[1], status="running",
            scheduled_at=datetime.now(UTC),
        )
        session.add(campaign)
        await session.flush()
        recipient = EmailCampaignRecipient(campaign_id=campaign.id, email="a@x.fr", current_step=1)
        session.add(recipient)
        await session.flush()
        session.add(
            EmailCampaignEvent(
                campaign_id=campaign.id, recipient_id=recipient.id, step_position=0,
                event_type="sent", occurred_at=datetime.now(UTC),
            )
        )
        await session.commit()

        stats = await EmailCampaignService(session).get_stats(campaign.id)
        assert stats["total_recipients"] == 1
        assert stats["steps"][0]["sent"] == 1
        assert len(stats["steps"][1]["branches"]) == 1


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


async def _make_scheduled_campaign(session, n: int):
    """Campagne 1 étape avec n contacts actifs déjà programmés dans le passé."""
    tpl = EmailTemplate(name="T", subject="Bonjour {{prenom}}", html_body="<p>{{prenom}}</p>")
    session.add(tpl)
    await session.flush()
    seq = EmailSequence(name="S", status="active")
    session.add(seq)
    await session.flush()
    session.add(EmailSequenceStep(sequence_id=seq.id, template_id=tpl.id, position=0, delay_days=0))
    campaign = EmailCampaign(
        name="C", sequence_id=seq.id, brevo_list_ids=[1], status="running",
        scheduled_at=datetime.now(UTC),
    )
    session.add(campaign)
    await session.flush()
    past = datetime.now(UTC) - timedelta(days=1)
    for i in range(n):
        session.add(EmailCampaignRecipient(
            campaign_id=campaign.id, email=f"c{i}@x.fr", first_name=f"P{i}",
            status="active", scheduled_at=past,
        ))
    await session.commit()
    return campaign


async def test_cron_caps_at_100_per_run(monkeypatch):
    """Jamais plus de 100 personnes touchées d'un coup, même si 250 sont dues."""
    async def fake_send(**kwargs):
        return "ok"
    monkeypatch.setattr("app.services.emailing_service._send_via_brevo", fake_send)

    async with test_session_factory() as session:
        await _make_scheduled_campaign(session, 250)
    async with test_session_factory() as session:
        sent = await process_campaign_emails(session)
    assert sent == 100


async def test_cron_marks_failed_after_max_attempts(monkeypatch):
    async def fake_send(**kwargs):
        return "error"
    monkeypatch.setattr("app.services.emailing_service._send_via_brevo", fake_send)

    async with test_session_factory() as session:
        await _make_scheduled_campaign(session, 1)
    for _ in range(MAX_SEND_ATTEMPTS):
        async with test_session_factory() as session:
            await process_campaign_emails(session)

    from sqlalchemy import func, select
    async with test_session_factory() as session:
        recipient = (await session.execute(select(EmailCampaignRecipient))).scalar_one()
        sent_events = (await session.execute(
            select(func.count()).select_from(EmailCampaignEvent)
            .where(EmailCampaignEvent.event_type == "sent")
        )).scalar()
    assert recipient.send_attempts == MAX_SEND_ATTEMPTS
    assert recipient.status == "failed"
    assert sent_events == 0  # un échec ne crée jamais d'événement "envoyé"


async def test_unsubscribe_marks_all_rows_and_suppresses(monkeypatch):
    from sqlalchemy import func, select
    from app.services import emailing_service as svc

    async with test_session_factory() as session:
        c1 = await _make_scheduled_campaign(session, 0)
        c2 = await _make_scheduled_campaign(session, 0)
        r1 = EmailCampaignRecipient(campaign_id=c1.id, email="bob@x.fr", status="active", current_step=1)
        r2 = EmailCampaignRecipient(campaign_id=c2.id, email="bob@x.fr", status="active")
        r3 = EmailCampaignRecipient(campaign_id=c1.id, email="autre@x.fr", status="active")
        session.add_all([r1, r2, r3])
        await session.flush()
        rid = r1.id
        await session.commit()

    async with test_session_factory() as session:
        await svc.process_unsubscribe(session, rid)

    async with test_session_factory() as session:
        bob = [s for (s,) in (await session.execute(
            select(EmailCampaignRecipient.status).where(EmailCampaignRecipient.email == "bob@x.fr")
        )).all()]
        autre = (await session.execute(
            select(EmailCampaignRecipient.status).where(EmailCampaignRecipient.email == "autre@x.fr")
        )).scalar()
        suppressed = (await session.execute(
            select(func.count()).select_from(EmailUnsubscribe)
        )).scalar()
    assert bob == ["unsubscribed", "unsubscribed"]  # toutes les lignes du même email
    assert autre == "active"
    assert suppressed == 1


async def test_unsubscribe_signature_roundtrip():
    import uuid
    from app.services.emailing_service import (
        unsubscribe_signature, verify_unsubscribe_signature, unsubscribe_url,
    )
    rid = uuid.uuid4()
    sig = unsubscribe_signature(rid)
    assert verify_unsubscribe_signature(rid, sig)
    assert not verify_unsubscribe_signature(rid, "tampered")
    assert not verify_unsubscribe_signature(rid, None)
    assert str(rid) in unsubscribe_url(rid)


async def test_cron_stops_on_quota(monkeypatch):
    """429 Brevo → on s'arrête proprement au lieu de marteler."""
    sequence = ["ok", "ok", "quota", "ok", "ok"]

    async def fake_send(**kwargs):
        return sequence.pop(0)
    monkeypatch.setattr("app.services.emailing_service._send_via_brevo", fake_send)

    async with test_session_factory() as session:
        await _make_scheduled_campaign(session, 5)
    async with test_session_factory() as session:
        sent = await process_campaign_emails(session)
    assert sent == 2  # s'arrête à la 3e (quota)


async def test_purge_bounced_deletes_and_marks_all_rows(monkeypatch):
    """Purge : supprime de Brevo chaque email rebondi, marque toutes ses lignes
    purgées, et ne touche ni aux actifs ni aux déjà-purgés."""
    from sqlalchemy import select
    from app.services import emailing_service as svc

    deleted: list[str] = []

    async def fake_delete(email):
        deleted.append(email)
        return True

    monkeypatch.setattr(svc, "_delete_brevo_contact", fake_delete)

    async with test_session_factory() as session:
        c1 = await _make_scheduled_campaign(session, 0)
        c2 = await _make_scheduled_campaign(session, 0)
        # Même email rebondi dans 2 campagnes → 2 lignes, 1 seul appel Brevo.
        session.add_all([
            EmailCampaignRecipient(campaign_id=c1.id, email="dead@x.fr", status="bounced"),
            EmailCampaignRecipient(campaign_id=c2.id, email="dead@x.fr", status="bounced"),
            EmailCampaignRecipient(campaign_id=c1.id, email="soft@x.fr", status="bounced"),
            EmailCampaignRecipient(campaign_id=c1.id, email="ok@x.fr", status="active"),
        ])
        await session.commit()

    async with test_session_factory() as session:
        purged = await svc.purge_bounced_contacts(session)

    assert purged == 2  # 2 emails distincts (dead, soft), pas 3 lignes
    assert set(deleted) == {"dead@x.fr", "soft@x.fr"}

    async with test_session_factory() as session:
        dead_rows = (await session.execute(
            select(EmailCampaignRecipient.brevo_purged_at)
            .where(EmailCampaignRecipient.email == "dead@x.fr")
        )).scalars().all()
        ok_row = (await session.execute(
            select(EmailCampaignRecipient)
            .where(EmailCampaignRecipient.email == "ok@x.fr")
        )).scalar_one()
    assert all(d is not None for d in dead_rows)  # les 2 lignes marquées
    assert ok_row.brevo_purged_at is None and ok_row.status == "active"

    # Deuxième passage : tout est déjà purgé → aucun nouvel appel Brevo.
    deleted.clear()
    async with test_session_factory() as session:
        again = await svc.purge_bounced_contacts(session)
    assert again == 0 and deleted == []


async def test_purge_bounced_retries_on_failure(monkeypatch):
    """Un échec Brevo laisse la ligne non purgée → retentée au passage suivant."""
    from sqlalchemy import select
    from app.services import emailing_service as svc

    outcomes = [False, True]

    async def fake_delete(email):
        return outcomes.pop(0)

    monkeypatch.setattr(svc, "_delete_brevo_contact", fake_delete)

    async with test_session_factory() as session:
        c = await _make_scheduled_campaign(session, 0)
        session.add(EmailCampaignRecipient(campaign_id=c.id, email="flap@x.fr", status="bounced"))
        await session.commit()

    async with test_session_factory() as session:
        assert await svc.purge_bounced_contacts(session) == 0  # échec → pas purgé
    async with test_session_factory() as session:
        row = (await session.execute(select(EmailCampaignRecipient))).scalar_one()
        assert row.brevo_purged_at is None

    async with test_session_factory() as session:
        assert await svc.purge_bounced_contacts(session) == 1  # retry → purgé
    async with test_session_factory() as session:
        row = (await session.execute(select(EmailCampaignRecipient))).scalar_one()
        assert row.brevo_purged_at is not None


async def test_purge_bounced_dry_run_does_not_delete(monkeypatch):
    """dry_run : aucun appel Brevo, aucune ligne marquée."""
    from sqlalchemy import select
    from app.services import emailing_service as svc

    called = False

    async def fake_delete(email):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(svc, "_delete_brevo_contact", fake_delete)

    async with test_session_factory() as session:
        c = await _make_scheduled_campaign(session, 0)
        session.add(EmailCampaignRecipient(campaign_id=c.id, email="dead@x.fr", status="bounced"))
        await session.commit()

    async with test_session_factory() as session:
        assert await svc.purge_bounced_contacts(session, dry_run=True) == 0
    assert called is False

    async with test_session_factory() as session:
        row = (await session.execute(select(EmailCampaignRecipient))).scalar_one()
        assert row.brevo_purged_at is None
