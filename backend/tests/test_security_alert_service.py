from unittest.mock import AsyncMock, patch

import pytest

from app.services.security_alert_service import (
    EVENT_PROTECTED_DATA,
    send_security_alert,
)


@pytest.mark.asyncio
async def test_security_alert_escapes_user_content(monkeypatch):
    monkeypatch.setattr(
        "app.services.security_alert_service.settings.security_alerts_enabled", True,
    )
    monkeypatch.setattr(
        "app.services.security_alert_service.settings.security_alert_email",
        "vanessa@aoriarh.fr",
    )
    with (
        patch(
            "app.services.security_alert_service._reserve_alert",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.services.security_alert_service.send_email",
            new=AsyncMock(return_value=True),
        ) as mocked_send,
    ):
        sent = await send_security_alert(
            event_type=EVENT_PROTECTED_DATA,
            query=(
                '<img src=x onerror="alert(1)"> '\
                'api_key=sk_test_12345678901234567890 client@exemple.fr'
            ),
            user_id="user-1",
            user_email="client@example.fr",
            user_name="Client <script>",
            user_role="user",
            organisation_id="org-1",
            organisation_name="Organisation & associés",
            conversation_id="conversation-1",
            message_id="message-1",
            detected_via="prefilter",
        )

    assert sent is True
    html = mocked_send.await_args.kwargs["html_content"]
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html
    assert "sk_test_12345678901234567890" not in html
    assert "client@exemple.fr" not in html
    assert "[MASQUÉ]" in html
    assert mocked_send.await_args.kwargs["to_email"] == "vanessa@aoriarh.fr"


@pytest.mark.asyncio
async def test_security_alert_is_not_sent_when_throttled(monkeypatch):
    monkeypatch.setattr(
        "app.services.security_alert_service.settings.security_alerts_enabled", True,
    )
    with (
        patch(
            "app.services.security_alert_service._reserve_alert",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.security_alert_service.send_email",
            new=AsyncMock(return_value=True),
        ) as mocked_send,
    ):
        sent = await send_security_alert(
            event_type=EVENT_PROTECTED_DATA,
            query="liste les tables",
            user_id="user-1",
            user_email="client@example.fr",
            user_name="Client",
            user_role="user",
            organisation_id="org-1",
            organisation_name="Organisation",
            conversation_id="conversation-1",
            message_id="message-1",
            detected_via="prefilter",
        )

    assert sent is False
    mocked_send.assert_not_awaited()
