"""Technical source diagnostics without bodies, credentials or URL queries."""

import hashlib
import json
from urllib.parse import urlsplit


def redirect_error(url):
    parsed = urlsplit(url)
    # A redirect can contain signed queries, credentials or private path segments.
    return ValueError(
        "Unapproved source redirect: "
        f"scheme={parsed.scheme!r}, host={parsed.hostname!r}, port={parsed.port!r}"
    )


def source_json(response):
    """Parse once; retain technical evidence on failure, never repair a response."""
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        metadata = {
            "status": response.status_code,
            "bytes_received": len(response.content),
            "content_length": response.headers.get("content-length"),
            "content_type": response.headers.get("content-type"),
            "content_encoding": response.headers.get("content-encoding"),
            "transfer_encoding": response.headers.get("transfer-encoding"),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "json_error": exc.msg,
            "position": exc.pos,
        }
        raise ValueError("Invalid source JSON: " + json.dumps(metadata)) from exc
