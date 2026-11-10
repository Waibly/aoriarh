"""Questionnaire de fin d'essai : emails J+3 / J+23, page signée, admin, purge."""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models.account import Account
from app.models.monthly_question_usage import MonthlyQuestionUsage
from app.models.trial_feedback import TrialFeedback
from app.models.user import User
from app.services.data_retention_service import DataRetentionService
from app.services.trial_feedback_service import feedback_signature, feedback_url
from app.worker import run_billing_lifecycle
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def _expired_trial(days_since_end: float, questions: int = 0) -> uuid.UUID:
    async with session_factory() as db:
        owner = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            full_name="Claire <Test>",
        )
        db.add(owner)
        await db.flush()
        account = Account(
            id=uuid.uuid4(),
            name="Cabinet Test",
            owner_id=owner.id,
            plan="gratuit",
            status="suspended",
            plan_expires_at=datetime.now(UTC) - timedelta(days=days_since_end),
        )
        db.add(account)
        if questions:
            db.add(
                MonthlyQuestionUsage(
                    account_id=account.id,
                    period_start=date.today() - timedelta(days=20),
                    period_end=date.today(),
                    questions_used=questions,
                    quota_for_period=300,
                )
            )
        await db.commit()
        return account.id


def _params(account_id: uuid.UUID, reason: str | None = None) -> dict[str, str]:
    params = {"a": str(account_id), "sig": feedback_signature(account_id)}
    if reason:
        params["r"] = reason
    return params


@pytest.fixture
def sent(monkeypatch):
    mock = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.email.sender.send_email", mock)
    return mock


@pytest.mark.parametrize(
    ("days", "expected_subject"),
    [
        (3.5, "Une question sur votre essai AORIA RH"),
        (23.5, "Vos données AORIA RH seront supprimées le"),
        (2.5, None),
        (10.5, None),
        (24.5, None),
    ],
)
async def test_post_trial_emails_fire_once_on_their_day(sent, days, expected_subject):
    account_id = await _expired_trial(days)

    await run_billing_lifecycle({"session_factory": session_factory})

    if expected_subject is None:
        sent.assert_not_called()
        return
    sent.assert_called_once()
    _, _, subject, html = sent.call_args.args
    assert subject.startswith(expected_subject)
    assert "Claire &lt;Test&gt;" in html
    assert "/billing" in html and "/settings/billing" not in html
    if days < 10:
        for code in ("prix", "pas_le_temps", "besoin", "plus_tard", "autre"):
            assert feedback_url(account_id, code).replace("&", "&amp;") in html
        assert "Laisser un avis" in html


async def test_post_trial_emails_skip_converted_accounts(sent):
    account_id = await _expired_trial(3.5)
    async with session_factory() as db:
        account = await db.get(Account, account_id)
        account.plan = "solo"
        account.status = "active"
        await db.commit()

    await run_billing_lifecycle({"session_factory": session_factory})

    sent.assert_not_called()


async def test_feedback_page_requires_valid_signature(client):
    account_id = await _expired_trial(4)

    bad = await client.get("/api/v1/trial-feedback", params={"a": str(account_id), "sig": "0" * 32})
    assert bad.status_code == 400

    other = uuid.uuid4()
    forged = await client.post(
        "/api/v1/trial-feedback",
        data={"a": str(other), "sig": feedback_signature(account_id), "reason": "prix"},
    )
    assert forged.status_code == 400


async def test_opening_the_link_does_not_record_an_answer(client):
    account_id = await _expired_trial(4)

    res = await client.get("/api/v1/trial-feedback", params=_params(account_id, "autre"))

    assert res.status_code == 200
    assert 'value="autre" required checked' in res.text
    assert "Laquelle ?" in res.text
    async with session_factory() as db:
        assert (await db.execute(select(TrialFeedback))).first() is None


async def test_submitting_records_and_replaces_the_answer(client):
    account_id = await _expired_trial(4, questions=42)
    params = _params(account_id)

    first = await client.post(
        "/api/v1/trial-feedback", data={**params, "reason": "prix", "comment": "  "}
    )
    second = await client.post(
        "/api/v1/trial-feedback",
        data={**params, "reason": "autre", "comment": "Nous changeons d'outil"},
    )

    assert first.status_code == 200 and second.status_code == 200
    async with session_factory() as db:
        rows = list((await db.execute(select(TrialFeedback))).scalars())
    assert len(rows) == 1
    assert rows[0].reason == "autre"
    assert rows[0].comment == "Nous changeons d'outil"
    assert rows[0].questions_used == 42
    assert rows[0].trial_ended_at is not None


@pytest.mark.parametrize(
    "data",
    [{"reason": "inconnue"}, {"reason": ""}, {"reason": "prix", "comment": "x" * 2001}],
)
async def test_invalid_answers_are_rejected(client, data):
    account_id = await _expired_trial(4)

    res = await client.post("/api/v1/trial-feedback", data={**_params(account_id), **data})

    assert res.status_code == 400
    async with session_factory() as db:
        assert (await db.execute(select(TrialFeedback))).first() is None


async def test_comment_is_escaped_when_redisplayed(client):
    account_id = await _expired_trial(4)

    res = await client.post(
        "/api/v1/trial-feedback",
        data={**_params(account_id), "reason": "inconnue", "comment": "<script>x</script>"},
    )

    assert "<script>x</script>" not in res.text
    assert "&lt;script&gt;x&lt;/script&gt;" in res.text


async def _purge(monkeypatch, account_id: uuid.UUID, **kwargs) -> None:
    monkeypatch.setattr("app.rag.qdrant_store.get_qdrant_client", lambda: MagicMock())
    monkeypatch.setattr("app.services.storage_service.StorageService.__init__", lambda self: None)
    async with session_factory() as db:
        await DataRetentionService(db).purge_account(account_id, **kwargs)


async def test_purge_keeps_answer_without_identity(client, admin_user, monkeypatch):
    account_id = await _expired_trial(4, questions=7)
    await client.post(
        "/api/v1/trial-feedback",
        data={**_params(account_id), "reason": "besoin", "comment": "Pas de CCN"},
    )

    before = await client.get(
        "/api/v1/admin/business/trial-feedback", headers=auth_header(admin_user["token"])
    )
    assert before.json()["rows"][0]["account_name"] == "Cabinet Test"
    assert before.json()["rows"][0]["owner_email"].endswith("@example.test")

    await _purge(monkeypatch, account_id)

    after = await client.get(
        "/api/v1/admin/business/trial-feedback", headers=auth_header(admin_user["token"])
    )
    body = after.json()
    assert body["total"] == 1
    assert {"reason": "besoin", "label": "L'outil ne répond pas à mon besoin", "count": 1} in body[
        "by_reason"
    ]
    row = body["rows"][0]
    assert row["account_id"] is None
    assert row["account_name"] is None and row["owner_email"] is None
    assert row["comment"] == "Pas de CCN"
    assert row["questions_used"] == 7


async def test_erasure_request_deletes_the_answer(client, monkeypatch):
    account_id = await _expired_trial(4)
    await client.post("/api/v1/trial-feedback", data={**_params(account_id), "reason": "prix"})

    await _purge(monkeypatch, account_id, erase_trial_feedback=True)

    async with session_factory() as db:
        assert (await db.execute(select(TrialFeedback))).first() is None


async def test_admin_trial_feedback_is_staff_only(client, regular_user):
    res = await client.get(
        "/api/v1/admin/business/trial-feedback", headers=auth_header(regular_user["token"])
    )
    assert res.status_code == 403
