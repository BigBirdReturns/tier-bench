from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from test_tier_pilot_bridge import _acceptance, _make_repos  # noqa: E402
from tier_runner.adapters.claude_code import REQUIRED_CLAUDE_FLAGS  # noqa: E402
from tier_runner.pilot_activation import (  # noqa: E402
    ADAPTER_IDENTITY,
    ADAPTER_VERSION,
    DEFAULT_REF,
    EXECUTOR_IDENTITY,
    PRODUCTION_SCHEMA_PATHS,
    PROVIDER_RESULT_SCHEMA,
    SCHEMA,
    SOURCE_PATHS,
    ActivationError,
    _package_initializer_paths,
    load_official_activation,
)
import tier_runner.pilot_activation as pilot_activation  # noqa: E402
from tier_runner.pilot_adapter import PilotAdapterError, run_activated_adapter  # noqa: E402
from tier_runner.pilot import PROTOCOL_V13_COMMIT, RESIDUAL_ORDERS, derive_schedule  # noqa: E402
from tier_runner.pilot_bridge import recover_pilot_arm, start_pilot_arm  # noqa: E402
import tier_runner.pilot_bridge as pilot_bridge  # noqa: E402


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=False
    )
    if result.returncode:
        raise AssertionError(result.stderr.decode(errors="replace"))
    return result.stdout


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(
        root, "-c", "user.name=Activation Fixture", "-c",
        "user.email=activation@example.invalid", "commit", "-m", message,
    )
    return _git(root, "rev-parse", "HEAD")


def _copy(root: Path, relative: str) -> None:
    source = REPO / relative
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _committed_artifact(root: Path, commit: str, relative: str) -> dict[str, str]:
    return {
        "path": relative,
        "sha256": _sha(_git_bytes(root, "show", f"{commit}:{relative}")),
    }


def _activation_fixture(root: Path):
    _, evidence, manifest_path, _ = _make_repos(root)
    manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_value["arms"]["arm_a"]["escalations"] = [
        {"backend": "frontier", "prompt_template": "repair"},
        {"backend": "cheap", "prompt_template": "hands"},
    ]
    manifest_path.write_bytes(_canonical(manifest_value))
    remote = root / "control-remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True, capture_output=True,
    )
    _git(evidence, "remote", "add", "origin", str(remote.resolve()))
    pilot_activation.CONTROL_REMOTE_URL = _git(evidence, "remote", "get-url", "origin")

    for path in (*SOURCE_PATHS.values(), *PRODUCTION_SCHEMA_PATHS.values()):
        _copy(evidence, path)
    artifact_commit = _commit(evidence, "activation source and schema fixtures")
    sources = {
        name: _committed_artifact(evidence, artifact_commit, path)
        for name, path in SOURCE_PATHS.items()
    }
    schemas = {
        name: _committed_artifact(evidence, artifact_commit, path)
        for name, path in PRODUCTION_SCHEMA_PATHS.items()
    }
    manifest_raw = _git_bytes(evidence, "show", f"{artifact_commit}:pilot_backends.json")
    manifest = json.loads(manifest_raw)
    backend_hashes = {
        name: _sha(_canonical(value)) for name, value in manifest["backends"].items()
    }
    prompts = [
        {
            "name": name,
            "path": f"prompts/{name}.txt",
            "sha256": value["sha256"],
        }
        for name, value in sorted(manifest["prompt_templates"].items())
    ]
    help_raw = b"\n".join(
        flag.encode("ascii") for flag in sorted(REQUIRED_CLAUDE_FLAGS)
    )
    activation = {
        "schema": SCHEMA,
        "status": "OPERATOR_RATIFIED",
        "protocol_commit": manifest["protocol_commit"],
        "executor_identity": EXECUTOR_IDENTITY,
        "composition_manifest": {
            "path": "pilot_backends.json",
            "sha256": _sha(manifest_raw),
        },
        "backend_entry_sha256s": backend_hashes,
        "prompt_templates": prompts,
        "sources": sources,
        "adapter": {
            "identity": ADAPTER_IDENTITY,
            "version": ADAPTER_VERSION,
            "binary": "claude",
            "cli_version": "2.1.fixture",
            "help_sha256": _sha(help_raw),
            "provider_result_schema": PROVIDER_RESULT_SCHEMA,
        },
        "production_schemas": schemas,
        "control_repository": {
            "remote_url": _git(evidence, "remote", "get-url", "origin"),
            "default_ref": DEFAULT_REF,
            "evidence_root": "pilot-evidence",
        },
        "guards": {
            "production_entrypoint_requires_activation": True,
            "canary_requires_separate_operator_authorization": True,
            "pilot_task_disclosure_authorized": False,
            "scientific_verdict_minted": False,
        },
    }
    activation_path = evidence / "pilot_activation.json"
    activation_path.write_bytes(_canonical(activation))
    commit = _commit(evidence, "operator-ratified activation fixture")
    _git(evidence, "push", "-u", "origin", "main")
    loaded = load_official_activation(evidence, commit, "pilot_activation.json")
    return evidence, commit, loaded, help_raw


