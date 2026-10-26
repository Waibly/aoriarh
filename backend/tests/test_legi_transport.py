"""Bounded retries of invalid official API JSON; never repair source content."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.legi_service import LegiService
from app.services.source_diagnostics import SourceJSONError


@pytest.mark.parametrize("recover", [True, False])
async def test_invalid_legi_json_retries_original_request_with_a_fixed_limit(monkeypatch, recover):
    request = httpx.Request("POST", "https://api.piste.gouv.fr/consult/legiPart")
    invalid = httpx.Response(200, content=b'{"sections": [', request=request)
    valid = httpx.Response(200, json={"sections": [{"text": "  original  "}]}, request=request)
    client = AsyncMock()
    client.post.side_effect = [invalid, valid] if recover else [invalid] * 3
    service = LegiService()
    monkeypatch.setattr(service, "_get_access_token", AsyncMock(return_value="test-token"))
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.legi_service.asyncio.sleep", sleep)
    body = {"textId": "LEGITEXT000006072050", "date": "2026-10-27"}
    if recover:
        result = await service._api_post(client, "/consult/legiPart", body)
        assert result == {"sections": [{"text": "  original  "}]}
        assert client.post.await_count == 2
        assert sleep.await_count == 1
    else:
        with pytest.raises(SourceJSONError, match="Invalid source JSON"):
            await service._api_post(client, "/consult/legiPart", body)
        assert client.post.await_count == 3
        assert sleep.await_count == 2
    for call in client.post.await_args_list:
        assert call.kwargs["json"] == body
