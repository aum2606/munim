"""What a model call would cost at the provider's list price, even when a free tier makes it free.

Integers only: prices are micro-dollars per million tokens, so a result is whole micro-dollars.
A model that is not listed costs 0 and is reported as unpriced, never guessed. Prices change:
re-check them before publishing a number (each line names where it came from).
"""

# model id -> (input, output) in micro-USD per 1M tokens (150_000 = $0.15 per 1M tokens).
# Source for both: https://console.groq.com/docs/model/openai/gpt-oss-120b and .../gpt-oss-20b,
# checked 2026-11-17.
LIST_PRICES: dict[str, tuple[int, int]] = {
    "openai/gpt-oss-120b": (150_000, 600_000),
    "openai/gpt-oss-20b": (75_000, 300_000),
}


def is_priced(model: str | None) -> bool:
    return model in LIST_PRICES


def estimate_cost_micros(model: str | None, prompt_tokens: int, completion_tokens: int) -> int:
    """Micro-dollars at list price, rounded to the nearest micro-dollar. 0 for an unlisted model."""
    if model not in LIST_PRICES:
        return 0
    price_in, price_out = LIST_PRICES[model]
    return (prompt_tokens * price_in + completion_tokens * price_out + 500_000) // 1_000_000