def test_official_activation_opens_exact_remote_git_objects(root: Path) -> None:
    evidence, commit, loaded, _ = _activation_fixture(root)
    assert loaded.commit == commit
    assert loaded.composition.sha256 == loaded.document["composition_manifest"]["sha256"]
    assert loaded.document["guards"]["pilot_task_disclosure_authorized"] is False

    activation = json.loads((evidence / "pilot_activation.json").read_text())
    activation["backend_entry_sha256s"]["cheap"] = "0" * 64
    (evidence / "pilot_activation.json").write_bytes(_canonical(activation))
    unlanded = _commit(evidence, "unlanded activation drift")
    _git(evidence, "update-ref", "refs/remotes/origin/main", unlanded)
    try:
        load_official_activation(evidence, unlanded, "pilot_activation.json")
    except ActivationError as exc:
        assert "remote default branch" in str(exc)
    else:
        raise AssertionError("an unlanded activation commit was accepted")
    _git(evidence, "push", "origin", "main")
    try:
        load_official_activation(evidence, unlanded, "pilot_activation.json")
    except ActivationError as exc:
        assert "backend entry 'cheap' drifted" in str(exc)
    else:
        raise AssertionError("a landed activation with a false backend binding was accepted")


def test_transitive_source_drift_is_not_self_authorizing(root: Path) -> None:
    evidence, _, _, _ = _activation_fixture(root)
    relative = SOURCE_PATHS["claude_adapter"]
    path = evidence / relative
    path.write_text(path.read_text(encoding="utf-8") + "\n# locally drifted argv authority\n", encoding="utf-8", newline="\n")
    source_commit = _commit(evidence, "drift transitive command authority")
    activation = json.loads((evidence / "pilot_activation.json").read_text())
    activation["sources"]["claude_adapter"] = _committed_artifact(
        evidence, source_commit, relative
    )
    (evidence / "pilot_activation.json").write_bytes(_canonical(activation))
    drift_commit = _commit(evidence, "self-consistent drifted activation")
    _git(evidence, "push", "origin", "main")
    try:
        load_official_activation(evidence, drift_commit, "pilot_activation.json")
    except ActivationError as exc:
        assert "running claude_adapter bytes differ" in str(exc)
    else:
        raise AssertionError("a self-consistent activation hid transitive source drift")


