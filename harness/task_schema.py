from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class Task:
    task_id: str
    tier: str                 # "T0"..."T5"
    prompt_template: str      # rendered with file contents and optional hints
    fixture_dir: Path
    target_relpath: str       # file to edit inside fixture
    run_command: list[str]    # deterministic execution (for behavior capture and tests)
    validate: dict[str, Any]  # flags for deterministic validators
    max_lines_changed: int
    allowed_files: list[str]

    @staticmethod
    def from_json(path: Path) -> "Task":
        import json
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Task(
            task_id=raw["task_id"],
            tier=raw["tier"],
            prompt_template=raw["prompt_template"],
            fixture_dir=Path(raw["fixture_dir"]),
            target_relpath=raw["target_relpath"],
            run_command=list(raw["run_command"]),
            validate=dict(raw["validate"]),
            max_lines_changed=int(raw["max_lines_changed"]),
            allowed_files=list(raw["allowed_files"]),
        )
