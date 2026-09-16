"""Token cost tracking and pricing calculator matching Claude Code CostTracker."""

from __future__ import annotations

# Pricing per million tokens (USD): { input, output, cache_read, cache_write }
PRICING_TABLE = {
    # Anthropic Claude models
    "claude-3-7-sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    # OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.0, "cache_read": 1.25, "cache_write": 2.50},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.15},
    "o1": {"input": 15.0, "output": 60.0, "cache_read": 7.50, "cache_write": 15.0},
    "o3-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.55, "cache_write": 1.10},
    # DeepSeek models
    "deepseek-chat": {"input": 0.14, "output": 0.28, "cache_read": 0.014, "cache_write": 0.14},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_read": 0.14, "cache_write": 0.55},
    # Default fallback rate
    "default": {"input": 2.0, "output": 8.0, "cache_read": 0.20, "cache_write": 2.50},
}


def get_model_pricing(model_name: str) -> dict[str, float]:
    lowered = (model_name or "").lower()
    for key, rate in PRICING_TABLE.items():
        if key in lowered:
            return rate
    return PRICING_TABLE["default"]


def calculate_turn_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Calculate exact USD cost for a given turn."""
    rates = get_model_pricing(model)
    cost = (
        (prompt_tokens * rates["input"] / 1_000_000)
        + (completion_tokens * rates["output"] / 1_000_000)
        + (cache_read_tokens * rates["cache_read"] / 1_000_000)
        + (cache_write_tokens * rates["cache_write"] / 1_000_000)
    )
    return round(cost, 6)