def test_package_initializer_drift_is_not_self_authorizing(root: Path) -> None:
    for source_name in ("runner_package_runtime", "adapters_package_runtime"):
        case = root / source_name
        case.mkdir()
        evidence, _, _, _ = _activation_fixture(case)
        relative = SOURCE_PATHS[source_name]
        path = evidence / relative
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n# locally drifted package import authority\n",
            encoding="utf-8",
            newline="\n",
        )
        source_commit = _commit(evidence, f"drift {source_name}")
        activation = json.loads((evidence / "pilot_activation.json").read_text())
        activation["sources"][source_name] = _committed_artifact(
            evidence, source_commit, relative
        )
        (evidence / "pilot_activation.json").write_bytes(_canonical(activation))
        drift_commit = _commit(evidence, f"self-consistent {source_name} drift")
        _git(evidence, "push", "origin", "main")
        try:
            load_official_activation(evidence, drift_commit, "pilot_activation.json")
        except ActivationError as exc:
            assert f"running {source_name} bytes differ" in str(exc)
        else:
            raise AssertionError(
                f"a self-consistent activation hid {source_name} drift"
            )


def test_activated_adapter_ignores_manifest_argv_and_preserves_bytes(root: Path) -> None:
    _, _, activation, help_raw = _activation_fixture(root)
    call_dir = root / "call"
    call_dir.mkdir()
    prompt = b"exact rendered prompt\r\n"
    prompt_path = call_dir / "prompt.txt"
    prompt_path.write_bytes(prompt)
    template = activation.composition.templates["hands"]
    dispatch = {
        "schema": "tier-bench/tier-pilot-dispatch-receipt@1",
        "call_id": "call-1",
        "task_id": "synthetic-canary",
        "arm": "arm_b",
        "stage": "hands",
        "attempt": 1,
        "backend": "cheap",
        "prompt_template": {"name": "hands", "sha256": template.sha256},
        "prompt_sha256": _sha(prompt),
        "base_commit": "1" * 40,
        "task_sha256": "2" * 64,
        "files": ["target.txt"],
        "acceptance_sha256": "3" * 64,
        "composition_manifest_sha256": activation.composition.sha256,
    }
    dispatch_path = call_dir / "dispatch.json"
    dispatch_path.write_bytes(_canonical(dispatch))
    provider_output = {"outcome": "completed", "text": "candidate emitted"}
    provider_raw = _canonical({
        "result": json.dumps(provider_output, sort_keys=True, separators=(",", ":")),
        "session_id": "00000000-0000-4000-8000-000000000001",
        "modelUsage": {"fixture-cheap": {}},
        "usage": {
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 4,
        },
        "total_cost_usd": 0,
    })
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, b"2.1.fixture\n", b"")
        if argv[1:] == ["--help"]:
            return subprocess.CompletedProcess(argv, 0, help_raw, b"")
        assert kwargs["input"] == prompt
        assert kwargs["text"] is False
        dispatch_path.write_bytes(b"mutated during provider call")
        return subprocess.CompletedProcess(argv, 0, provider_raw, b"provider stderr\r\n")

    result_path = call_dir / "provider-result.json"
    run_activated_adapter(
        activation,
        backend_name="cheap",
        dispatch_path=dispatch_path,
        prompt_path=prompt_path,
        result_path=result_path,
        worktree=root,
        runner=runner,
        environment={"PATH": "kept", "CLAUDE_CODE_SESSION_ID": "strip-me"},
    )
    assert calls[-1][0] == "claude"
    assert "--forbidden-in-fixture-mode" not in calls[-1]
    assert (call_dir / "provider.raw.bin").read_bytes() == provider_raw
    assert (call_dir / "provider.stderr.bin").read_bytes() == b"provider stderr\r\n"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["pilot_output"] == provider_output
    assert result["calls"][0]["extra"]["rendered_prompt_sha256"] == _sha(prompt)
    assert result["calls"][0]["extra"]["dispatch_receipt_sha256"] == _sha(
        _canonical(dispatch)
    )
    assert result["calls"][0]["extra"]["tool_versions"] == activation.composition.tool_versions
    assert result["artifacts"][0]["sha256"] == _sha(provider_raw)


