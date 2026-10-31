from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.plan_service import PlanOverflowError
from app.services.stripe_service import StripeService


async def test_downgrade_notification_retains_reasons_after_exception_handler(monkeypatch):
    owner = SimpleNamespace(is_active=True, email="owner@example.test", full_name="Owner")
    account = SimpleNamespace(id="account-id", owner_id="owner-id")
    database = SimpleNamespace(get=AsyncMock(return_value=owner))
    validate = AsyncMock(side_effect=PlanOverflowError(["3 utilisateurs pour 1 place"]))
    send = AsyncMock()
    monkeypatch.setattr("app.services.plan_service._validate_plan_fits_existing_data", validate)
    monkeypatch.setattr("app.services.email.sender.send_email", send)

    await StripeService(database)._notify_downgrade_overflow(account, "equipe", "solo")

    validate.assert_awaited_once_with(database, account.id, "solo")
    send.assert_awaited_once()
    recipient, name, subject, body = send.await_args.args
    assert (recipient, name) == (owner.email, owner.full_name)
    assert subject == "Downgrade AORIA RH — action requise"
    assert "<li>3 utilisateurs pour 1 place</li>" in body
