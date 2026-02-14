from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cost_guard import TIER_ROUTING, Tier

def models_for_tier(tier: Tier) -> list[str]:
    return list(TIER_ROUTING.get(tier, []))

@dataclass(frozen=True)
class RunConfig:
    results_path: Path = Path("harness_results.jsonl")
    work_root: Path = Path(".work")
    max_escalations: int = 0  # harness does not auto-escalate; routing order is tested as-is
