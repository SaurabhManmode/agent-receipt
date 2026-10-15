"""Rough list-price estimates (USD per 1M tokens).

These are *estimates* from public list prices and drift over time. Subscription
plans (Claude Pro/Max, ChatGPT Plus/Pro) don't bill per token at all, in which
case the number is "what this would have cost on the API".

Override any model with a JSON file via AGENT_RECEIPT_PRICES, e.g.
  {"my-model": {"input": 2, "output": 8, "cache_write": 2.5, "cache_read": 0.2}}
Keys are matched as substrings of the model name, first match wins.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .model import Usage

# order matters: more specific patterns first
_ANTHROPIC = [
    ("claude-3-opus", 15, 75), ("opus-4-1", 15, 75), ("opus-4-0", 15, 75), ("claude-opus-4-2025", 15, 75),
    ("opus", 5, 25),
    ("sonnet", 3, 15),
    ("claude-3-haiku", 0.25, 1.25), ("3-5-haiku", 0.8, 4), ("haiku", 1, 5),
]
_OPENAI = [
    ("gpt-5-nano", 0.05, 0.40), ("gpt-5-mini", 0.25, 2), ("gpt-5", 1.25, 10),
    ("codex-mini", 1.5, 6), ("o4-mini", 1.1, 4.4), ("o3", 2, 8),
    ("gpt-4.1-mini", 0.4, 1.6), ("gpt-4.1", 2, 8), ("gpt-4o", 2.5, 10),
]


def _table() -> list:
    rows = []
    for key, i, o in _ANTHROPIC:
        rows.append((key, {"input": i, "output": o, "cache_write": i * 1.25, "cache_read": i * 0.1}))
    for key, i, o in _OPENAI:
        rows.append((key, {"input": i, "output": o, "cache_write": i, "cache_read": i * 0.1}))
    custom = os.environ.get("AGENT_RECEIPT_PRICES")
    if custom and os.path.exists(custom):
        with open(custom, encoding="utf-8") as fh:
            rows = list(json.load(fh).items()) + rows
    return rows


def rates_for(model: str) -> Optional[dict]:
    m = model.lower()
    for key, rate in _table():
        if key.lower() in m:
            return rate
    return None


def cost(model: str, u: Usage) -> Optional[float]:
    r = rates_for(model)
    if r is None:
        return None
    return (u.input * r["input"] + u.output * r["output"]
            + u.cache_write * r.get("cache_write", r["input"])
            + u.cache_read * r.get("cache_read", r["input"])) / 1_000_000


def session_cost(models: dict) -> tuple:
    """Return (total_usd_or_None, {model: usd_or_None})."""
    per, total, known = {}, 0.0, False
    for model, u in models.items():
        c = cost(model, u)
        per[model] = c
        if c is not None:
            total += c
            known = True
    return (total if known else None), per


def cache_savings(models: dict) -> float:
    """USD saved because cached reads are billed below the normal input rate."""
    saved = 0.0
    for model, u in models.items():
        r = rates_for(model)
        if r:
            saved += u.cache_read * (r["input"] - r.get("cache_read", r["input"])) / 1_000_000
    return saved
