"""Automated quality review: checks, anchoring, setting, scope, budget, idempotence, API."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models.audit_log import AuditLog
from app.models.conversation import Conversation, Message
from app.models.organisation import Organisation
from app.models.quality_review import QualityFinding, QualityReview
from app.models.user import User
from app.services import platform_settings
from app.services.platform_settings import QualityReviewSettings
from app.services.quality_review.deterministic import (
    arithmetic_findings,
    citation_findings,
    labour_code_citations,
)
from app.services.quality_review.llm_reviewer import LlmReviewer, quote_found
from app.services.quality_review.service import run_quality_review
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory

SOURCE_TEXT = (
    "Article D3313-13\n\nLorsqu'un bénéficiaire demande le versement de l'intéressement "
    "conformément aux dispositions de l'article R. 3313-12, ou lorsque l'intéressement est "
    "affecté à un plan d'épargne salariale, l'entreprise effectue ce versement avant le "
    "premier jour du sixième mois suivant la clôture de l'exercice de calcul au titre duquel "
    "l'intéressement est dû."
)
WRONG_ANSWER = (
    "Les montants sont validés en interne.\n\n"
    "Pour l’exercice clos le **30 juin 2026**, les sommes doivent être versées ou affectées "
    "au plan **avant le 1er janvier 2027** (**art. D.3313-13**)."
)


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    platform_settings.clear_cache()
    yield
    platform_settings.clear_cache()


def _completion(payload: dict):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=None,
    )


class FakeClient:
    """Answers the review call first, then each counter-check in order."""

    def __init__(self, review: dict, verdicts: list[str] | None = None, fail: bool = False):
        self.review = review
        self.verdicts = list(verdicts or [])
        self.fail = fail
        self.calls: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        name = kwargs["response_format"]["json_schema"]["name"]
        self.calls.append(name)
        if self.fail:
            raise RuntimeError("model down")
        if name == "quality_review":
            return _completion(self.review)
        return _completion({"verdict": self.verdicts.pop(0), "reason": "vérifié"})


def _finding(**overrides) -> dict:
    finding = {
        "kind": "date",
        "answer_quote": "les sommes doivent être versées ou affectées au plan avant le 1er "
        "janvier 2027",
        "source_index": 1,
        "source_quote": "avant le premier jour du sixième mois suivant la clôture",
        "explanation": "Clôture 30 juin : juillet 1er mois, décembre 6e. Donc avant le 1er "
        "décembre 2026.",
        "correction": "au plus tard le 30 novembre 2026",
    }
    finding.update(overrides)
    return finding


async def _all_present(refs):
    return set(refs)


async def _answer(email: str, content: str = WRONG_ANSWER, role: str | None = None):
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        if role:
            user.role = role
        org = Organisation(name="TEAM Test", account_id=user.owned_account.id)
        db.add(org)
        await db.flush()
        conversation = Conversation(organisation_id=org.id, user_id=user.id, title="Q")
        db.add(conversation)
        await db.flush()
        now = datetime.now(UTC)
        db.add(
            Message(
                conversation_id=conversation.id,
                role="user",
                content="Quand verser l'intéressement de l'exercice juillet 2025-juin 2026 ?",
                created_at=now - timedelta(seconds=30),
            )
        )
        answer = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=content,
            sources=[
                {
                    "document_name": "Code du travail — Partie réglementaire",
                    "article_nums": ["D3313-13"],
                    "full_text": SOURCE_TEXT,
                }
            ],
            created_at=now,
        )
        db.add(answer)
        await db.commit()
        return answer.id


SHADOW = QualityReviewSettings(mode="shadow")


# --- Checks by program -------------------------------------------------------


def test_labour_code_citations_ignore_other_codes():
    cited = labour_code_citations(
        "Délai de **15 jours** (**art. R.3313-12** et **L.3315-2**). "
        "La règle de l’**art. L.242-1** du Code de la sécurité sociale. "
        "Voir D.3313-13 du Code du travail."
    )
    assert set(cited) == {"R3313-12", "L3315-2", "D3313-13"}
    assert cited["R3313-12"].startswith("Délai de")


async def test_citation_findings_flag_only_missing_articles():
    async def lookup(refs):
        return {"L3342-1"}

    findings = await citation_findings("Voir **art. L.3342-1** et **art. L.9999-99**.", lookup)
    assert [f.kind for f in findings] == ["citation_introuvable"]
    assert "L9999-99" in findings[0].explanation


def test_arithmetic_already_corrected_live_is_not_reported_twice():
    answer = "2 500 € × 3 = 7 000 €"
    assert len(arithmetic_findings(answer)) == 1
    notice = "\n\n---\n**Vérification automatique des calculs** : une opération est inexacte."
    assert arithmetic_findings(answer + notice) == []


def test_quote_found_tolerates_markdown_typography_and_ellipsis():
    assert quote_found(
        "les sommes doivent être versées ou affectées au plan avant le 1er janvier 2027",
        WRONG_ANSWER,
    )
    assert quote_found("l'exercice clos le 30 juin 2026 … avant le 1er janvier 2027", WRONG_ANSWER)
    assert not quote_found("avant le 1er février 2027", WRONG_ANSWER)
    assert not quote_found("", WRONG_ANSWER)


# --- Review service ------------------------------------------------------------


async def test_off_reviews_nothing(regular_user):
    message_id = await _answer(regular_user["email"])
    client = FakeClient({"findings": [_finding()]}, ["confirmed"])
    async with session_factory() as db:
        review = await run_quality_review(
            db,
            message_id,
            config=QualityReviewSettings(),
            reviewer=LlmReviewer(client, "gpt-5.2"),
            article_lookup=_all_present,
        )
        assert review is None
        assert (await db.execute(select(func.count(QualityReview.id)))).scalar_one() == 0
    assert client.calls == []


async def test_confirmed_error_flags_the_answer(regular_user):
    message_id = await _answer(regular_user["email"])
    client = FakeClient(
        {
            "findings": [
                _finding(),
                _finding(answer_quote="une phrase que la réponse ne contient pas"),
                _finding(kind="montant", answer_quote="Les montants sont validés en interne"),
            ]
        },
        ["confirmed", "refuted"],
    )
    async with session_factory() as db:
        review = await run_quality_review(
            db,
            message_id,
            config=SHADOW,
            reviewer=LlmReviewer(client, "gpt-5.2"),
            article_lookup=_all_present,
        )
        assert review.status == "flagged"
        assert review.mode == "shadow"
        findings = (
            (await db.execute(select(QualityFinding).order_by(QualityFinding.created_at)))
            .scalars()
            .all()
        )
    validations = sorted(f.validation for f in findings)
    assert validations == ["confirmed", "refuted", "unanchored"]
    confirmed = next(f for f in findings if f.validation == "confirmed")
    assert confirmed.kind == "date"
    assert confirmed.source_label.startswith("Code du travail")
    # One review call, one counter-check per anchored finding, none for the invented quote.
    assert client.calls.count("quality_review") == 1
    assert client.calls.count("quality_counter_check") == 2


async def test_refuted_only_leaves_the_answer_clean(regular_user):
    message_id = await _answer(regular_user["email"])
    client = FakeClient({"findings": [_finding()]}, ["refuted"])
    async with session_factory() as db:
        review = await run_quality_review(
            db,
            message_id,
            config=SHADOW,
            reviewer=LlmReviewer(client, "gpt-5.2"),
            article_lookup=_all_present,
        )
    assert review.status == "clean"


async def test_review_is_idempotent(regular_user):
    message_id = await _answer(regular_user["email"])
    client = FakeClient({"findings": []})
    async with session_factory() as db:
        first = await run_quality_review(
            db,
            message_id,
            config=SHADOW,
            reviewer=LlmReviewer(client, "gpt-5.2"),
            article_lookup=_all_present,
        )
        second = await run_quality_review(
            db,
            message_id,
            config=SHADOW,
            reviewer=LlmReviewer(client, "gpt-5.2"),
            article_lookup=_all_present,
        )
    assert first.id == second.id
    assert client.calls == ["quality_review"]


async def test_staff_answers_are_out_of_customer_scope(admin_user):
    message_id = await _answer(admin_user["email"])
    client = FakeClient({"findings": []})
    async with session_factory() as db:
        review = await run_quality_review(
            db,
            message_id,
            config=SHADOW,
            reviewer=LlmReviewer(client, "gpt-5.2"),
            article_lookup=_all_present,
        )
    assert review is None
    assert client.calls == []


async def test_monthly_budget_stops_paid_review(regular_user):
    first_id = await _answer(regular_user["email"])
    second_id = await _answer(regular_user["email"])
    async with session_factory() as db:
        db.add(
            QualityReview(
                message_id=first_id,
                reviewer_version="old",
                mode="shadow",
                status="clean",
                checks=[],
                cost_usd=Decimal("5"),
            )
        )
        await db.commit()
        client = FakeClient({"findings": []})
        review = await run_quality_review(
            db,
            second_id,
            config=QualityReviewSettings(mode="shadow", monthly_budget_usd=5),
            reviewer=LlmReviewer(client, "gpt-5.2"),
            article_lookup=_all_present,
        )
    assert review.status == "skipped"
    assert review.skip_reason == "monthly_budget_reached"
    assert client.calls == []


async def test_model_failure_is_recorded_not_raised(regular_user):
    message_id = await _answer(regular_user["email"])
    async with session_factory() as db:
        review = await run_quality_review(
            db,
            message_id,
            config=SHADOW,
            reviewer=LlmReviewer(FakeClient({}, fail=True), "gpt-5.2"),
            article_lookup=_all_present,
        )
    assert review.status == "failed"
    assert "model down" in review.error


async def test_missing_labour_code_article_is_a_confirmed_finding(regular_user):
    message_id = await _answer(regular_user["email"])

    async def nothing(refs):
        return set()

    config = QualityReviewSettings(
        mode="shadow", checks={"arithmetic": True, "citations": True, "llm": False}
    )
    async with session_factory() as db:
        review = await run_quality_review(db, message_id, config=config, article_lookup=nothing)
        finding = (await db.execute(select(QualityFinding))).scalar_one()
    assert review.status == "flagged"
    assert finding.kind == "citation_introuvable"
    assert finding.validation == "confirmed"


# --- Scheduling from the chat ---------------------------------------------------


async def test_nothing_is_queued_when_off(monkeypatch):
    from app.services.quality_review import tasks

    pool = AsyncMock()
    monkeypatch.setattr("app.core.database.async_session_factory", session_factory)
    monkeypatch.setattr("app.rag.tasks.get_arq_pool", AsyncMock(return_value=pool))
    await tasks._enqueue("00000000-0000-0000-0000-000000000001")
    pool.enqueue_job.assert_not_called()

    async with session_factory() as db:
        await platform_settings.save_quality_review_settings(db, SHADOW, user_id=None)
    await tasks._enqueue("00000000-0000-0000-0000-000000000001")
    pool.enqueue_job.assert_awaited_once()
    assert pool.enqueue_job.await_args.kwargs["_job_id"].startswith("quality_review:")


async def test_force_off_overrides_the_admin_setting(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.quality_review_force_off", True)
    async with session_factory() as db:
        await platform_settings.save_quality_review_settings(db, SHADOW, user_id=None)
        assert (await platform_settings.get_quality_review_settings(db)).mode == "off"


# --- Admin API ------------------------------------------------------------------


async def test_admin_switches_the_review_and_it_is_audited(client, admin_user, regular_user):
    headers = auth_header(admin_user["token"])
    initial = await client.get("/api/v1/admin/quality/review/settings", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["settings"]["mode"] == "off"

    payload = {**initial.json()["settings"], "mode": "shadow", "monthly_budget_usd": 12}
    updated = await client.put(
        "/api/v1/admin/quality/review/settings", json=payload, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["settings"]["mode"] == "shadow"

    async with session_factory() as db:
        assert (await platform_settings.get_quality_review_settings(db, use_cache=False)).mode == (
            "shadow"
        )
        audit = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "quality_review_settings_updated")
            )
        ).scalar_one()
        assert '"mode": "shadow"' in audit.details

    invalid = await client.put(
        "/api/v1/admin/quality/review/settings", json={"mode": "everything"}, headers=headers
    )
    assert invalid.status_code == 422

    forbidden = await client.get(
        "/api/v1/admin/quality/review/settings", headers=auth_header(regular_user["token"])
    )
    assert forbidden.status_code == 403


async def test_admin_lists_confirmed_findings(client, admin_user, regular_user):
    message_id = await _answer(regular_user["email"])
    async with session_factory() as db:
        await run_quality_review(
            db,
            message_id,
            config=SHADOW,
            reviewer=LlmReviewer(FakeClient({"findings": [_finding()]}, ["confirmed"]), "gpt-5.2"),
            article_lookup=_all_present,
        )
    response = await client.get(
        "/api/v1/admin/quality/review/findings", headers=auth_header(admin_user["token"])
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["kind"] == "date"
    assert items[0]["organisation_name"] == "TEAM Test"
