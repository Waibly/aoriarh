from types import SimpleNamespace

from app.rag.usage_metrics import usage_details


def test_missing_details_are_unknown_not_zero():
    assert usage_details(None) == {}
    assert usage_details(SimpleNamespace()) == {}


def test_provider_counts_are_not_added_to_totals_or_coerced():
    assert usage_details(
        SimpleNamespace(
            prompt_tokens_details={"cached_tokens": 0, "cache_write_tokens": 120},
            completion_tokens_details=SimpleNamespace(reasoning_tokens=32),
        )
    ) == {"tokens_cached": 0, "tokens_cache_write": 120, "tokens_reasoning": 32}
    assert (
        usage_details(
            SimpleNamespace(
                prompt_tokens_details={"cached_tokens": "20"},
                completion_tokens_details={"reasoning_tokens": -1},
            )
        )
        == {}
    )