def test_escalation_attempt_binds_one_ladder_position(root: Path) -> None:
    _, _, activation, _ = _activation_fixture(root)
    call_dir = root / "escalation"
    call_dir.mkdir()
    prompt = b"wrong escalation rung\n"
    prompt_path = call_dir / "prompt.txt"
    prompt_path.write_bytes(prompt)
    wrong_template = activation.composition.templates["hands"]
    dispatch = {
        "schema": "tier-bench/tier-pilot-dispatch-receipt@1",
        "call_id": "escalation-1", "task_id": "synthetic-canary",
        "arm": "arm_a", "stage": "escalation", "attempt": 1,
        "backend": "cheap",
        "prompt_template": {"name": "hands", "sha256": wrong_template.sha256},
        "prompt_sha256": _sha(prompt), "base_commit": "1" * 40,
        "task_sha256": "2" * 64, "files": ["target.txt"],
        "acceptance_sha256": "3" * 64,
        "composition_manifest_sha256": activation.composition.sha256,
    }
    dispatch_path = call_dir / "dispatch.json"
    dispatch_path.write_bytes(_canonical(dispatch))

    def forbidden_runner(*args, **kwargs):
        del args, kwargs
        raise AssertionError("wrong escalation rung reached the provider")

    try:
        run_activated_adapter(
            activation,
            backend_name="cheap",
            dispatch_path=dispatch_path,
            prompt_path=prompt_path,
            result_path=call_dir / "result.json",
            worktree=root,
            runner=forbidden_runner,
        )
    except PilotAdapterError as exc:
        assert "invalid for its arm stage" in str(exc)
    else:
        raise AssertionError("adapter accepted a later escalation rung at attempt 1")


def test_activation_and_production_schemas_are_distinct(root: Path) -> None:
    del root
    activation_schema = json.loads(
        (REPO / "schemas/tier_pilot_activation.schema.json").read_text(encoding="utf-8")
    )
    assert activation_schema["properties"]["status"]["const"] == "OPERATOR_RATIFIED"
    assert set(activation_schema["properties"]["sources"]["required"]) == set(SOURCE_PATHS)
    assert set(activation_schema["properties"]["production_schemas"]["required"]) == set(
        PRODUCTION_SCHEMA_PATHS
    )
    expected = {
        "provider": "tier-bench/tier-pilot-production-provider-evidence@1",
        "acceptance": "tier-bench/tier-pilot-production-acceptance-evidence@1",
        "bridge": "tier-bench/tier-pilot-production-bridge-receipt@2",
    }
    for name, schema_id in expected.items():
        value = json.loads((REPO / PRODUCTION_SCHEMA_PATHS[name]).read_text(encoding="utf-8"))
        assert value["properties"]["schema"]["const"] == schema_id


