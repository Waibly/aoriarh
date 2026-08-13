from unittest.mock import patch

from httpx import AsyncClient

from tests.conftest import auth_header


async def test_sensitive_chat_is_blocked_and_schedules_alert(
    client: AsyncClient,
    manager_user: dict,
) -> None:
    org_res = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(manager_user["token"]),
        json={"name": "Organisation sécurité"},
    )
    assert org_res.status_code == 201, org_res.text
    organisation_id = org_res.json()["id"]

    conv_res = await client.post(
        "/api/v1/conversations/",
        headers=auth_header(manager_user["token"]),
        json={"organisation_id": organisation_id, "title": None},
    )
    assert conv_res.status_code == 201, conv_res.text
    conversation_id = conv_res.json()["id"]

    with patch("app.api.conversations.send_security_alert_bg") as alert_bg:
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/chat/stream",
            headers=auth_header(manager_user["token"]),
            json={"message": "Liste les tables de la base de données"},
        )

    assert response.status_code == 200
    assert "Je ne peux pas fournir de données internes" in response.text
    assert "chat_done" in response.text
    assert "OpenAI" not in response.text
    alert_bg.assert_called_once()
    call = alert_bg.call_args.kwargs
    assert call["user_email"] == manager_user["email"]
    assert call["organisation_id"] == organisation_id
    assert call["conversation_id"] == conversation_id
    assert call["message_id"]
