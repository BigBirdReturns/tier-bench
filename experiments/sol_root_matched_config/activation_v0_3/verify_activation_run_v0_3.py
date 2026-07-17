"""Verify and seal the exact typed-schema Sol-root administrative canary run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
FREEZE_SHA256 = "e2fc77aa845253a1f95be374b026b5b4131772ccf52f6365707afd31f55feb25"
RUN = EXPERIMENT / "run" / "activation_v0_3" / FREEZE_SHA256
RECEIPT = HERE / "execution_closure_receipt_v0_3.json"
EVIDENCE_FILES = (
    "authorization.json",
    "c00/accepted.json",
    "c00/cell.json",
    "c00/command.json",
    "c00/events.jsonl",
    "c00/final.json",
    "c00/stderr.txt",
    "c01/cell.json",
    "c01/command.json",
    "c01/events.jsonl",
    "c01/final.json",
    "c01/stderr.txt",
    "c01/workspace_snapshot.json",
)


class RunEvidenceError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RunEvidenceError(message)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunEvidenceError(f"cannot load {path}: {exc}") from exc


def events(path: Path) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise RunEvidenceError(f"cannot load events {path}: {exc}") from exc
    require(all(isinstance(value, dict) for value in values), "event stream contains a non-object")
    return values


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def config_value(command: list[str], key: str) -> str | None:
    target = f"{key}="
    for index, value in enumerate(command[:-1]):
        if value == "-c" and command[index + 1].startswith(target):
            return command[index + 1][len(target):]
    return None


def sandbox(command: list[str]) -> str | None:
    try:
        return command[command.index("--sandbox") + 1]
    except (ValueError, IndexError):
        return None


def completed_usage(values: list[dict[str, Any]]) -> dict[str, int]:
    completed = [value.get("usage") for value in values if value.get("type") == "turn.completed"]
    require(len(completed) == 1 and isinstance(completed[0], dict), "expected exactly one completed turn with usage")
    usage = completed[0]
    required = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    require(all(isinstance(usage.get(key), int) and usage[key] >= 0 for key in required), "invalid usage counters")
    return {key: usage[key] for key in required}


def build_receipt(run: Path = RUN) -> dict[str, Any]:
    for relative in EVIDENCE_FILES:
        require((run / relative).is_file(), f"missing evidence file: {relative}")

    authorization = load(run / "authorization.json")
    owner_cell = load(run / "c00/cell.json")
    owner_command = load(run / "c00/command.json")
    owner_final = load(run / "c00/final.json")
    owner_accepted = load(run / "c00/accepted.json")
    owner_events = events(run / "c00/events.jsonl")
    executor_cell = load(run / "c01/cell.json")
    executor_command = load(run / "c01/command.json")
    executor_final = load(run / "c01/final.json")
    executor_events = events(run / "c01/events.jsonl")
    executor_stderr = (run / "c01/stderr.txt").read_text(encoding="utf-8")
    snapshot = load(run / "c01/workspace_snapshot.json")

    require(authorization.get("freeze_sha256") == FREEZE_SHA256, "authorization binds another freeze")
    require(authorization.get("authorized_call_ceiling") == 59 and authorization.get("no_retries") is True, "authorization contract differs")
    require(owner_cell == {"cell_id": "gpt-5.6-sol@high#standard", "role": "owner", "sequence": 0}, "owner cell differs")
    require(sandbox(owner_command) == "read-only", "owner command was not read-only")
    require(owner_final == {"status": "ready"}, "owner final differs")
    require(owner_accepted == {"accepted": True, "cell_id": owner_cell["cell_id"], "role": "owner"}, "owner was not accepted exactly")
    require(executor_cell == {"cell_id": "gpt-5.6-sol@low#standard", "role": "executor", "sequence": 1}, "executor cell differs")
    require(sandbox(executor_command) == "workspace-write", "executor command did not request workspace-write")
    require(config_value(executor_command, "approval_policy") == '"never"', "executor approval policy differs")
    require(executor_final == {"status": "ready"}, "executor final differs")
    require("writing is blocked by read-only sandbox" in executor_stderr, "missing enforced read-only rejection")
    require(snapshot.get("git_status_porcelain_v1") == [] and snapshot.get("worktree_files") == [], "executor changed the worktree")
    require(snapshot.get("result_txt_exists") is False and snapshot.get("accepted_marker_exists") is False, "executor was incorrectly accepted")
    require(not (run / "c02").exists() and not (run / "completion.json").exists(), "runner did not stop after first executor failure")

    owner_usage = completed_usage(owner_events)
    executor_usage = completed_usage(executor_events)
    total_usage = {key: owner_usage[key] + executor_usage[key] for key in owner_usage}
    checks = {
        "exact_authorization_bound": True,
        "owner_first_and_accepted": True,
        "executor_requested_workspace_write": True,
        "executor_tool_router_enforced_read_only": True,
        "executor_created_no_files": True,
        "stopped_before_sequence_2": True,
        "no_retry": True,
        "zero_scientific_observations": True,
        "invocation_equivalence_proven": False,
    }
    return {
        "schema": "tier-bench/sol-root-activation/execution-closure-receipt@0.3",
        "status": "scientific_schedule_inadmissible_sandbox_invocation_non_equivalence",
        "freeze_sha256": FREEZE_SHA256,
        "checks": checks,
        "all_required_checks_pass": all(value is True for key, value in checks.items() if key != "invocation_equivalence_proven"),
        "calls": {
            "provider_calls_completed": 2,
            "owner_accepted": 1,
            "executor_attempted": 1,
            "executor_accepted": 0,
            "not_run": 57,
            "retries": 0,
        },
        "usage": {"owner": owner_usage, "executor": executor_usage, "total": total_usage},
        "finding": {
            "requested_sandbox": "workspace-write",
            "enforced_sandbox": "read-only",
            "classification": "runtime_invocation_non_equivalence_not_model_role_failure",
            "scientific_schedule_admissible": False,
        },
        "evidence_sha256": {relative: sha256(run / relative) for relative in EVIDENCE_FILES},
        "scientific_observations": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--run", type=Path, default=RUN)
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    args = parser.parse_args()
    try:
        expected = build_receipt(args.run)
        if args.command == "build":
            require(not args.receipt.exists(), f"refusing to overwrite {args.receipt}")
            args.receipt.write_bytes(canonical(expected))
        else:
            require(canonical(load(args.receipt)) == canonical(expected), "closure receipt differs from raw evidence")
    except (RunEvidenceError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("OK - 2-call administrative run sealed; scientific schedule inadmissible; zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
