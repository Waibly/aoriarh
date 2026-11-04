"""Rate limiting keyed on the visitor's real IP, shared across gunicorn workers.

Behind Caddy, `request.client.host` is the proxy's Docker IP: keying on it made
every limit global to all users (e.g. 5 logins/minute for everybody). Caddy
overwrites X-Forwarded-For with the real client IP; the Next.js server forwards
it on the auth calls it makes on the browser's behalf.
"""

import ipaddress

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings

# Server-to-server calls from our own Next.js process that carry no visitor IP
# (token refresh, Google exchange) share this key and get a dedicated budget.
INTERNAL_KEY = "internal"


def client_ip(request: Request) -> str:
    """Real visitor IP; X-Forwarded-For is trusted only from private peers."""
    peer = get_remote_address(request)
    try:
        peer_ip = ipaddress.ip_address(peer)
        trusted_proxy = peer_ip.is_loopback or peer_ip.is_private
    except ValueError:
        trusted_proxy = False
    if trusted_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            for candidate in reversed([part.strip() for part in xff.split(",")]):
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    continue
    return peer


def rate_limit_key(request: Request) -> str:
    peer = get_remote_address(request)
    ip = client_ip(request)
    if ip == peer:
        try:
            address = ipaddress.ip_address(peer)
            if address.is_private or address.is_loopback:
                return INTERNAL_KEY
        except ValueError:
            pass
    return ip


def per_visitor(limit: str, internal: str = "600/minute"):
    """Limit per real visitor; internal server calls get their own wider budget."""

    def provider(key: str) -> str:
        return internal if key == INTERNAL_KEY else limit

    return provider


limiter = Limiter(
    key_func=rate_limit_key,
    storage_uri=settings.redis_url,
    storage_options={"socket_timeout": 0.3, "socket_connect_timeout": 0.3},
    in_memory_fallback_enabled=True,
    swallow_errors=True,
)
