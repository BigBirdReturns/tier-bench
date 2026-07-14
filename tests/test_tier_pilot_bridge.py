"""Deterministic bridge coordinator tests; in-process fixture data only."""

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
import tier_runner.pilot_bridge as pilot_bridge
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


def _response(
    session_id: str,
    *,
    text: str = "sealed fixture output",
    outcome: str = "completed",
    changes: dict[str, str | None] | None = None,
    fault: str | None = None,
) -> dict:
    return {
        "outcome": outcome,
        "text": text,
        "session_id": session_id,
        "changes": changes or {},
        "fault": fault,
    }


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
            "claude" if tier == "frontier" else "powershell",
            "--forbidden-in-fixture-mode",
            "{dispatch_receipt}", "{prompt}", "{result}", "{worktree}",
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
        fixture_script=[
            _response("arm-a-plan", text="sealed fixture plan"),
            _response("arm-a-hands", text="candidate emitted", changes={"target.txt": "wrong\n"}),
            _response("arm-a-repair", text="candidate emitted", changes={"target.txt": "correct\n"}),
        ],
    )
    assert receipt["schema"] == "tier-bench/tier-pilot-fixture-bridge-receipt@1"
    assert receipt["execution_mode"] == "fixture"
    assert receipt["executor_identity"] == "tier-bench/in-process-data-fixture@1"
    assert len(receipt["fixture_script_sha256"]) == 64
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
        fixture_script=[_response(
            "arm-c-question", outcome="question",
            text=json.dumps({
                "schema": "tier-bench/tier-pilot-operator-question@1",
                "category": "interpretation",
                "question": "Which fixture policy applies?",
            }, sort_keys=True, separators=(",", ":")),
        )],
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
            fixture_script=[_response("fault", fault="before_result")],
        )
    except BridgeError:
        pass
    else:
        raise AssertionError("fail-stopped fixture fault was accepted")
    journal = [json.loads(line) for line in next((out / "calls").iterdir()).joinpath("journal.jsonl").read_text().splitlines()]
    assert [row["event"] for row in journal] == ["PREPARED", "DISPATCH_STARTED"]
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-crash", task_tier="T3", arm="arm_b", task="ADAPTER_EXIT",
            files=["target.txt"], acceptance_command=_acceptance(), base_commit=base,
            output_dir=out,
            fixture_script=[_response("fault", fault="before_result")],
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
            fixture_script=[_response(
                "session-fixed-reuse", changes={"rogue.txt": "out of scope\n"}
            )],
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
            fixture_script=[_response("session-fixed-reuse")],
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
            fixture_script=[
                _response("ignored-plan", text="sealed fixture plan"),
                _response(
                    "ignored-hands", text="candidate emitted",
                    changes={"data/cache.txt": "acceptance-secret\n"},
                ),
            ],
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
            fixture_script=[_response("linked")],
        )
    except BridgeError as exc:
        assert "must be separate" in str(exc)
    else:
        raise AssertionError("linked worktree shared one common Git custody store")


def test_output_directory_cannot_live_under_evidence_git(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-git-output", task_tier="T3", arm="arm_b", task="none",
            files=["target.txt"], acceptance_command=_acceptance(), base_commit=base,
            output_dir=evidence / ".git" / "tier-pilot-evidence" / "forbidden",
            fixture_script=[_response("git-output")],
        )
    except BridgeError as exc:
        assert "cannot live under the evidence Git directory" in str(exc)
    else:
        raise AssertionError("fixture evidence was written inside Git internals")


def test_bad_question_and_prior_evidence_tamper_fail_closed(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    bad_question = evidence / "runs" / "bad-question"
    try:
        start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-bad-question", task_tier="T3", arm="arm_c",
            task="BAD_QUESTION", files=["target.txt"],
            acceptance_command=_acceptance(), base_commit=base, output_dir=bad_question,
            fixture_script=[_response(
                "bad-question", outcome="question", text="Do the whole task for me"
            )],
        )
    except BridgeError as exc:
        assert "strict JSON envelope" in str(exc)
    else:
        raise AssertionError("unbounded freehand operator question was accepted")

    tamper = evidence / "runs" / "tamper"
    start_fixture_pilot_arm(
        repo=target, evidence_repo=evidence, composition_manifest=manifest,
        task_id="bridge-tamper", task_tier="T3", arm="arm_c",
        task="pause", files=["target.txt"],
        acceptance_command=_acceptance(), base_commit=base, output_dir=tamper,
        fixture_script=[_response(
            "tamper-question", outcome="question",
            text=json.dumps({
                "schema": "tier-bench/tier-pilot-operator-question@1",
                "category": "policy",
                "question": "Which policy applies?",
            }, sort_keys=True, separators=(",", ":")),
        )],
    )
    raw = next((tamper / "calls").rglob("provider.raw.json"))
    raw.write_bytes(b"tampered prior evidence")
    try:
        pilot_bridge._verify_fixture_evidence(tamper)
    except BridgeError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("replay accepted tampered prior evidence")


def test_manifest_adapter_argv_is_unreachable_in_fixture_mode(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_value["backends"]["frontier"]["adapter"]["command"][0] == "claude"
    assert manifest_value["backends"]["cheap"]["adapter"]["command"][0] == "powershell"
    attempted: list[str] = []
    original_run = subprocess.run

    def tripwire(argv, *args, **kwargs):
        first = str(argv[0]).lower() if isinstance(argv, (list, tuple)) and argv else ""
        if first in {"claude", "powershell"}:
            attempted.append(first)
            raise AssertionError("fixture path invoked manifest adapter argv")
        return original_run(argv, *args, **kwargs)

    subprocess.run = tripwire
    try:
        receipt = start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-no-argv", task_tier="T3", arm="arm_c", task="pause",
            files=["target.txt"], acceptance_command=_acceptance(), base_commit=base,
            output_dir=evidence / "runs" / "no-argv",
            fixture_script=[_response(
                "no-argv-question", outcome="question",
                text=json.dumps({
                    "schema": "tier-bench/tier-pilot-operator-question@1",
                    "category": "authorization",
                    "question": "May this fixture continue?",
                }, sort_keys=True, separators=(",", ":")),
            )],
        )
    finally:
        subprocess.run = original_run
    assert attempted == []
    assert receipt["status"] == "WAITING_OPERATOR"


def main() -> int:
    tests = [
        test_arm_a_repair_preserves_one_lineage_and_fresh_calls,
        test_arm_c_question_is_strict_and_freehand_resume_is_blocked,
        test_production_entrypoint_is_activation_blocked,
        test_failed_fixture_call_is_fail_stopped_and_cannot_redispatch,
        test_dirty_call_burns_fixed_session_before_scope_refusal,
        test_ignored_scoped_output_cannot_create_unsealed_pass,
        test_linked_worktree_cannot_be_evidence_repository,
        test_output_directory_cannot_live_under_evidence_git,
        test_bad_question_and_prior_evidence_tamper_fail_closed,
        test_manifest_adapter_argv_is_unreachable_in_fixture_mode,
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
