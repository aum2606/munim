import pytest

from app.llm.costs import LIST_PRICES, estimate_cost_micros, is_priced


def test_cost_is_whole_micro_dollars_at_list_price() -> None:
    # gpt-oss-120b: $0.15 in, $0.60 out per 1M tokens. 2,000 in + 500 out = $0.0003 + $0.0003.
    assert estimate_cost_micros("openai/gpt-oss-120b", 2_000, 500) == 600
    # gpt-oss-20b is half the input price and half the output price.
    assert estimate_cost_micros("openai/gpt-oss-20b", 2_000, 500) == 300


def test_a_model_without_a_listed_price_costs_nothing_and_is_not_guessed() -> None:
    assert estimate_cost_micros("fake-1", 1_000_000, 1_000_000) == 0
    assert estimate_cost_micros(None, 10, 10) == 0
    assert not is_priced("fake-1") and is_priced("openai/gpt-oss-20b")


def test_rounding_and_zero_tokens() -> None:
    assert estimate_cost_micros("openai/gpt-oss-120b", 0, 0) == 0
    assert estimate_cost_micros("openai/gpt-oss-120b", 3, 0) == 0  # 0.45 micro-dollars rounds down
    assert estimate_cost_micros("openai/gpt-oss-120b", 4, 0) == 1  # 0.6 rounds up


@pytest.mark.parametrize("model", list(LIST_PRICES))
def test_prices_are_integers_and_output_costs_at_least_input(model: str) -> None:
    price_in, price_out = LIST_PRICES[model]
    assert isinstance(price_in, int) and isinstance(price_out, int)
    assert 0 < price_in <= price_out
