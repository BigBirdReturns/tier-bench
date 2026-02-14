from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ModelTierStats:
    attempts: int = 0
    successes: int = 0
    total_cost: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def avg_cost_per_attempt(self) -> float:
        return self.total_cost / self.attempts if self.attempts else 0.0

    @property
    def cost_per_success(self) -> float:
        return (self.avg_cost_per_attempt / self.success_rate) if self.success_rate else float("inf")

def compute(path: Path) -> dict[tuple[str, str], ModelTierStats]:
    stats: dict[tuple[str, str], ModelTierStats] = defaultdict(ModelTierStats)
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row.get("model"), row.get("tier"))
        s = stats[key]
        s.attempts += 1
        if row.get("pass") is True:
            s.successes += 1
        c = row.get("actual_cost")
        if isinstance(c, (int, float)):
            s.total_cost += float(c)
    return stats
