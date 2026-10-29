"""Parcours HTTP de désinscription des campagnes et des envois de test."""

import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.emailing import (
    EmailCampaign,
    EmailCampaignEvent,
    EmailCampaignRecipient,
    EmailSequence,
    EmailSequenceStep,
    EmailTemplate,
    EmailUnsubscribe,
)
from app.services import emailing_service as svc
from tests.conftest import test_session_factory as session_factory


class LinksAndForms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.actions = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs.get("href"))
        if tag == "form":
            assert attrs["method"] == "post"
            self.actions.append(attrs["action"])


@pytest.fixture
async def mailing():
    async with session_factory() as session:
        template = EmailTemplate(
            name="Test",
            subject="Bonjour",
            html_body='<a href="{{desinscription}}">Se désinscrire</a>',
        )
        sequence = EmailSequence(name="Test")
        session.add_all([template, sequence])
        await session.flush()
        session.add_all(
            [
                EmailSequenceStep(
                    sequence_id=sequence.id,
                    template_id=template.id,
                    position=position,
                    delay_days=0,
                )
                for position in range(2)
            ]
        )
        campaign = EmailCampaign(
            name="Test",
            sequence_id=sequence.id,
            status="running",
        )
        session.add(campaign)
        await session.flush()
        recipient = EmailCampaignRecipient(
            campaign_id=campaign.id,
            email="test@example.com",
            scheduled_at=datetime.now(UTC),
        )
        session.add(recipient)
        await session.commit()
        return template.id, recipient.id


async def test_test_email_link_opens_simulation_without_unsubscribing(
    client,
    monkeypatch,
    mailing,
):
    monkeypatch.setattr(settings, "api_base_url", "http://test/")
    sent_html = []

    async def fake_send(email, name, subject, html, **kwargs):
        sent_html.append(html)
        return "ok"

    monkeypatch.setattr(svc, "_send_via_brevo", fake_send)
    async with session_factory() as session:
        result = await svc.EmailTemplateService(session).send_test(
            mailing[0],
            ["test@example.com", "other@example.com"],
        )
    assert all(item["sent"] for item in result)
    assert len(sent_html) == 2
    for html in sent_html:
        (link,) = LinksAndForms(html).links
        assert link == "http://test/api/v1/emailing/unsubscribe/test"
        confirm = await client.get(link)
        assert confirm.status_code == 200
        assert "aucune adresse ne sera désinscrite" in confirm.text
        (action,) = LinksAndForms(confirm.text).actions
        response = await client.post(action)
        assert response.status_code == 200
        assert "Aucune adresse n'a été désinscrite" in response.text

    async with session_factory() as session:
        recipient = await session.get(EmailCampaignRecipient, mailing[1])
        assert recipient.status == "active"
        for model in (EmailUnsubscribe, EmailCampaignEvent):
            count = await session.execute(select(func.count()).select_from(model))
            assert count.scalar() == 0


async def test_campaign_link_requires_confirmation_and_stops_future_sends(
    client,
    monkeypatch,
    mailing,
):
    monkeypatch.setattr(settings, "api_base_url", "http://test")
    sent_html = []

    async def fake_send(**kwargs):
        sent_html.append(kwargs["html_content"])
        return "ok"

    monkeypatch.setattr(svc, "_send_via_brevo", fake_send)
    async with session_factory() as session:
        assert await svc.process_campaign_emails(session) == 1

    (link,) = LinksAndForms(sent_html[0]).links
    assert "/unsubscribe?rid=" in link
    confirm = await client.get(link)
    assert confirm.status_code == 200
    assert "test@example.com" in confirm.text
    async with session_factory() as session:
        recipient = await session.get(EmailCampaignRecipient, mailing[1])
        assert recipient.status == "active"
        assert await session.get(EmailUnsubscribe, recipient.email) is None

    (action,) = LinksAndForms(confirm.text).actions
    response = await client.post(action)
    assert response.status_code == 200
    assert "Désinscription confirmée" in response.text
    async with session_factory() as session:
        recipient = await session.get(EmailCampaignRecipient, mailing[1])
        assert recipient.status == "unsubscribed"
        assert await session.get(EmailUnsubscribe, recipient.email) is not None
        assert await svc.process_campaign_emails(session) == 0
    assert len(sent_html) == 1
    again = await client.get(link)
    assert "Déjà désinscrit" in again.text


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("invalid", ["signature", "recipient_id", "missing_recipient"])
async def test_invalid_campaign_links_do_not_unsubscribe(client, mailing, method, invalid):
    rid = uuid.uuid4() if invalid == "missing_recipient" else mailing[1]
    params = {"rid": str(rid), "sig": svc.unsubscribe_signature(rid)}
    if invalid == "signature":
        params["sig"] = "invalid"
    elif invalid == "recipient_id":
        params["rid"] = "invalid"
    response = await getattr(client, method)("/api/v1/emailing/unsubscribe", params=params)
    assert response.status_code == 400
    async with session_factory() as session:
        recipient = await session.get(EmailCampaignRecipient, mailing[1])
        assert recipient.status == "active"
        assert await session.get(EmailUnsubscribe, recipient.email) is None
