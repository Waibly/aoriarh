"""Garde-fou anti-fuite Brevo : les adresses de test ne doivent jamais
générer d'appel Brevo, même quand une vraie clé API est configurée
(incidents des 28-29/07/2026 : pytest et e2e locaux → 500+ mails réels)."""

from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.email.sender import is_test_email, sync_contact_to_brevo


class TestIsTestEmail:
    def test_test_domains(self):
        assert is_test_email("admin@test.com")
        assert is_test_email("e2e-attr-123@example.com")
        assert is_test_email("user@EXAMPLE.ORG")
        assert is_test_email("x@sub.domain.test")
        assert is_test_email("x@foo.invalid")

    def test_real_domains(self):
        assert not is_test_email("vanessa@aoriarh.fr")
        assert not is_test_email("prospect@gmail.com")
        assert not is_test_email("rh@testard-associes.fr")


async def test_sync_contact_skips_test_address_even_with_real_key():
    with (
        patch.object(settings, "brevo_api_key", "xkeysib-fake-but-set"),
        patch.object(settings, "brevo_list_id", 13),
        patch("app.services.email.sender.httpx.AsyncClient") as client_cls,
    ):
        result = await sync_contact_to_brevo(
            email="someone@test.com", full_name="Test User", auth_method="password", role="manager"
        )
    assert result is False
    client_cls.assert_not_called()


async def test_notify_admin_skips_test_address_even_with_real_key():
    from app.services.auth_service import _notify_admin_new_signup

    with (
        patch.object(settings, "brevo_api_key", "xkeysib-fake-but-set"),
        patch.object(settings, "admin_email", "hello@aoriarh.fr"),
        patch("app.services.auth_service.send_email", new=AsyncMock()) as mock_send,
    ):
        await _notify_admin_new_signup(
            full_name="Regular User",
            email="user@test.com",
            workspace_name="Test Org",
            auth_method="password",
        )
    mock_send.assert_not_called()
