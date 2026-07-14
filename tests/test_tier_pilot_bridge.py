"""Deterministic production-bridge coordinator tests; fixture adapters only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tier_runner.pilot_bridge import (
    BridgeError,
    answer_and_resume_fixture_pilot_arm,
    start_fixture_pilot_arm,
    start_pilot_arm,
)
from tier_runner.pilot_composition import read_state
from tier_runner.pilot_manifest import load_pilot_composition


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(
        root, "-c", "user.name=Bridge Fixture", "-c",
        "user.email=bridge@example.invalid", "commit", "-m", message,
    )
    return _git(root, "rev-parse", "HEAD")


ADAPTER = r'''
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

p = argparse.ArgumentParser()
for name in ("arm", "stage", "dispatch", "prompt", "result", "worktree", "model", "account", "tier"):
    p.add_argument("--" + name.replace("_", "-"), required=True)
a = p.parse_args()
dispatch_path = Path(a.dispatch)
dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
prompt_raw = Path(a.prompt).read_bytes()
prompt = prompt_raw.decode("utf-8")
packet = Path(a.worktree)
outcome = "completed"
text = "sealed fixture plan"
if "BAD_QUESTION" in prompt and a.stage == "hands":
    outcome = "question"
    text = "Do the whole task for me"
elif "ASK_OPERATOR" in prompt and a.stage == "hands":
    outcome = "question"
    text = json.dumps({
        "schema": "tier-bench/tier-pilot-operator-question@1",
        "category": "interpretation",
        "question": "Which fixture policy applies?",
    }, sort_keys=True, separators=(",", ":"))
elif "ADAPTER_EXIT" in prompt:
    raise SystemExit(7)
elif a.stage != "driver_plan":
    if "CREATE_IGNORED" in prompt:
        target = packet / "data" / "cache.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("acceptance-secret\n", encoding="utf-8")
    else:
        target = packet / "target.txt"
        target.write_text("wrong\n" if "FAIL_FIRST" in prompt and a.stage == "hands" else "correct\n", encoding="utf-8")
    text = "candidate emitted"
if "DIRTY_SCOPE" in prompt:
    (packet / "rogue.txt").write_text("out of scope\n", encoding="utf-8")
call_id = dispatch["call_id"]
session = "session-fixed-reuse" if "FIXED_SESSION" in prompt else "session-" + call_id
ledger_outcome = "partial" if outcome == "question" else "pass"
call = {
    "ts": datetime.now(timezone.utc).isoformat(), "account": a.account,
    "model": a.model, "tier": a.tier, "task_id": dispatch["task_id"],
    "phase": a.arm, "outcome": ledger_outcome, "effort": "low",
    "input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 0,
    "cache_write_tokens": 0, "cost_usd": 0.0, "latency_ms": 1.0,
    "trial": dispatch["attempt"], "note": "shadow-estimated fixture",
    "extra": {
        "backend_manifest_sha256": dispatch["composition_manifest_sha256"],
        "backend_surface": "fixture", "cost_basis": "shadow-estimated",
        "dispatch_receipt_sha256": hashlib.sha256(dispatch_path.read_bytes()).hexdigest(),
        "prompt_template_sha256": dispatch["prompt_template"]["sha256"],
        "runtime_model_id": a.model, "session_id": session,
        "telemetry_complete": True, "tool_versions": {"fixture-adapter": "1"},
    },
}
raw_path = Path(a.result).with_name("provider.raw.bin")
pilot_output = {"outcome": outcome, "text": text}
raw_path.write_bytes(json.dumps({"pilot_output": pilot_output}, sort_keys=True).encode())
Path(a.result).write_text(json.dumps({
    "schema": "tier-bench/tier-backend-result@1", "calls": [call],
    "pilot_output": pilot_output,
    "artifacts": [{"name": "provider_raw", "path": raw_path.name,
                   "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()}],
}, sort_keys=True) + "\n", encoding="utf-8")
if "TAMPER_PRIOR" in prompt and a.stage == "hands":
    prior = Path(a.result).parents[1] / "01-driver_plan" / "provider.raw.bin"
    prior.write_bytes(b"tampered prior evidence")
'''


def _make_repos(root: Path) -> tuple[Path, Path, Path, str]:
    target = root / "target"
    evidence = root / "evidence"
    target.mkdir()
    evidence.mkdir()
    _git(target, "init", "-b", "main")
    _git(evidence, "init", "-b", "main")
    (target / "target.txt").write_text("old\n", encoding="utf-8")
    (target / "check.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "ok = Path('target.txt').read_text() == 'correct\\n'\n"
        "print('target mismatch: expected correct', file=sys.stderr) if not ok else None\n"
        "raise SystemExit(not ok)\n",
        encoding="utf-8",
    )
    base = _commit(target, "target base")
    adapter = evidence / "fixture_adapter.py"
    adapter.write_text(ADAPTER, encoding="utf-8")
    prompt_dir = evidence / "prompts"
    prompt_dir.mkdir()
    prompts = {
        "driver": "Plan {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}}\n",
        "hands": "Do {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}} {{DRIVER_PLAN}}\n",
        "repair": "Repair {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}} {{CANDIDATE_OUTPUT}} {{FAILED_ACCEPTANCE_REPORT}}\n",
        "question": "{{TASK_ID}} {{QUESTION}} {{EVIDENCE_SHA256}}\n",
        "resume": "Resume {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}} {{QUESTION}} {{ANSWER}} {{CANDIDATE_OUTPUT}} {{FAILED_ACCEPTANCE_REPORT}}\n",
    }
    templates = {}
    for name, value in prompts.items():
        path = prompt_dir / f"{name}.txt"
        path.write_text(value, encoding="utf-8", newline="\n")
        templates[name] = {"path": f"prompts/{name}.txt", "sha256": _sha(path.read_bytes())}

    def backend(name: str, tier: str) -> dict:
        command = [
            sys.executable, str(adapter), "--arm", "{arm}", "--stage", "{stage}",
            "--dispatch", "{dispatch_receipt}", "--prompt", "{prompt}",
            "--result", "{result}", "--worktree", "{worktree}",
            "--model", name, "--account", name + "-account", "--tier", tier,
        ]
        return {
            "model_id": name, "effort": "low", "surface": "fixture",
            "cost_basis": "shadow-estimated", "account": name + "-account",
            "tier": tier, "adapter": {"command": command},
        }

    manifest = {
        "schema": "tier-bench/pilot-backends@2",
        "protocol_commit": "076fd1e3d97c22f7c33933c5dee4ff897d7ba4e6",
        "isolation": {"fresh_session_per_call": True, "instruction_files": False,
                      "auto_memory": False, "conversation_carryover": False},
        "tool_versions": {"fixture-adapter": "1"},
        "acceptance_tool_versions": {"python": sys.version.split()[0]},
        "prompt_templates": templates,
        "backends": {
            "frontier": backend("fixture-frontier", "frontier"),
            "cheap": backend("fixture-cheap", "cheap"),
        },
        "arms": {
            "arm_a": {"mode": "frontier_driver", "driver": {"backend": "frontier", "prompt_template": "driver"},
                      "hands": {"backend": "cheap", "prompt_template": "hands"},
                      "repair": {"backend": "frontier", "prompt_template": "repair", "max_calls": 1},
                      "escalations": [], "driver_trace": {"required": True, "path": "driver_traces.jsonl"}},
            "arm_b": {"mode": "cheap_driver", "driver": {"backend": "cheap", "prompt_template": "driver"},
                      "hands": {"backend": "cheap", "prompt_template": "hands"},
                      "repair": {"backend": "cheap", "prompt_template": "repair", "max_calls": 1},
                      "escalations": []},
            "arm_c": {"mode": "operator_routed", "hands": {"backend": "cheap", "prompt_template": "hands"},
                      "repair": {"backend": "cheap", "prompt_template": "repair", "max_calls": 1},
                      "escalations": [], "question_route": {"question_template": "question",
                                                              "resume_prompt_template": "resume", "max_questions": 2}},
        },
    }
    manifest_path = evidence / "pilot_backends.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    _commit(evidence, "fixture control")
    return target, evidence, manifest_path, base


def _acceptance() -> str:
    return f'"{sys.executable}" check.py'


def test_arm_a_repair_preserves_one_lineage_and_fresh_calls(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "arm-a"
    receipt = start_fixture_pilot_arm(
        repo=target, evidence_repo=evidence, composition_manifest=manifest,
        task_id="bridge-a", task_tier="T3", arm="arm_a",
        task="FAIL_FIRST then repair", files=["target.txt"],
        acceptance_command=_acceptance(), base_commit=base, output_dir=out,
    )
    assert receipt["schema"] == "tier-bench/tier-pilot-fixture-bridge-receipt@1"
    assert receipt["execution_mode"] == "fixture"
    assert receipt["executor_identity"] == "tier-bench/builtin-subprocess-fixture@1"
    assert receipt["status"] == "COMPLETE"
    assert receipt["arm_worktree_removed"] is True
    assert receipt["scientific_verdict_minted"] is False
    composition = load_pilot_composition(manifest)
    state = read_state(composition, out / "state.jsonl")
    assert [call["stage"] for call in state["calls"]] == ["driver_plan", "hands", "repair"]
    assert [item["passed"] for item in state["acceptance_attempts"]] == [False, True]
    assert "target mismatch: expected correct" in state["acceptance_attempts"][0]["report"]
    assert len(state["driver_traces"]) == 1
    assert len({call["session_id"] for call in state["calls"]}) == 3
    assert state["state_sequence"] == 5
    for call_dir in sorted((out / "calls").iterdir()):
        custody = json.loads((call_dir / "custody.json").read_text())
        assert custody["packet_removed"] is True
        assert custody["arm_worktree_preserved"] is True
        provider = json.loads((call_dir / "provider-result.json").read_text())
        assert provider["artifacts"][0]["name"] == "provider_raw"
        descriptor = json.loads((call_dir / "provider-evidence.json").read_text())
        assert descriptor["schema"] == "tier-bench/tier-pilot-fixture-provider-evidence@1"
        assert descriptor["execution_mode"] == "fixture"
        journal = [json.loads(line) for line in (call_dir / "journal.jsonl").read_text().splitlines()]
        assert [row["event"] for row in journal] == ["PREPARED", "DISPATCH_STARTED", "EVIDENCE_SEALED"]
        assert len(json.loads((call_dir / "dispatch.json").read_text())["call_id"].rsplit("-", 1)[-1]) == 64


def test_arm_c_question_is_strict_and_freehand_resume_is_blocked(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "arm-c"
    paused = start_fixture_pilot_arm(
        repo=target, evidence_repo=evidence, composition_manifest=manifest,
        task_id="bridge-c", task_tier="T3", arm="arm_c",
        task="ASK_OPERATOR then implement", files=["target.txt"],
        acceptance_command=_acceptance(), base_commit=base, output_dir=out,
    )
    assert paused["status"] == "WAITING_OPERATOR"
    assert paused["arm_worktree_removed"] is False
    before = (out / "state.jsonl").read_bytes()
    try:
        answer_and_resume_fixture_pilot_arm(
            out, question_id=paused["active_question_id"], answer="literal",
            intervention_id="freehand-not-authority",
        )
    except BridgeError as exc:
        assert "activation-blocked" in str(exc)
    else:
        raise AssertionError("freehand fixture resume dispatched a provider")
    assert (out / "state.jsonl").read_bytes() == before
    state = read_state(load_pilot_composition(manifest), out / "state.jsonl")
    assert [call["stage"] for call in state["calls"]] == ["hands"]
    envelope = json.loads(state["calls"][0]["output"]["text"])
    assert envelope["category"] == "interpretation"
    assert envelope["question"].count("?") == 1


def test_production_entrypoint_is_activation_blocked(root: Path) -> None:
    try:
        start_pilot_arm(repo=root)
    except BridgeError as exc:
        assert "activation-blocked" in str(exc)
    else:
        raise AssertionError("production bridge ran without activation custody")


def test_failed_fixture_call_is_fail_stopped_and_cannot_redispatch(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "crash"
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-crash", task_tier="T3", arm="arm_b", task="ADAPTER_EXIT",
            files=["target.txt"], acceptance_command=_acceptance(), base_commit=base,
            output_dir=out,
        )
    except BridgeError:
        pass
    else:
        raise AssertionError("ambiguous adapter crash was accepted")
    journal = [json.loads(line) for line in next((out / "calls").iterdir()).joinpath("journal.jsonl").read_text().splitlines()]
    assert [row["event"] for row in journal] == ["PREPARED", "DISPATCH_STARTED"]
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-crash", task_tier="T3", arm="arm_b", task="ADAPTER_EXIT",
            files=["target.txt"], acceptance_command=_acceptance(), base_commit=base,
            output_dir=out,
        )
    except BridgeError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("ambiguous call was redispatched")


def test_dirty_call_burns_fixed_session_before_scope_refusal(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    dirty_out = evidence / "runs" / "dirty"
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-dirty", task_tier="T3", arm="arm_b",
            task="FIXED_SESSION DIRTY_SCOPE", files=["target.txt"],
            acceptance_command=_acceptance(), base_commit=base, output_dir=dirty_out,
        )
    except BridgeError as exc:
        assert "outside the frozen scope" in str(exc)
    else:
        raise AssertionError("dirty fixture call was accepted")
    custody = json.loads(
        next((dirty_out / "calls").iterdir()).joinpath("custody.json").read_text()
    )
    assert custody["session_registered"] is True

    clean_out = evidence / "runs" / "clean"
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-clean", task_tier="T3", arm="arm_b",
            task="FIXED_SESSION", files=["target.txt"],
            acceptance_command=_acceptance(), base_commit=base, output_dir=clean_out,
        )
    except BridgeError as exc:
        assert "reused a session_id" in str(exc)
    else:
        raise AssertionError("session from dirty call was reused")


def test_ignored_scoped_output_cannot_create_unsealed_pass(root: Path) -> None:
    target, evidence, manifest, _, = _make_repos(root)
    (target / ".gitignore").write_text("data/cache.txt\n", encoding="utf-8")
    (target / "data").mkdir()
    (target / "data" / "seed.txt").write_text("seed\n", encoding="utf-8")
    (target / "check.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(Path('data/cache.txt').read_text() != 'acceptance-secret\\n')\n",
        encoding="utf-8",
    )
    base = _commit(target, "ignored acceptance fixture")
    out = evidence / "runs" / "ignored"
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-ignored", task_tier="T3", arm="arm_b",
            task="CREATE_IGNORED", files=["data/"],
            acceptance_command=_acceptance(), base_commit=base, output_dir=out,
        )
    except BridgeError as exc:
        assert "ignored files in pilot scope" in str(exc)
    else:
        raise AssertionError("acceptance passed through an unsealed ignored file")
    assert not list((out / "calls").rglob("acceptance.json"))


def test_linked_worktree_cannot_be_evidence_repository(root: Path) -> None:
    target, _, _, base = _make_repos(root)
    linked = root / "linked-evidence"
    _git(target, "worktree", "add", "--detach", str(linked), base)
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=linked,
            composition_manifest=linked / "nonexistent.json",
            task_id="bridge-linked", task_tier="T3", arm="arm_b", task="none",
            files=["target.txt"], acceptance_command=_acceptance(), base_commit=base,
            output_dir=linked / "runs" / "linked",
        )
    except BridgeError as exc:
        assert "must be separate" in str(exc)
    else:
        raise AssertionError("linked worktree shared one common Git custody store")


def test_bad_question_and_prior_evidence_tamper_fail_closed(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    bad_question = evidence / "runs" / "bad-question"
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-bad-question", task_tier="T3", arm="arm_c",
            task="BAD_QUESTION", files=["target.txt"],
            acceptance_command=_acceptance(), base_commit=base, output_dir=bad_question,
        )
    except BridgeError as exc:
        assert "strict JSON envelope" in str(exc)
    else:
        raise AssertionError("unbounded freehand operator question was accepted")

    tamper = evidence / "runs" / "tamper"
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-tamper", task_tier="T3", arm="arm_a",
            task="TAMPER_PRIOR", files=["target.txt"],
            acceptance_command=_acceptance(), base_commit=base, output_dir=tamper,
        )
    except BridgeError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("terminal cleanup accepted tampered prior evidence")


def main() -> int:
    tests = [
        test_arm_a_repair_preserves_one_lineage_and_fresh_calls,
        test_arm_c_question_is_strict_and_freehand_resume_is_blocked,
        test_production_entrypoint_is_activation_blocked,
        test_failed_fixture_call_is_fail_stopped_and_cannot_redispatch,
        test_dirty_call_burns_fixed_session_before_scope_refusal,
        test_ignored_scoped_output_cannot_create_unsealed_pass,
        test_linked_worktree_cannot_be_evidence_repository,
        test_bad_question_and_prior_evidence_tamper_fail_closed,
    ]
    with tempfile.TemporaryDirectory(prefix="tier-pilot-bridge-") as temporary:
        parent = Path(temporary)
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
    print(f"OK — {len(tests)}/{len(tests)} pilot-bridge tests passed; zero model calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
