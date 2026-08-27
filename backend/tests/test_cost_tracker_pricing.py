from decimal import Decimal

from app.services.cost_tracker import PRICING, compute_cost


def test_gpt_5_6_terra_pricing_is_tracked():
    assert PRICING[("openai", "gpt-5.6-terra")] == (2.00, 12.00)
    assert compute_cost("openai", "gpt-5.6-terra", 1_000_000, 1_000_000) == Decimal("14.0")
