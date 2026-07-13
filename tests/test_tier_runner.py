#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO = Path(__file__).resolve().parents[1]
TEST_TMP = REPO / ".test-tmp"
sys.path.insert(0, str(REPO))

from tier_runner.core import RunError, run_task, verify_run  # noqa: E402
from tier_runner.adapters.claude_code import (  # noqa: E402
    EMPTY_MCP_CONFIG,
    REQUIRED_CLAUDE_FLAGS,
    _help_surface_bytes,
    _packet_access_args,
    _packet_permission_args,
    _subscription_env,
    _runtime_model,
    _usage,
    _usage_evidenced,
)
from tier_runner.events import (  # noqa: E402
    InterventionError,
    event_hash,
    start,
    stop,
    validate_events,
)


FAKE_BACKEND = r'''
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
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
if any(key.startswith("TIER_") for key in os.environ):
    raise SystemExit(4)
if (root / ".git").exists() or (root / "AGENTS.md").exists() or (root / "CLAUDE.md").exists():
    raise SystemExit(3)
task_id = dispatch["task_id"]
session_seed = (
    "voided-session"
    if task_id in {"voided-session-error", "voided-session-pass"}
    else task_id
)
(root / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
if task_id == "prompt-tamper":
    Path(a.prompt).write_text("tampered\n", encoding="utf-8")
if task_id == "scope-bad":
    (root / "outside.py").write_text("bad = True\n", encoding="utf-8")
if task_id == "telemetry-bad":
    raise SystemExit(0)
extra = {
    "backend_manifest_sha256": dispatch["backend_manifest_sha256"],
    "backend_surface": "fixture",
    "cost_basis": "shadow-estimated",
    "dispatch_receipt_sha256": __import__("hashlib").sha256(
        Path(a.dispatch).read_bytes()
    ).hexdigest(),
    "prompt_template_sha256": dispatch["prompt_template_sha256"],
    "runtime_model_id": "fake-haiku",
    "session_id": str(uuid.uuid5(uuid.NAMESPACE_URL, session_seed)),
    "telemetry_complete": True,
    "tool_versions": {"fake_backend": "1"},
}
call = {
    "ts": datetime.now(timezone.utc).isoformat(),
    "account": "fixture",
    "model": "fake-haiku",
    "tier": "cheap",
    "task_id": "wrong-task" if task_id == "task-id-bad" else task_id,
    "phase": a.arm,
    "outcome": "error" if task_id == "voided-session-error" else "pass",
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


PROMPT = """Implement the requested change.
Task: {{TASK}}
Files:
{{FILES}}
Acceptance: {{ACCEPTANCE}}
Base: {{BASE_COMMIT}}
"""


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_repo(parent: Path) -> Path:
    repo = parent / "subject"
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "tier-runner@example.invalid"], repo)
    _run(["git", "config", "user.name", "Tier Runner Test"], repo)
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("hidden repository instructions\n", encoding="utf-8")
    (repo / "fake_backend.py").write_text(FAKE_BACKEND, encoding="utf-8")
    (repo / "accept_mutate.py").write_text(
        "from pathlib import Path\n"
        "Path('app.py').write_text('def value():\\n    return 3\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (repo / "hands.prompt.txt").write_text(PROMPT, encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-q", "-m", "fixture base"], repo)
    template_blob = subprocess.run(
        ["git", "cat-file", "blob", "HEAD:hands.prompt.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
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
    _run(["git", "add", "pilot_backends.json"], repo)
    _run(["git", "commit", "-q", "-m", "freeze backend manifest"], repo)
    return repo


def acceptance(expected: int) -> str:
    return f'"{sys.executable}" -c "import app; assert app.value() == {expected}"'


def test_accepts_and_preserves_source(parent: Path) -> None:
    repo = make_repo(parent)
    out = parent / "accepted"
    receipt = run_task(
        repo=repo,
        task_id="accepted",
        task="make value return two",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "ACCEPTED", receipt
    assert receipt["worktree_removed"] is True
    assert (repo / "app.py").read_text(encoding="utf-8").endswith("return 1\n")
    assert not (out / "model-packet").exists()
    assert (out / "change.patch").read_text(encoding="utf-8").find("return 2") >= 0
    ledger = json.loads((out / "ledger.jsonl").read_text(encoding="utf-8"))
    dispatch_hash = _sha(out / "dispatch-receipt.json")
    assert ledger["extra"]["dispatch_receipt_sha256"] == dispatch_hash
    assert ledger["extra"]["cost_basis"] == "shadow-estimated"
    assert verify_run(out) == []

    patch = out / "change.patch"
    original = patch.read_bytes()
    patch.write_bytes(original + b"tamper")
    assert "artifact patch hash mismatch" in verify_run(out)
    patch.write_bytes(original)
    assert verify_run(out) == []


def test_scope_violation_fails_closed(parent: Path) -> None:
    repo = make_repo(parent)
    receipt = run_task(
        repo=repo,
        task_id="scope-bad",
        task="attempt scope escape",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "scope-bad-out",
    )
    assert receipt["state"] == "ERROR"
    assert receipt["changes"]["scope_violations"] == ["outside.py"]
    assert "acceptance" not in receipt


def test_missing_telemetry_fails_closed(parent: Path) -> None:
    repo = make_repo(parent)
    out = parent / "telemetry-bad-out"
    receipt = run_task(
        repo=repo,
        task_id="telemetry-bad",
        task="omit telemetry",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "ERROR"
    assert not (out / "ledger.jsonl").exists()
    assert any("no backend-result" in error for error in receipt["errors"])


def test_acceptance_rejection_is_preserved(parent: Path) -> None:
    repo = make_repo(parent)
    receipt = run_task(
        repo=repo,
        task_id="acceptance-bad",
        task="make value return two",
        files=["app.py"],
        acceptance=acceptance(3),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "acceptance-bad-out",
    )
    assert receipt["state"] == "REJECTED"
    assert receipt["acceptance"]["returncode"] != 0
    assert (parent / "acceptance-bad-out" / "change.patch").exists()


def test_acceptance_cannot_mutate_the_tested_patch(parent: Path) -> None:
    repo = make_repo(parent)
    receipt = run_task(
        repo=repo,
        task_id="acceptance-mutates",
        task="make value return two",
        files=["app.py"],
        acceptance=f'"{sys.executable}" accept_mutate.py',
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "acceptance-mutates-out",
    )
    assert receipt["state"] == "ERROR"
    assert any("acceptance command mutated" in error for error in receipt["errors"])


def test_backend_cannot_mutate_precall_evidence(parent: Path) -> None:
    repo = make_repo(parent)
    receipt = run_task(
        repo=repo,
        task_id="prompt-tamper",
        task="tamper with prompt",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "prompt-tamper-out",
    )
    assert receipt["state"] == "ERROR"
    assert any("immutable prompt" in error for error in receipt["errors"])


def test_task_id_and_session_freshness_fail_closed(parent: Path) -> None:
    repo = make_repo(parent)
    bad = run_task(
        repo=repo,
        task_id="task-id-bad",
        task="misbind task identity",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "task-id-bad-out",
    )
    assert bad["state"] == "ERROR"
    assert any("task_id contradicts" in error for error in bad["errors"])

    first = run_task(
        repo=repo,
        task_id="reused-session",
        task="first call",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "reused-session-1",
    )
    assert first["state"] == "ACCEPTED"
    second = run_task(
        repo=repo,
        task_id="reused-session",
        task="second call",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "reused-session-2",
    )
    assert second["state"] == "ERROR"
    assert any("reused a session_id" in error for error in second["errors"])


def test_voided_call_still_consumes_its_session(parent: Path) -> None:
    repo = make_repo(parent)
    first = run_task(
        repo=repo,
        task_id="voided-session-error",
        task="provider call errors after allocating a session",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "voided-session-error",
    )
    assert first["state"] == "ERROR"
    assert any("outcome is 'error'" in error for error in first["errors"])

    second = run_task(
        repo=repo,
        task_id="voided-session-pass",
        task="backend attempts to reuse the voided call's session",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "voided-session-pass",
    )
    assert second["state"] == "ERROR"
    assert any("reused a session_id" in error for error in second["errors"])


def test_prompt_values_cannot_inject_or_trip_template_markers(parent: Path) -> None:
    repo = make_repo(parent)
    task = "keep this operator text literal: {{ACCEPTANCE}}"
    command = acceptance(2) + " {{TASK}}"
    out = parent / "marker-values"
    receipt = run_task(
        repo=repo,
        task_id="marker-values",
        task=task,
        files=["app.py"],
        acceptance=command,
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "ACCEPTED", receipt
    prompt = (out / "prompt.txt").read_text(encoding="utf-8")
    assert task in prompt
    assert command in prompt


def test_output_and_verifier_bindings_fail_closed(parent: Path) -> None:
    repo = make_repo(parent)
    try:
        run_task(
            repo=repo,
            task_id="bad-output",
            task="write receipts into source",
            files=["app.py"],
            acceptance=acceptance(2),
            manifest=repo / "pilot_backends.json",
            arm="arm_b",
            output_dir=repo / "runner-output",
        )
    except RunError as exc:
        assert "operator's checkout" in str(exc)
    else:
        raise AssertionError("runner wrote output into the operator checkout")

    out = parent / "verify-semantic-out"
    receipt = run_task(
        repo=repo,
        task_id="verify-semantic",
        task="make value return two",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "ACCEPTED"
    on_disk = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    on_disk["arm"] = "arm_c"
    (out / "receipt.json").write_text(json.dumps(on_disk), encoding="utf-8")
    assert "dispatch arm does not bind the final receipt" in verify_run(out)


def test_working_template_drift_cannot_change_pinned_prompt(parent: Path) -> None:
    repo = make_repo(parent)
    (repo / "hands.prompt.txt").write_text("drift\n", encoding="utf-8")
    out = parent / "drift-out"
    receipt = run_task(
        repo=repo,
        task_id="drift",
        task="use the committed template",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "ACCEPTED"
    prompt = (out / "prompt.txt").read_text(encoding="utf-8")
    assert "use the committed template" in prompt
    assert prompt != "drift\n"


def test_instruction_file_cannot_be_model_scope(parent: Path) -> None:
    repo = make_repo(parent)
    receipt = run_task(
        repo=repo,
        task_id="instructions",
        task="rewrite repository instructions",
        files=["AGENTS.md"],
        acceptance="exit 0",
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "instructions-out",
    )
    assert receipt["state"] == "ERROR"
    assert any("instruction files" in error for error in receipt["errors"])


def test_prompt_must_bind_every_registered_input(parent: Path) -> None:
    repo = make_repo(parent)
    (repo / "hands.prompt.txt").write_text("Task only: {{TASK}}\n", encoding="utf-8")
    _run(["git", "add", "hands.prompt.txt"], repo)
    _run(["git", "commit", "-q", "-m", "bad incomplete prompt"], repo)
    template_blob = subprocess.run(
        ["git", "cat-file", "blob", "HEAD:hands.prompt.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    manifest = json.loads((repo / "pilot_backends.json").read_text(encoding="utf-8"))
    manifest["prompt_templates"]["hands"]["sha256"] = hashlib.sha256(
        template_blob
    ).hexdigest()
    (repo / "pilot_backends.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _run(["git", "add", "pilot_backends.json"], repo)
    _run(["git", "commit", "-q", "-m", "bind bad prompt hash"], repo)
    receipt = run_task(
        repo=repo,
        task_id="missing-markers",
        task="no",
        files=["app.py"],
        acceptance=acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=parent / "missing-markers-out",
    )
    assert receipt["state"] == "ERROR"
    assert any("missing required markers" in error for error in receipt["errors"])


def test_interventions_are_global_and_paired(parent: Path) -> None:
    log = parent / "interventions.jsonl"
    first = start(log, "t1", "arm_b", "brief")
    try:
        start(log, "t2", "arm_c", "review")
    except InterventionError:
        pass
    else:
        raise AssertionError("overlapping intervention was accepted")
    stop(log, first)
    rows = validate_events(log)
    assert [row["event"] for row in rows] == ["start", "stop"]
    assert rows[1]["previous_event_sha256"] == rows[0]["event_sha256"]
    try:
        stop(log, first)
    except InterventionError:
        pass
    else:
        raise AssertionError("duplicate stop was accepted")
    tampered = [dict(row) for row in rows]
    tampered[1]["ts"] = "2000-01-01T00:00:00Z"
    tampered[1]["event_sha256"] = event_hash(tampered[1])
    log.write_text("".join(json.dumps(row) + "\n" for row in tampered), encoding="utf-8")
    try:
        validate_events(log)
    except InterventionError as exc:
        assert "out of order" in str(exc)
    else:
        raise AssertionError("out-of-order intervention timestamps were accepted")


def test_claude_receipt_parser_requires_provider_model_evidence(parent: Path) -> None:
    del parent
    data = {
        "modelUsage": {"claude-haiku-exact": {}},
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 3,
        },
    }
    assert _runtime_model(data, "requested-alias") == ("claude-haiku-exact", True)
    assert _runtime_model({}, "requested-alias") == ("requested-alias", False)
    assert _usage(data) == {
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 5,
        "cache_write_tokens": 3,
    }
    assert _usage_evidenced(data) is True
    assert _usage_evidenced({"usage": {}}) is False
    sanitized = _subscription_env({
        "ANTHROPIC_API_KEY": "must-not-reach-subscription-cli",
        "AWS_ACCESS_KEY_ID": "must-not-switch-to-bedrock",
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription-auth-is-allowed",
        "PATH": "kept",
        "TIER_RUN_DIR": "must-not-reach-model",
    })
    assert sanitized == {
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription-auth-is-allowed",
        "PATH": "kept",
    }


def test_claude_help_hash_binds_raw_bytes(parent: Path) -> None:
    del parent
    raw = b"\xff platform-specific help\r\n" + b"\n".join(
        flag.encode("ascii") for flag in sorted(REQUIRED_CLAUDE_FLAGS)
    )
    assert _help_surface_bytes(raw) == hashlib.sha256(raw).hexdigest()


def test_claude_empty_mcp_config_has_required_shape(parent: Path) -> None:
    del parent
    assert json.loads(EMPTY_MCP_CONFIG) == {"mcpServers": {}}


def test_claude_explicitly_allows_only_packet_path(parent: Path) -> None:
    packet = parent / "packet"
    assert _packet_access_args(packet) == ["--add-dir", str(packet)]


def test_claude_permissions_are_scoped_to_dispatched_files(parent: Path) -> None:
    del parent
    assert _packet_permission_args(["src/a.py", "docs\\b.md"]) == [
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        "Read(src/a.py)",
        "Edit(src/a.py)",
        "Read(docs/b.md)",
        "Edit(docs/b.md)",
    ]


def main() -> int:
    TEST_TMP.mkdir(exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix="tier-runner-", dir=TEST_TMP))
    tests = [
        test_accepts_and_preserves_source,
        test_scope_violation_fails_closed,
        test_missing_telemetry_fails_closed,
        test_acceptance_rejection_is_preserved,
        test_acceptance_cannot_mutate_the_tested_patch,
        test_backend_cannot_mutate_precall_evidence,
        test_task_id_and_session_freshness_fail_closed,
        test_voided_call_still_consumes_its_session,
        test_prompt_values_cannot_inject_or_trip_template_markers,
        test_output_and_verifier_bindings_fail_closed,
        test_working_template_drift_cannot_change_pinned_prompt,
        test_instruction_file_cannot_be_model_scope,
        test_prompt_must_bind_every_registered_input,
        test_interventions_are_global_and_paired,
        test_claude_receipt_parser_requires_provider_model_evidence,
        test_claude_help_hash_binds_raw_bytes,
        test_claude_empty_mcp_config_has_required_shape,
        test_claude_explicitly_allows_only_packet_path,
        test_claude_permissions_are_scoped_to_dispatched_files,
    ]
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(f"OK — {len(tests)}/{len(tests)} tier-runner tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
