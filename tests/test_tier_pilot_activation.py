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

from test_tier_pilot_bridge import _make_repos  # noqa: E402
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
    load_official_activation,
)
import tier_runner.pilot_activation as pilot_activation  # noqa: E402
from tier_runner.pilot_adapter import run_activated_adapter  # noqa: E402


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
    assert result["artifacts"][0]["sha256"] == _sha(provider_raw)


def test_activation_and_production_schemas_are_distinct(root: Path) -> None:
    del root
    activation_schema = json.loads(
        (REPO / "schemas/tier_pilot_activation.schema.json").read_text(encoding="utf-8")
    )
    assert activation_schema["properties"]["status"]["const"] == "OPERATOR_RATIFIED"
    expected = {
        "provider": "tier-bench/tier-pilot-production-provider-evidence@1",
        "acceptance": "tier-bench/tier-pilot-production-acceptance-evidence@1",
        "bridge": "tier-bench/tier-pilot-production-bridge-receipt@1",
    }
    for name, schema_id in expected.items():
        value = json.loads((REPO / PRODUCTION_SCHEMA_PATHS[name]).read_text(encoding="utf-8"))
        assert value["properties"]["schema"]["const"] == schema_id


def main() -> int:
    tests = [
        test_official_activation_opens_exact_remote_git_objects,
        test_activated_adapter_ignores_manifest_argv_and_preserves_bytes,
        test_activation_and_production_schemas_are_distinct,
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
