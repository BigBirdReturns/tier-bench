"""Shared fixture-mode scaffolding for the referee-kernel negative witnesses.

Every witness builds a throwaway Git repo and drives it through
`tier_runner.core.run_task`/`verify_run` with a small Python script standing
in for a model "backend" (the same fixture-mode shape `tests/test_tier_runner.py`
already uses: `surface: "fixture"`, `cost_basis: "shadow-estimated"`). Zero
model calls, zero writes outside a tempfile.mkdtemp() directory, zero edits to
tier_runner/ itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


PROMPT = (
    "Implement the requested change.\n"
    "Task: {{TASK}}\n"
    "Files:\n{{FILES}}\n"
    "Acceptance: {{ACCEPTANCE}}\n"
    "Base: {{BASE_COMMIT}}\n"
)

# Placeholder tokens substituted with .replace(), not str.format()/f-string —
# the generated file is itself Python source full of literal braces.
_BACKEND_TEMPLATE = '''
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

p = argparse.ArgumentParser()
p.add_argument("--arm", required=True)
p.add_argument("--dispatch", required=True)
p.add_argument("--prompt", required=True)
p.add_argument("--result", required=True)
p.add_argument("--worktree", required=True)
a = p.parse_args()
dispatch = json.loads(Path(a.dispatch).read_text(encoding="utf-8"))
root = Path(a.worktree)
task_id = dispatch["task_id"]
if __WRITE_APP__:
    (root / "app.py").write_text("def value():\\n    return __APP_VALUE__\\n", encoding="utf-8")
if __WRITE_OUTSIDE__:
    (root / "outside.py").write_text("bad = True\\n", encoding="utf-8")
extra = {
    "backend_manifest_sha256": dispatch["backend_manifest_sha256"],
    "backend_surface": "fixture",
    "cost_basis": "shadow-estimated",
    "dispatch_receipt_sha256": hashlib.sha256(Path(a.dispatch).read_bytes()).hexdigest(),
    "prompt_template_sha256": dispatch["prompt_template_sha256"],
    "runtime_model_id": "fake-haiku",
    "session_id": str(uuid.uuid5(uuid.NAMESPACE_URL, task_id)),
    "telemetry_complete": True,
    "tool_versions": {"fake_backend": "1"},
}
call = {
    "ts": datetime.now(timezone.utc).isoformat(),
    "account": "fixture",
    "model": "fake-haiku",
    "tier": "cheap",
    "task_id": task_id,
    "phase": a.arm,
    "outcome": "pass",
    "effort": "low",
    "input_tokens": 10,
    "output_tokens": 5,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "cost_usd": 0.001,
    "latency_ms": 1.0,
    "trial": 0,
    "note": "shadow-estimated fixture",
    "extra": extra,
}
Path(a.result).write_text(
    json.dumps({"schema": "tier-bench/tier-backend-result@1", "calls": [call]}),
    encoding="utf-8",
)
'''


def backend_source(*, write_app: bool = True, write_outside: bool = False, app_value: int = 2) -> str:
    """Render a fixture 'backend' stand-in: deterministic Python, no model calls."""
    return (
        _BACKEND_TEMPLATE
        .replace("__WRITE_APP__", repr(write_app))
        .replace("__WRITE_OUTSIDE__", repr(write_outside))
        .replace("__APP_VALUE__", str(app_value))
    )


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)


def acceptance(expected: int) -> str:
    return f'"{sys.executable}" -c "import app; assert app.value() == {expected}"'


def make_repo(parent: Path, backend_source_text: str, *, commit_manifest: bool = True) -> Path:
    """Fixture-mode subject repo: a fake backend stands in for a model."""
    repo = parent / "subject"
    repo.mkdir()
    run(["git", "init", "-q"], repo)
    run(["git", "config", "user.email", "referee-witness@example.invalid"], repo)
    run(["git", "config", "user.name", "Referee Witness"], repo)
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "fake_backend.py").write_text(backend_source_text, encoding="utf-8")
    (repo / "accept_mutate.py").write_text(
        "from pathlib import Path\n"
        "Path('app.py').write_text('def value():\\n    return 3\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (repo / "hands.prompt.txt").write_text(PROMPT, encoding="utf-8")
    run(["git", "add", "-A"], repo)
    run(["git", "commit", "-q", "-m", "fixture base"], repo)
    template_blob = subprocess.run(
        ["git", "cat-file", "blob", "HEAD:hands.prompt.txt"],
        cwd=repo, check=True, capture_output=True,
    ).stdout
    manifest = {
        "schema": "tier-bench/pilot-backends@1",
        "protocol_commit": "a" * 40,
        "isolation": {
            "fresh_session_per_call": True,
            "instruction_files": False,
            "auto_memory": False,
            "conversation_carryover": False,
        },
        "tool_versions": {"fake_backend": "1"},
        "prompt_templates": {
            "hands": {
                "path": "hands.prompt.txt",
                "sha256": hashlib.sha256(template_blob).hexdigest(),
            }
        },
        "arms": {
            "arm_b": {
                "model_id": "fake-haiku",
                "effort": "low",
                "surface": "fixture",
                "cost_basis": "shadow-estimated",
                "account": "fixture",
                "tier": "cheap",
                "prompt_template": "hands",
                "adapter": {
                    "command": [
                        sys.executable,
                        str((repo / "fake_backend.py").resolve()),
                        "--arm", "{arm}",
                        "--dispatch", "{dispatch_receipt}",
                        "--prompt", "{prompt}",
                        "--result", "{backend_result}",
                        "--worktree", "{worktree}",
                    ]
                },
            }
        },
    }
    (repo / "pilot_backends.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if commit_manifest:
        run(["git", "add", "pilot_backends.json"], repo)
        run(["git", "commit", "-q", "-m", "freeze backend manifest"], repo)
    return repo
