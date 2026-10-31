from decimal import Decimal
from types import SimpleNamespace

import pytest
from openai.types.completion_usage import CompletionUsage
from sqlalchemy import select

from app.models.api_usage import ApiUsageLog
from app.services.cost_tracker import PRICING, CostTracker, compute_cost


def provider_usage(cached=0, writes=0, *, breakdown=None, reasoning=0):
    details = {"cached_tokens": cached, "cache_write_tokens": writes}
    if breakdown is not None:
        details["cache_write_tokens_details"] = breakdown
    return CompletionUsage.model_validate(
        {
            "prompt_tokens": 12000,
            "completion_tokens": 1000,
            "total_tokens": 13000,
            "prompt_tokens_details": details,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        }
    )


def test_gpt_5_6_terra_pricing_is_tracked():
    assert PRICING[("openai", "gpt-5.6-terra")] == (2.00, 12.00)
    assert compute_cost("openai", "gpt-5.6-terra", 100_000, 100_000) == Decimal("1.4")


@pytest.mark.parametrize(
    "model, expected",
    [
        ("gpt-5.6-terra", "0.0323"),
        ("gpt-6-luna", "0.001515"),
    ],
)
def test_cache_reads_and_writes_are_not_charged_twice(model, expected):
    # 1K ordinary input + 4K cache reads + 7K cache writes + 1K output.
    assert compute_cost(
        "openai",
        model,
        12000,
        1000,
        usage=provider_usage(4000, 7000, reasoning=500),
    ) == Decimal(expected)


@pytest.mark.parametrize(
    "model, expected",
    [
        ("gpt-5.6-terra", "0.0423"),
        ("gpt-6-luna", "0.002015"),
    ],
)
def test_cache_write_lifetimes_use_their_own_rates(model, expected):
    assert compute_cost(
        "openai",
        model,
        12000,
        1000,
        usage=provider_usage(
            4000,
            7000,
            breakdown={
                "ttl_30m_tokens": 3000,
                "ttl_12h_tokens": 4000,
            },
        ),
    ) == Decimal(expected)


def test_lifetime_breakdown_without_redundant_total():
    usage = SimpleNamespace(
        prompt_tokens_details={
            "cached_tokens": 4000,
            "cache_write_tokens_details": {"ttl_30m_tokens": 3000, "ttl_12h_tokens": 4000},
        }
    )
    assert compute_cost(
        "openai",
        "gpt-5.6-terra",
        12000,
        1000,
        usage=usage,
    ) == Decimal("0.0423")


def test_production_usage_example():
    assert compute_cost(
        "openai",
        "gpt-5.6-terra",
        96975,
        1583,
        usage=provider_usage(7004, 89968),
    ) == Decimal("0.2453228")


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5-mini", "0.00235"),
        ("gpt-5.2", "0.01645"),
        ("gpt-5", "0.01175"),
        ("gpt-4o-mini", "0.00105"),
    ],
)
def test_older_models_cache_read_discounts(model, expected):
    assert compute_cost(
        "openai",
        model,
        5000,
        1000,
        usage=provider_usage(4000),
    ) == Decimal(expected)


@pytest.mark.parametrize("usage", [None, SimpleNamespace(), provider_usage()])
def test_without_cache_details_input_keeps_ordinary_rate(usage):
    assert compute_cost(
        "openai",
        "gpt-5.6-terra",
        12000,
        1000,
        usage=usage,
    ) == Decimal("0.036")


@pytest.mark.parametrize(
    "model, tokens_input, expected",
    [
        ("gpt-5.6-terra", 272000, "0.556"),
        ("gpt-5.6-terra", 272001, "1.106004"),
        ("gpt-6-luna", 272000, "0.0277"),
        ("gpt-6-luna", 272001, "0.0551502"),
    ],
)
def test_long_context_rate_boundary(model, tokens_input, expected):
    assert compute_cost(
        "openai",
        model,
        tokens_input,
        1000,
    ) == Decimal(expected)


@pytest.mark.parametrize(
    "model, expected",
    [
        ("gpt-5.6-terra", "1.258"),
        ("gpt-6-luna", "0.06275"),
    ],
)
def test_long_context_cache_rates(model, expected):
    assert compute_cost(
        "openai",
        model,
        300000,
        1000,
        usage=provider_usage(
            100000,
            150000,
            breakdown={
                "ttl_30m_tokens": 100000,
                "ttl_12h_tokens": 50000,
            },
        ),
    ) == Decimal(expected)


@pytest.mark.parametrize(
    "usage",
    [
        provider_usage(8000, 8000),
        provider_usage(0, 5000, breakdown={"ttl_12h_tokens": 6000}),
        provider_usage(0, 5000, breakdown={"ttl_30m_tokens": 3000, "ttl_12h_tokens": 3000}),
    ],
)
def test_inconsistent_cache_counts_are_reported_as_technical_errors(usage):
    with pytest.raises(ValueError, match="Inconsistent provider cache token counts"):
        compute_cost("openai", "gpt-5.6-terra", 12000, 1000, usage=usage)


def test_voyage_pricing_is_unchanged():
    assert compute_cost("voyageai", "voyage-law-2", 10000, 0) == Decimal("0.0012")
    assert compute_cost("voyageai", "rerank-2", 10000, 0) == Decimal("0.0005")
    assert compute_cost("voyageai", "rerank-3", 10000, 0) == Decimal("0.0005")


async def test_logged_cost_persists_cache_adjusted_amount(monkeypatch):
    from tests.conftest import test_session_factory

    monkeypatch.setattr("app.services.cost_tracker.async_session_factory", test_session_factory)
    tracker = CostTracker()
    tracker.log_bg(
        provider="openai",
        model="gpt-5.6-terra",
        operation_type="generate",
        tokens_input=12000,
        tokens_output=1000,
        usage=provider_usage(4000, 7000),
    )
    await tracker.flush()
    async with test_session_factory() as session:
        row = (await session.execute(select(ApiUsageLog))).scalar_one()
    assert row.cost_usd == Decimal("0.032300")
    assert row.tokens_input == 12000
    assert row.tokens_output == 1000


def test_rerank_3_pricing_is_tracked_at_the_same_rate_as_rerank_2():
    assert PRICING[("voyageai", "rerank-3")] == PRICING[("voyageai", "rerank-2")]
    assert compute_cost("voyageai", "rerank-3", 10_000, 0) == Decimal("0.0005")
