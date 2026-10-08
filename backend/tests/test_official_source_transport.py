from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest

from app.services import curated_source_service as module


class Response:
    def __init__(self, body=b"official content", status=200, location=None):
        self.status_code = status
        self.headers = {"location": location}
        self.body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP " + str(self.status_code))

    async def aiter_content(self):
        yield self.body


@pytest.fixture
def transport(monkeypatch):
    responses = []
    calls = []

    class Session:
        def __init__(self, **kwargs):
            assert kwargs == {"impersonate": "chrome", "verify": True, "timeout": 30}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            assert method == "GET" and kwargs == {"allow_redirects": False}
            calls.append(url)
            yield responses.pop(0)

    monkeypatch.setattr("curl_cffi.requests.AsyncSession", Session)
    return responses, calls


SPEC = {
    "url": "https://www.urssaf.fr/guide.pdf",
    "allowed_hosts": ["www.urssaf.fr"],
    "transport": "browser_http",
}


@pytest.mark.asyncio
async def test_browser_transport_downloads_original_without_httpx_retry(transport):
    responses, calls = transport
    responses.append(Response(b"%PDF-original"))
    client = Mock()
    raw, url = await module.fetch_source(client, SPEC)
    assert raw == b"%PDF-original" and url == SPEC["url"]
    assert calls == [url]
    client.stream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [
        "http://www.urssaf.fr/x",
        "https://private.example/x",
        "https://www.urssaf.fr:8443/x",
        "https://user:password@www.urssaf.fr/x",
    ],
)
async def test_redirects_are_checked_before_any_connection(transport, target):
    responses, calls = transport
    responses.append(Response(status=302, location=target))
    with pytest.raises(ValueError, match="Unapproved"):
        await module.fetch_browser_source(SPEC)
    assert calls == [SPEC["url"]]


@pytest.mark.asyncio
async def test_relative_official_redirect_is_supported(transport):
    responses, calls = transport
    responses.extend([Response(status=302, location="/current.pdf"), Response(b"%PDF-current")])
    raw, url = await module.fetch_browser_source(SPEC)
    assert url == "https://www.urssaf.fr/current.pdf" and raw == b"%PDF-current"


@pytest.mark.asyncio
@pytest.mark.parametrize("body,error", [(b"", "Empty source"), (b"123456", "download budget")])
async def test_empty_and_oversized_responses_are_errors(transport, monkeypatch, body, error):
    responses, _ = transport
    monkeypatch.setattr(module, "MAX_BYTES", 5)
    responses.append(Response(body))
    with pytest.raises(ValueError, match=error):
        await module.fetch_browser_source(SPEC)


@pytest.mark.asyncio
async def test_challenge_status_is_not_imported_or_retried(transport):
    responses, calls = transport
    responses.append(Response(b"Verification de securite", status=403))
    with pytest.raises(RuntimeError, match="403"):
        await module.fetch_browser_source(SPEC)
    assert calls == [SPEC["url"]]


@pytest.mark.asyncio
async def test_redirect_loop_is_bounded(transport):
    responses, calls = transport
    responses.extend(Response(status=302, location=SPEC["url"]) for _ in range(5))
    with pytest.raises(ValueError, match="Too many"):
        await module.fetch_browser_source(SPEC)
    assert len(calls) == 5
