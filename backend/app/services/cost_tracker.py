"""Centralized cost tracking service for all paid API calls.

Usage:
    from app.services.cost_tracker import cost_tracker

    # After any OpenAI or Voyage AI call:
    await cost_tracker.log(
        provider="openai",
        model="gpt-5-mini",
        operation_type="generate",
        tokens_input=1200,
        tokens_output=850,
        organisation_id="...",
        user_id="...",
        context_type="question",
        context_id="...",
    )
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.api_usage import ApiUsageLog
from app.rag.usage_metrics import usage_details

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing table — updated when providers change prices.
# Key: (provider, model) → (input_per_1M_tokens, output_per_1M_tokens)
# Output is None for embedding/rerank models (billed per input token only).
# ---------------------------------------------------------------------------
PRICING: dict[tuple[str, str], tuple[float, float | None]] = {
    # OpenAI — https://platform.openai.com/docs/pricing
    ("openai", "gpt-5-mini"): (0.25, 2.00),
    ("openai", "gpt-6-luna"): (0.10, 0.50),
    ("openai", "gpt-5.2"): (1.75, 14.00),
    ("openai", "gpt-5.6-terra"): (2.00, 12.00),
    ("openai", "gpt-5"): (1.25, 10.00),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    # Voyage AI — https://docs.voyageai.com/pricing/
    ("voyageai", "voyage-law-2"): (0.12, None),
    ("voyageai", "rerank-2"): (0.05, None),
    ("voyageai", "rerank-3"): (0.05, None),
}

# USD per million tokens. Cache reads/writes are subsets of prompt_tokens,
# not additional tokens. Older models have no separate cache-write charge.
CACHED_INPUT_PRICING: dict[tuple[str, str], float] = {
    ("openai", "gpt-5-mini"): 0.025,
    ("openai", "gpt-6-luna"): 0.01,
    ("openai", "gpt-5.2"): 0.175,
    ("openai", "gpt-5.6-terra"): 0.20,
    ("openai", "gpt-5"): 0.125,
    ("openai", "gpt-4o-mini"): 0.075,
}
CACHE_WRITE_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-6-luna"): (0.125, 0.25),  # 30 minutes / 12 hours
    ("openai", "gpt-5.6-terra"): (2.50, 5.00),  # 30 minutes / 12 hours
}


def compute_cost(
    provider: str,
    model: str,
    tokens_input: int,
    tokens_output: int,
    *,
    usage: object | None = None,
) -> Decimal:
    """Standard-tier USD estimate, including provider-reported cache usage.

    Without cache details, all input is priced at the ordinary input rate.
    Cache writes without a TTL breakdown use the default 30-minute TTL.
    Completion tokens already include reasoning tokens; do not add them again.
    """
    key = (provider, model)
    prices = PRICING.get(key)
    if prices is None:
        logger.warning("No pricing found for %s/%s — cost set to 0", provider, model)
        return Decimal(0)

    input_price, output_price = prices
    # These models switch rate cards above 272K input tokens.
    long_context = (
        key
        in {
            ("openai", "gpt-5.6-terra"),
            ("openai", "gpt-6-luna"),
        }
        and tokens_input > 272_000
    )
    if long_context:
        input_price *= 2
        output_price *= 1.5
    details = usage_details(usage)
    cached = details.get("tokens_cached", 0)
    writes_12h = details.get("tokens_cache_write_12h", 0)
    writes = details.get(
        "tokens_cache_write",
        details.get("tokens_cache_write_30m", 0) + writes_12h,
    )
    writes_30m = writes - writes_12h
    if (
        cached + writes > tokens_input
        or writes_30m < 0
        or details.get("tokens_cache_write_30m", writes_30m) != writes_30m
    ):
        raise ValueError("Inconsistent provider cache token counts")

    cost = Decimal(tokens_input - cached - writes) * Decimal(str(input_price))
    if cached:
        cached_price = CACHED_INPUT_PRICING[key] * (2 if long_context else 1)
        cost += Decimal(cached) * Decimal(str(cached_price))
    if writes:
        price_30m, price_12h = CACHE_WRITE_PRICING[key]
        if long_context:
            price_30m *= 2
            price_12h *= 2
        cost += Decimal(writes_30m) * Decimal(str(price_30m))
        cost += Decimal(writes_12h) * Decimal(str(price_12h))
    if output_price is not None and tokens_output > 0:
        cost += Decimal(tokens_output) * Decimal(str(output_price))
    return cost / Decimal("1000000")


@dataclass(frozen=True)
class CostContext:
    """Contexte d'attribution d'un appel payant (org, user, question).

    Passé EXPLICITEMENT aux composants partagés (HybridSearch, VoyageReranker)
    à chaque appel. Ne jamais stocker ce contexte sur un singleton : deux
    questions simultanées de deux organisations s'écraseraient mutuellement et
    les coûts seraient facturés à la mauvaise org (race observée à l'audit du
    27/07/2026).
    """

    organisation_id: str | None = None
    user_id: str | None = None
    context_id: str | None = None
    is_replay: bool = False


class CostTracker:
    """Fire-and-forget cost logger. Writes to DB in a dedicated session."""

    def __init__(self) -> None:
        # Références fortes sur les tâches de fond : sans elles, une tâche
        # peut être ramassée par le GC avant d'avoir écrit son log.
        self._bg_tasks: set[asyncio.Task] = set()

    def log_bg(self, **kwargs) -> None:
        """Écrit le coût en tâche de fond, HORS du chemin critique.

        `log()` ouvre une session BDD + 2 SELECT (email, nom d'org) + INSERT :
        awaité inline ~8-10 fois par question, cela s'additionnait dans la
        latence perçue. Ici on programme l'écriture et on rend la main tout de
        suite. `log()` avale déjà ses propres erreurs.
        """
        try:
            task = asyncio.get_running_loop().create_task(self.log(**kwargs))
        except RuntimeError:
            # Pas d'event loop (contexte synchrone) : on ne peut pas écrire —
            # même philosophie que log() : le tracking ne casse jamais l'appel.
            logger.warning("[COST] log_bg appelé hors event loop — coût non tracé")
            return
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def flush(self) -> None:
        """Attend les écritures de fond en cours (tests, arrêt propre)."""
        if self._bg_tasks:
            await asyncio.gather(*tuple(self._bg_tasks), return_exceptions=True)

    async def log(
        self,
        *,
        provider: str,
        model: str,
        operation_type: str,
        tokens_input: int,
        tokens_output: int = 0,
        usage: object | None = None,
        organisation_id: str | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
        organisation_name: str | None = None,
        context_type: str = "question",
        context_id: str | None = None,
        is_replay: bool = False,
    ) -> None:
        # For replay/sandbox calls, drop org_id and user_id : they may
        # reference fake/synthetic ids (eg the corpus retrieval test) that
        # would violate FK constraints. Replays are not billed to clients.
        if is_replay:
            organisation_id = None
            user_id = None
        """Log a single API call. Non-blocking — errors are swallowed."""
        try:
            cost = compute_cost(provider, model, tokens_input, tokens_output, usage=usage)

            # Resolve snapshots if not provided
            resolved_email = user_email
            resolved_org_name = organisation_name
            async with async_session_factory() as session:
                if not resolved_email and user_id:
                    from app.models.user import User

                    result = await session.execute(
                        select(User.email).where(User.id == uuid.UUID(user_id))
                    )
                    resolved_email = result.scalar_one_or_none()
                if not resolved_org_name and organisation_id:
                    from app.models.organisation import Organisation

                    result = await session.execute(
                        select(Organisation.name).where(
                            Organisation.id == uuid.UUID(organisation_id)
                        )
                    )
                    resolved_org_name = result.scalar_one_or_none()

                log_entry = ApiUsageLog(
                    provider=provider,
                    model=model,
                    operation_type=operation_type,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    cost_usd=cost,
                    organisation_id=uuid.UUID(organisation_id) if organisation_id else None,
                    user_id=uuid.UUID(user_id) if user_id else None,
                    user_email_snapshot=resolved_email,
                    organisation_name_snapshot=resolved_org_name,
                    context_type=context_type,
                    context_id=uuid.UUID(context_id) if context_id else None,
                    is_replay=is_replay,
                )
                session.add(log_entry)
                await session.commit()

            logger.debug(
                "[COST] %s/%s %s — %d in + %d out = $%.6f | org=%s user=%s",
                provider,
                model,
                operation_type,
                tokens_input,
                tokens_output,
                cost,
                organisation_id,
                user_id,
            )
        except Exception:
            logger.exception("[COST] Failed to log usage — continuing without tracking")


# Module-level singleton
cost_tracker = CostTracker()
