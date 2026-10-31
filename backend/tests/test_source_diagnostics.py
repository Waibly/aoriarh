import httpx
import pytest

from app.services.source_diagnostics import source_json


def test_invalid_json_keeps_technical_evidence_without_response_content():
    response = httpx.Response(
        200,
        content=b'{"private":"sensitive',
        headers={"content-type": "application/json", "content-length": "20"},
    )
    with pytest.raises(ValueError) as error:
        source_json(response)
    message = str(error.value)
    assert '"bytes_received": 21' in message
    assert '"sha256":' in message and '"position":' in message
    assert "private" not in message and "sensitive" not in message
    assert error.value.__cause__ is not None


def test_valid_source_json_is_returned_unchanged():
    assert source_json(httpx.Response(200, content=b'{"text":"  original  "}')) == {
        "text": "  original  ",
    }
