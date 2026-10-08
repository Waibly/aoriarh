import httpx
from openai import RateLimitError

from app.services.chat_errors import stream_error_payload


def provider_error(code, kind):
    return RateLimitError(
        "private provider details",
        response=httpx.Response(429, request=httpx.Request("POST", "https://provider.invalid")),
        body={"code": code, "type": kind},
    )


def test_exhausted_credit_error_does_not_suggest_retry_or_disclose_raw_error():
    result = stream_error_payload(provider_error("credit_balance_exhausted", "insufficient_quota"))
    assert result["error"] == "provider_quota_exhausted"
    assert "crédits" in result["message"]
    assert "private provider details" not in result["message"]


def test_temporary_rate_limit_has_a_distinct_error():
    assert (
        stream_error_payload(provider_error("rate_limit_exceeded", "requests"))["error"]
        == "provider_rate_limited"
    )


def test_unknown_errors_do_not_expose_exception_details():
    result = stream_error_payload(RuntimeError("secret connection string"))
    assert result["error"] == "server_error"
    assert "secret" not in result["message"]
