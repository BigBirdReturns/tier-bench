from __future__ import annotations

import os

from cost_guard import CostGuard, Tier
from harness.prompting import SYSTEM_RULES
from harness.sanitize import sanitize_model_output

# Singleton guard: daily spend accumulates across all calls in this process.
_GUARD = CostGuard(
    max_cost_per_call=float(os.environ.get("HARNESS_MAX_PER_CALL", "0.50")),
    max_daily_spend=float(os.environ.get("HARNESS_MAX_DAILY", "10.0")),
)


def get_guard() -> CostGuard:
    """Return the shared CostGuard instance."""
    return _GUARD


def call_with_guard(model: str, tier: Tier, prompt: str) -> dict:
    out = _GUARD.call(
        model=model,
        tier=tier,
        system=SYSTEM_RULES,
        messages=[{"role": "user", "content": prompt}],
    )

    content = out.get("content")
    if isinstance(content, str):
        cleaned, reason = sanitize_model_output(content)
        if reason is not None:
            out["status"] = "error"
            out["reason"] = f"output_rejected:{reason}"
            out["content"] = None
        else:
            out["content"] = cleaned
    elif out.get("status") == "ok":
        out["status"] = "error"
        out["reason"] = "empty_or_non_string_output"
        out["content"] = None

    return out
