from unittest.mock import AsyncMock, patch

import pytest

from app.api.public import PublicAskRequest
from app.services.demo_observability import observe_demo_stream


async def frames(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_demo_validation_is_logged_without_user_data(client):
    with patch("app.main.logger") as logger:
        response = await client.post(
            "/api/v1/public/ask",
            json={
                "message": "private question",
                "turnstile_token": "secret-token",
                "conversation_id": None,
            },
        )
    assert response.status_code == 422
    assert logger.error.call_args.args == ("demo_request_validation_failed",)
    assert logger.error.call_args.kwargs == {"error_types": ["extra_forbidden"]}
    assert "private question" not in str(logger.error.call_args)
    assert "secret-token" not in str(logger.error.call_args)


def test_public_contract_accepts_client_payload_and_forbids_conversation_reuse():
    from pydantic import ValidationError

    payload = {"message": "Question de démonstration", "turnstile_token": "token"}
    assert PublicAskRequest.model_validate(payload).message == payload["message"]
    with pytest.raises(ValidationError):
        PublicAskRequest.model_validate({**payload, "conversation_id": None})


@pytest.mark.asyncio
async def test_sse_observer_preserves_frames_and_logs_completion():
    data = 'event: chat_delta\ndata: {"content":"  texte brut  "}\n\n'
    done = "event: chat_done\ndata: {}\n\n"
    with patch("app.services.demo_observability.logger") as logger:
        result = [x async for x in observe_demo_stream(frames(data, done), AsyncMock())]
    assert result == [data, done]
    logger.info.assert_any_call("demo_stream_completed")
    logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_sse_observer_reports_error_even_with_http_200():
    error = 'event: chat_error\ndata: {"error":"timeout"}\n\n'
    with patch("app.services.demo_observability.logger") as logger:
        result = [x async for x in observe_demo_stream(frames(error), AsyncMock())]
    assert result == [error]
    logger.error.assert_called_once_with("demo_stream_failed")


@pytest.mark.asyncio
async def test_sse_observer_reports_exception_before_first_event():
    async def broken():
        raise RuntimeError("private context")
        yield ""

    with patch("app.services.demo_observability.logger") as logger:
        result = [x async for x in observe_demo_stream(broken(), AsyncMock())]
    assert len(result) == 1 and result[0].startswith("event: chat_error\n")
    assert "private context" not in result[0]
    logger.error.assert_called_once_with("demo_stream_failed", reason="unhandled_exception")


@pytest.mark.asyncio
async def test_sse_observer_reports_missing_terminal_event():
    request = AsyncMock()
    request.is_disconnected.return_value = False
    with patch("app.services.demo_observability.logger") as logger:
        result = [x async for x in observe_demo_stream(frames(), request)]
    assert result[0].startswith("event: chat_error\n")
    logger.error.assert_called_once_with("demo_stream_failed", reason="missing_completion")
