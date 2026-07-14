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
    decline_pilot_arm,
    recover_fixture_pilot_arm,
    start_fixture_pilot_arm,
    start_pilot_arm,
)
import tier_runner.pilot_bridge as pilot_bridge
from tier_runner.pilot_composition import read_state
from tier_runner.events import start as start_intervention, stop as stop_intervention
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
                                                              "resume_prompt_template": "resume", "max_questions": 1}},
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
    assert receipt["schema"] == "tier-bench/tier-pilot-fixture-bridge-receipt@2"
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


def test_arm_c_resume_requires_and_derives_one_closed_global_interval(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "arm-c"
    script = [
        _response(
            "arm-c-question", outcome="question",
            text=json.dumps({
                "schema": "tier-bench/tier-pilot-operator-question@1",
                "category": "interpretation",
                "question": "Which fixture policy applies?",
            }, sort_keys=True, separators=(",", ":")),
        ),
        _response(
            "arm-c-resume", text="candidate emitted",
            changes={"target.txt": "correct\n"},
        ),
    ]
    paused = start_fixture_pilot_arm(
        repo=target, evidence_repo=evidence, composition_manifest=manifest,
        task_id="bridge-c", task_tier="T3", arm="arm_c",
        task="ASK_OPERATOR then implement", files=["target.txt"],
        acceptance_command=_acceptance(), base_commit=base, output_dir=out,
        fixture_script=script,
    )
    assert paused["status"] == "WAITING_OPERATOR"
    assert paused["arm_worktree_removed"] is False
    before = (out / "state.jsonl").read_bytes()
    intervention_log = evidence / "pilot" / "interventions.jsonl"
    try:
        answer_and_resume_fixture_pilot_arm(
            out, question_id=paused["active_question_id"], answer="literal",
            intervention_log=intervention_log, fixture_script=script,
        )
    except BridgeError as exc:
        assert "exactly one globally closed clarification interval" in str(exc)
    else:
        raise AssertionError("Arm-C resumed without globally timed operator authority")
    assert (out / "state.jsonl").read_bytes() == before
    iid = start_intervention(
        intervention_log, "bridge-c", "arm_c", "clarification",
        paused["active_question_id"],
    )
    stop_intervention(intervention_log, iid)
    receipt = answer_and_resume_fixture_pilot_arm(
        out, question_id=paused["active_question_id"], answer="literal",
        intervention_log=intervention_log, fixture_script=script,
    )
    assert receipt["status"] == "COMPLETE"
    assert len(receipt["question_receipts"]) == 1
    state = read_state(load_pilot_composition(manifest), out / "state.jsonl")
    assert [call["stage"] for call in state["calls"]] == ["hands", "hands_resume"]
    assert state["question_receipts"][0]["intervention_id"] == iid
    assert state["questions"][0]["answer"] == "literal"
    stop_row = json.loads(intervention_log.read_text().splitlines()[-1])
    assert state["question_receipts"][0]["answered_at"] == stop_row["ts"]
    envelope = json.loads(state["calls"][0]["output"]["text"])
    assert envelope["category"] == "interpretation"
    assert envelope["question"].count("?") == 1


def test_arm_c_decline_is_one_terminal_sealed_transition(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "arm-c-decline"
    script = [_response(
        "arm-c-decline-question", outcome="question",
        text=json.dumps({
            "schema": "tier-bench/tier-pilot-operator-question@1",
            "category": "authorization",
            "question": "May this fixture proceed?",
        }, sort_keys=True, separators=(",", ":")),
    )]
    paused = start_fixture_pilot_arm(
        repo=target, evidence_repo=evidence, composition_manifest=manifest,
        task_id="bridge-c-decline", task_tier="T3", arm="arm_c",
        task="ASK_OPERATOR", files=["target.txt"],
        acceptance_command=_acceptance(), base_commit=base, output_dir=out,
        fixture_script=script,
    )
    intervention_log = evidence / "pilot" / "interventions.jsonl"
    iid = start_intervention(
        intervention_log, "bridge-c-decline", "arm_c", "clarification",
        paused["active_question_id"],
    )
    stop_intervention(intervention_log, iid)
    receipt = decline_pilot_arm(
        out, question_id=paused["active_question_id"], reason="operator refused",
        intervention_log=intervention_log, fixture_script=script,
    )
    assert receipt["status"] == "FAILED"
    assert receipt["arm_worktree_removed"] is True
    state = read_state(load_pilot_composition(manifest), out / "state.jsonl")
    assert state["state_sequence"] == 2
    assert state["questions"][0]["declined"] is True
    assert len(state["question_receipts"]) == 1


def test_production_entrypoint_is_activation_blocked(root: Path) -> None:
    try:
        start_pilot_arm(repo=root)
    except BridgeError as exc:
        assert "activation-blocked" in str(exc)
    else:
        raise AssertionError("production bridge ran without activation custody")


def test_evidence_seal_is_written_only_after_call_custody(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "seal-order"
    original = pilot_bridge._append_journal
    observed = False

    def assert_custody_before_seal(path: Path, event: str, call_id: str) -> None:
        nonlocal observed
        if event == "EVIDENCE_SEALED":
            custody = json.loads((path.parent / "custody.json").read_text())
            assert custody["call_id"] == call_id
            assert custody["session_registered"] is True
            assert custody["packet_removed"] is True
            assert custody["error"] is None
            observed = True
        original(path, event, call_id)

    pilot_bridge._append_journal = assert_custody_before_seal
    try:
        receipt = start_fixture_pilot_arm(
            repo=target, evidence_repo=evidence, composition_manifest=manifest,
            task_id="bridge-seal-order", task_tier="T3", arm="arm_c",
            task="IMPLEMENT", files=["target.txt"],
            acceptance_command=_acceptance(), base_commit=base, output_dir=out,
            fixture_script=[_response(
                "seal-order-session", text="candidate emitted",
                changes={"target.txt": "correct\n"},
            )],
        )
    finally:
        pilot_bridge._append_journal = original
    assert observed is True
    assert receipt["status"] == "COMPLETE"


def test_pre_dispatch_crash_archives_exact_bytes_and_retries_once(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "pre-dispatch-crash"
    script = [_response(
        "pre-dispatch-session", text="candidate emitted",
        changes={"target.txt": "correct\n"},
    )]
    original = pilot_bridge._append_journal
    tripped = False

    def stop_before_dispatch(path: Path, event: str, call_id: str) -> None:
        nonlocal tripped
        if event == "DISPATCH_STARTED" and not tripped:
            tripped = True
            raise OSError("synthetic crash before dispatch")
        original(path, event, call_id)

    pilot_bridge._append_journal = stop_before_dispatch
    try:
        try:
            start_fixture_pilot_arm(
                repo=target, evidence_repo=evidence, composition_manifest=manifest,
                task_id="bridge-pre-dispatch", task_tier="T3", arm="arm_c",
                task="IMPLEMENT", files=["target.txt"],
                acceptance_command=_acceptance(), base_commit=base, output_dir=out,
                fixture_script=script,
            )
        except BridgeError as exc:
            assert "synthetic crash before dispatch" in str(exc)
        else:
            raise AssertionError("synthetic pre-dispatch crash did not stop the arm")
    finally:
        pilot_bridge._append_journal = original
    session = json.loads((out / "bridge-session.json").read_text())
    dead_pid = 999999
    while pilot_bridge._pid_alive(dead_pid):
        dead_pid += 1
    (out / "arm.lock").write_bytes(pilot_bridge.canonical_json({
        "schema": pilot_bridge.DRIVE_LOCK_SCHEMA,
        "bridge_id": session["bridge_id"],
        "pid": dead_pid,
        "created_at": "2026-01-01T00:00:00Z",
    }))
    original_ensure = pilot_bridge._ensure_recovery_event
    recovery_tripped = False

    def stop_after_recovery_intent(
        session_dir: Path, action: str, call_directory: str, evidence_sha256: str
    ):
        nonlocal recovery_tripped
        row = original_ensure(session_dir, action, call_directory, evidence_sha256)
        if action == "PRE_DISPATCH_ARCHIVED" and not recovery_tripped:
            recovery_tripped = True
            raise OSError("synthetic crash after recovery intent")
        return row

    pilot_bridge._ensure_recovery_event = stop_after_recovery_intent
    try:
        try:
            recover_fixture_pilot_arm(out, fixture_script=script)
        except OSError as exc:
            assert "synthetic crash after recovery intent" in str(exc)
        else:
            raise AssertionError("recovery write-ahead crash did not stop recovery")
    finally:
        pilot_bridge._ensure_recovery_event = original_ensure
    assert next((out / "calls").iterdir()).name == "01-hands"
    receipt = recover_fixture_pilot_arm(out, fixture_script=script)
    assert receipt["status"] == "COMPLETE"
    archive = next((out / "recovered").iterdir())
    assert archive.name.startswith("pre-dispatch-01-hands")
    recovery = [json.loads(line) for line in (out / "recovery.jsonl").read_text().splitlines()]
    assert [row["action"] for row in recovery] == [
        "STALE_LOCK_CLEARED", "PRE_DISPATCH_ARCHIVED",
    ]
    registry = evidence / ".git" / "tier-session-registry.jsonl"
    assert len(registry.read_text().splitlines()) == 1
    repeated = recover_fixture_pilot_arm(out, fixture_script=script)
    assert repeated["state_sha256"] == receipt["state_sha256"]
    assert len(repeated["calls"]) == 1


def test_sealed_call_replays_state_without_provider_redispatch(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "sealed-state-crash"
    script = [_response(
        "sealed-only-once", text="candidate emitted",
        changes={"target.txt": "correct\n"},
    )]
    original = pilot_bridge._append_state
    tripped = False

    def stop_before_state(path: Path, composition, state):
        nonlocal tripped
        if state["state_sequence"] > 0 and not tripped:
            tripped = True
            raise OSError("synthetic crash after evidence seal")
        return original(path, composition, state)

    pilot_bridge._append_state = stop_before_state
    try:
        try:
            start_fixture_pilot_arm(
                repo=target, evidence_repo=evidence, composition_manifest=manifest,
                task_id="bridge-sealed-replay", task_tier="T3", arm="arm_c",
                task="IMPLEMENT", files=["target.txt"],
                acceptance_command=_acceptance(), base_commit=base, output_dir=out,
                fixture_script=script,
            )
        except OSError as exc:
            assert "synthetic crash after evidence seal" in str(exc)
        else:
            raise AssertionError("synthetic sealed-state crash did not stop the arm")
    finally:
        pilot_bridge._append_state = original
    recovery_tripped = False

    def stop_after_replay_intent(path: Path, composition, state):
        nonlocal recovery_tripped
        if state["state_sequence"] > 0 and not recovery_tripped:
            recovery_tripped = True
            raise OSError("synthetic crash after replay intent")
        return original(path, composition, state)

    pilot_bridge._append_state = stop_after_replay_intent
    try:
        try:
            recover_fixture_pilot_arm(out, fixture_script=script)
        except OSError as exc:
            assert "synthetic crash after replay intent" in str(exc)
        else:
            raise AssertionError("replay write-ahead crash did not stop recovery")
    finally:
        pilot_bridge._append_state = original
    receipt = recover_fixture_pilot_arm(out, fixture_script=script)
    assert receipt["status"] == "COMPLETE"
    assert len(receipt["calls"]) == 1
    recovery = [json.loads(line) for line in (out / "recovery.jsonl").read_text().splitlines()]
    assert [row["action"] for row in recovery] == ["SEALED_STATE_REPLAYED"]
    registry = evidence / ".git" / "tier-session-registry.jsonl"
    assert len(registry.read_text().splitlines()) == 1


def test_recovery_never_clears_a_live_drive_lock(root: Path) -> None:
    target, evidence, manifest, base = _make_repos(root)
    out = evidence / "runs" / "live-lock"
    script = [_response(
        "live-lock-question", outcome="question",
        text=json.dumps({
            "schema": "tier-bench/tier-pilot-operator-question@1",
            "category": "policy",
            "question": "Which policy applies?",
        }, sort_keys=True, separators=(",", ":")),
    )]
    start_fixture_pilot_arm(
        repo=target, evidence_repo=evidence, composition_manifest=manifest,
        task_id="bridge-live-lock", task_tier="T3", arm="arm_c", task="pause",
        files=["target.txt"], acceptance_command=_acceptance(), base_commit=base,
        output_dir=out, fixture_script=script,
    )
    session = json.loads((out / "bridge-session.json").read_text())
    lock = out / "arm.lock"
    lock.write_bytes(pilot_bridge.canonical_json({
        "schema": pilot_bridge.DRIVE_LOCK_SCHEMA,
        "bridge_id": session["bridge_id"],
        "pid": pilot_bridge.os.getpid(),
        "created_at": "2026-01-01T00:00:00Z",
    }))
    before = (out / "state.jsonl").read_bytes()
    try:
        recover_fixture_pilot_arm(out, fixture_script=script)
    except BridgeError as exc:
        assert "belongs to a live process" in str(exc)
    else:
        raise AssertionError("recovery cleared a live coordinator lock")
    assert lock.exists()
    assert (out / "state.jsonl").read_bytes() == before
    assert not (out / "recovery.jsonl").exists()
    lock.unlink()


def test_ambiguous_dispatch_is_permanently_aborted_and_never_redispatched(root: Path) -> None:
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
    script = [_response("fault", fault="before_result")]
    abort = recover_fixture_pilot_arm(out, fixture_script=script)
    assert abort["reason"] == "AMBIGUOUS_DISPATCH"
    assert abort["redispatch_permitted"] is False
    assert abort["arm_worktree_removed"] is True
    assert recover_fixture_pilot_arm(out, fixture_script=script) == abort
    recovery = [json.loads(line) for line in (out / "recovery.jsonl").read_text().splitlines()]
    assert [row["action"] for row in recovery] == [
        "AMBIGUOUS_DISPATCH_FAIL_STOPPED"
    ]


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
        test_arm_c_resume_requires_and_derives_one_closed_global_interval,
        test_arm_c_decline_is_one_terminal_sealed_transition,
        test_production_entrypoint_is_activation_blocked,
        test_evidence_seal_is_written_only_after_call_custody,
        test_pre_dispatch_crash_archives_exact_bytes_and_retries_once,
        test_sealed_call_replays_state_without_provider_redispatch,
        test_recovery_never_clears_a_live_drive_lock,
        test_ambiguous_dispatch_is_permanently_aborted_and_never_redispatched,
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
