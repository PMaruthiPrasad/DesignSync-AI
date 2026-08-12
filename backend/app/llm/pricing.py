"""Model pricing, in USD per million tokens.

Used for the estimated-cost figures shown in the observability panel. The mock
provider uses the same table so mock runs show realistic (if simulated) spend.
"""

from __future__ import annotations

# model id -> (input $/MTok, output $/MTok)
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # --- Google Vertex AI (default provider) ---
    "gemini-3.6-flash": (1.50, 7.50),
    # --- Anthropic ---
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # --- OpenAI ---
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6": (5.00, 30.00),          # alias for Sol
    "gpt-5.6-terra": (1.25, 7.50),     # mid tier; approximate
    "gpt-5.6-luna": (0.20, 1.20),
    # Used by the mock provider so its cost figures stay in a believable range.
    "mock-designsync-1": (5.00, 25.00),
}

DEFAULT_PRICE = (5.00, 25.00)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost of one call."""
    input_rate, output_rate = PRICE_PER_MTOK.get(model, DEFAULT_PRICE)
    cost = (prompt_tokens / 1_000_000) * input_rate + (
        completion_tokens / 1_000_000
    ) * output_rate
    return round(cost, 6)
