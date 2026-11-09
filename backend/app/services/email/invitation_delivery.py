"""Invitation writes must not report success when delivery was rejected."""

from collections.abc import Awaitable

from fastapi import HTTPException


async def require_invitation_delivery(delivery: Awaitable[bool]) -> None:
    try:
        sent = await delivery
    except Exception:
        raise HTTPException(
            502, "L'email d'invitation n'a pas pu être envoyé. Réessayez."
        ) from None
    if not sent:
        raise HTTPException(502, "L'email d'invitation n'a pas pu être envoyé. Réessayez.")