def test_production_entrypoint_rederives_activation_plan_and_provider_custody(
    root: Path,
) -> None:
    evidence, commit, activation, _ = _activation_fixture(root)
    target = root / "target"
    base = _git(target, "rev-parse", "HEAD")
    target_remote = root / "target-remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(target_remote)],
        check=True,
        capture_output=True,
    )
    _git(target, "remote", "add", "origin", str(target_remote.resolve()))
    _git(target, "push", "-u", "origin", "main")
    tasks = [
        {
            "task_id": f"prod-{index:02d}",
            "base_commit": base,
            "task": "Write the accepted target value",
            "files": ["target.txt"],
            "acceptance_command": _acceptance(),
            "withheld_audit_sha256": "d" * 64,
        }
        for index in range(10)
    ]
    plan = {
        "schema": "tier-bench/tier-pilot-plan@1",
        "pilot_id": "production-entry-fixture",
        "protocol_commit": PROTOCOL_V13_COMMIT,
        "backend_manifest_sha256": activation.composition.sha256,
        "target_remote": str(target_remote.resolve()),
        "default_branch": "main",
        "audit_normalization_profile": {
            "path": "pilot/audit-profile.json", "sha256": "e" * 64,
        },
        "real_billed_tolerance_fraction": 0.01,
        "intervention_log_path": "pilot/interventions.jsonl",
        "follow_up_days": 14,
        "audit_label_seed_commitment_sha256": "f" * 64,
        "residual_order_enumeration": list(RESIDUAL_ORDERS),
        "tasks": tasks,
        "schedule": derive_schedule(tasks, PROTOCOL_V13_COMMIT),
    }
    plan_path = evidence / "pilot-plan.json"
    plan_path.write_bytes(_canonical(plan))
    authorization_path = evidence / "pilot" / "operator-authorization.json"
    authorization_path.parent.mkdir(parents=True, exist_ok=True)
    authorization_path.write_bytes(_canonical({
        "schema": "tier-bench/tier-pilot-authorization@1",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": _sha(_canonical(plan)),
        "backend_manifest_sha256": plan["backend_manifest_sha256"],
        "protocol_commit": plan["protocol_commit"],
        "authority": "operator",
        "authorized": True,
        "ratified_at": "2026-07-14T00:00:00Z",
    }))
    authority_commit = _commit(evidence, "ratify exact production fixture plan")
    _git(evidence, "push", "origin", "main")

    calls = 0

    def fake_adapter(
        loaded,
        *,
        backend_name,
        dispatch_path,
        prompt_path,
        result_path,
        worktree,
    ):
        nonlocal calls
        calls += 1
        assert loaded.commit == authority_commit
        dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
        assert dispatch["schema"] == "tier-bench/tier-pilot-dispatch-receipt@1"
        assert prompt_path.read_bytes()
        if dispatch["stage"] == "hands":
            (worktree / "target.txt").write_text("correct\n", encoding="utf-8")
        output = {
            "outcome": "completed",
            "text": "plan" if dispatch["stage"] == "driver_plan" else "candidate",
        }
        encoded = json.dumps(output, sort_keys=True, separators=(",", ":"))
        raw = _canonical({"result": encoded, "session_id": f"prod-session-{calls}"})
        raw_path = result_path.with_name("provider.raw.bin")
        stderr_path = result_path.with_name("provider.stderr.bin")
        raw_path.write_bytes(raw)
        stderr_path.write_bytes(b"")
        backend = loaded.composition.backends[backend_name]
        call = {
            "ts": "2026-07-14T00:00:00+00:00",
            "account": backend.account,
            "model": backend.model_id,
            "tier": backend.tier,
            "task_id": dispatch["task_id"],
            "phase": dispatch["arm"],
            "outcome": "pass",
            "effort": backend.effort,
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_usd": 0.0,
            "latency_ms": 1.0,
            "trial": dispatch["attempt"],
            "note": f"{backend.cost_basis}; deterministic production fixture",
            "extra": {
                "activation_commit": loaded.commit,
                "activation_sha256": loaded.sha256,
                "backend_manifest_sha256": loaded.composition.sha256,
                "backend_surface": backend.surface,
                "cost_basis": backend.cost_basis,
                "dispatch_receipt_sha256": _sha(dispatch_path.read_bytes()),
                "prompt_template_sha256": dispatch["prompt_template"]["sha256"],
                "rendered_prompt_sha256": _sha(prompt_path.read_bytes()),
                "runtime_model_id": backend.model_id,
                "session_id": f"prod-session-{calls}",
                "telemetry_complete": True,
                "tool_versions": loaded.composition.tool_versions,
                "raw_result_sha256": _sha(raw),
                "stderr_sha256": _sha(b""),
            },
        }
        result_path.write_bytes(_canonical({
            "schema": PROVIDER_RESULT_SCHEMA,
            "calls": [call],
            "pilot_output": output,
            "artifacts": [
                {"name": "provider_raw", "path": raw_path.name, "sha256": _sha(raw)},
                {"name": "provider_stderr", "path": stderr_path.name, "sha256": _sha(b"")},
            ],
        }))
        return 0

    original = pilot_bridge.run_activated_adapter
    pilot_bridge.run_activated_adapter = fake_adapter
    try:
        receipt = start_pilot_arm(
            repo=target,
            evidence_repo=evidence,
            activation_commit=authority_commit,
            activation_path="pilot_activation.json",
            plan_path="pilot-plan.json",
            authorization_path="pilot/operator-authorization.json",
            task_id="prod-00",
            arm="arm_b",
            output_dir=evidence / "runs" / "prod-00-arm-b",
        )
    finally:
        pilot_bridge.run_activated_adapter = original
    assert calls == 2
    assert receipt["schema"] == "tier-bench/tier-pilot-production-bridge-receipt@2"
    assert receipt["activation_commit"] == authority_commit
    assert receipt["activation_sha256"] == activation.sha256
    assert receipt["status"] == "COMPLETE"
    assert receipt["arm_worktree_removed"] is True
    receipt_schema = json.loads(
        (REPO / PRODUCTION_SCHEMA_PATHS["bridge"]).read_text(encoding="utf-8")
    )
    assert set(receipt) == set(receipt_schema["required"])
    assert len(receipt["provider_receipts"]) == 2
    for reference in receipt["provider_receipts"]:
        value = json.loads((evidence / reference["path"]).read_text())
        assert value["activation_commit"] == authority_commit
        assert value["activation_sha256"] == activation.sha256

    crashed = evidence / "runs" / "prod-01-arm-c-recovery"
    original_append = pilot_bridge._append_state
    tripped = False

    def crash_after_seal(path, composition, state):
        nonlocal tripped
        if state["task_id"] == "prod-01" and state["state_sequence"] > 0 and not tripped:
            tripped = True
            raise OSError("synthetic production crash after evidence seal")
        return original_append(path, composition, state)

    pilot_bridge.run_activated_adapter = fake_adapter
    pilot_bridge._append_state = crash_after_seal
    calls_before_recovery = calls
    try:
        try:
            start_pilot_arm(
                repo=target,
                evidence_repo=evidence,
                activation_commit=authority_commit,
                activation_path="pilot_activation.json",
                plan_path="pilot-plan.json",
                authorization_path="pilot/operator-authorization.json",
                task_id="prod-01",
                arm="arm_c",
                output_dir=crashed,
            )
        except OSError as exc:
            assert "synthetic production crash" in str(exc)
        else:
            raise AssertionError("production sealed-state crash did not stop the arm")
    finally:
        pilot_bridge._append_state = original_append
    try:
        recovered = recover_pilot_arm(crashed)
    finally:
        pilot_bridge.run_activated_adapter = original
    assert recovered["status"] == "COMPLETE"
    assert calls == calls_before_recovery + 1
    recovery_rows = [
        json.loads(line) for line in (crashed / "recovery.jsonl").read_text().splitlines()
    ]
    assert [row["action"] for row in recovery_rows] == ["SEALED_STATE_REPLAYED"]
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    for path in SOURCE_PATHS.values():
        assert f"{path} text eol=lf" in attributes
        assert b"\r\n" not in (REPO / path).read_bytes()
    required_initializers = set().union(*(
        _package_initializer_paths(path) for path in SOURCE_PATHS.values()
    ))
    assert required_initializers <= set(SOURCE_PATHS.values())


def main() -> int:
    tests = [
        test_official_activation_opens_exact_remote_git_objects,
        test_transitive_source_drift_is_not_self_authorizing,
        test_package_initializer_drift_is_not_self_authorizing,
        test_activated_adapter_ignores_manifest_argv_and_preserves_bytes,
        test_escalation_attempt_binds_one_ladder_position,
        test_activation_and_production_schemas_are_distinct,
        test_production_entrypoint_rederives_activation_plan_and_provider_custody,
    ]
    with tempfile.TemporaryDirectory(prefix="tier-pilot-activation-") as temporary:
        parent = Path(temporary)
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
    print(f"OK — {len(tests)}/{len(tests)} pilot-activation tests passed; zero model calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
