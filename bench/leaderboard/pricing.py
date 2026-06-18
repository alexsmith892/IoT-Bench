from __future__ import annotations

from typing import Any


PRICING_TABLE_VERSION = "2026-06-18"

# Keep the table conservative: unknown or moving model prices produce null USD
# rather than silently estimating spend.
TOKEN_PRICES_USD_PER_1M: dict[str, dict[str, float]] = {}


def cost_usd(model: str, usage: dict[str, Any] | None) -> float | None:
    if usage is None:
        return None
    prices = TOKEN_PRICES_USD_PER_1M.get(model)
    if prices is None:
        return None
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if input_tokens is None or output_tokens is None:
        return None
    return round(
        (float(input_tokens) * prices["input"] + float(output_tokens) * prices["output"]) / 1_000_000,
        8,
    )

