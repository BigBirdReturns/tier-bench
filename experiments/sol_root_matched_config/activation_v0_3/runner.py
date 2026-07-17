"""Fail-closed live runner for the prospectively authorized activation freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from build_activation_v0_3 import ActivationError, PREFIX, canonical, load, verify


HERE = Path(__file__).resolve().parent
EXPECTED_CLI_VERSION = "codex-cli 0.144.5"
EXPECTED_CLI_SHA256 = "efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a"
EXPECTED_EXECUTOR_BYTES = b"SOL_ROOT_CANARY_V0_3\n"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ActivationError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_sha256(freeze: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(freeze)).hexdigest()


def call_directory_name(sequence: int) -> str:
    """Keep Windows evidence paths below MAX_PATH; cell identity lives in cell.json."""
    require(isinstance(sequence, int) and 0 <= sequence <= 58, "invalid call sequence")
    return f"c{sequence:02d}"


def validate_authorization(freeze: dict[str, Any], authorization: dict[str, Any]) -> str:
    digest = freeze_sha256(freeze)
    require(freeze.get("status") == "awaiting_prospective_operator_ratification", "freeze is not the ratifiable candidate")
    require(authorization.get("schema") == f"{PREFIX}/operator-authorization@0.3", "wrong authorization schema")
    require(authorization.get("freeze_sha256") == digest, "authorization does not bind the exact freeze")
    require(authorization.get("authorized_call_ceiling") == 59, "authorization must cap calls at 59")
    require(authorization.get("no_retries") is True, "authorization must forbid retries")
    require(authorization.get("prospective") is True, "authorization must be prospective")
    require(isinstance(authorization.get("authorized_by"), str) and authorization["authorized_by"].strip(), "authorizer missing")
    require(isinstance(authorization.get("authorized_at_utc"), str) and authorization["authorized_at_utc"].strip(), "authorization time missing")
    return digest


def command_for(cli: Path, item: dict[str, Any], cwd: Path, final_path: Path) -> list[str]:
    configs = {
        "approval_policy": "never",
        "model_reasoning_effort": item["reasoning_effort"],
        "service_tier": item["service_tier_config"],
        "features.multi_agent": False,
        "agents.max_depth": 1,
        "agents.max_threads": 1,
        "history.persistence": "none",
        "web_search": "disabled",
        "sandbox_workspace_write.network_access": False,
    }
    command = [str(cli), "exec", "--ignore-user-config", "--strict-config", "--model", item["model"], "--sandbox", item["sandbox"], "--ephemeral", "--json"]
    for key, value in configs.items():
        toml = json.dumps(value).lower() if isinstance(value, (bool, str)) else str(value)
        command.extend(["-c", f"{key}={toml}"])
    command.extend(["--output-schema", str(HERE / "final_schema.json"), "--output-last-message", str(final_path), "-C", str(cwd), "-"])
    return command


def git_status(repo: Path) -> list[str]:
    completed = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all"], capture_output=True, text=True)
    require(completed.returncode == 0, f"cannot inspect canary repository: {completed.stderr.strip()}")
    return [line for line in completed.stdout.splitlines() if line]


def validate_result(role: str, repo: Path, final_path: Path) -> None:
    try:
        final = json.loads(final_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationError(f"invalid final response: {exc}") from exc
    require(final == {"status": "ready"}, "final response is not exactly the frozen JSON object")
    status = git_status(repo)
    if role == "owner":
        require(status == [], "owner canary changed the repository")
        return
    require(status == ["?? result.txt"], f"executor changed unexpected paths: {status}")
    require((repo / "result.txt").read_bytes() == EXPECTED_EXECUTOR_BYTES, "executor result.txt bytes differ")


def prepare_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)
    completed = subprocess.run(["git", "-C", str(path), "init", "--quiet"], capture_output=True, text=True)
    require(completed.returncode == 0, f"git init failed: {completed.stderr.strip()}")


def run(freeze_path: Path, receipt_path: Path, authorization_path: Path, cli: Path, evidence_root: Path) -> None:
    verify(freeze_path, receipt_path)
    freeze = load(freeze_path)
    authorization = load(authorization_path)
    digest = validate_authorization(freeze, authorization)
    require(cli.is_file(), f"CLI executable missing: {cli}")
    require(file_sha256(cli) == EXPECTED_CLI_SHA256, "CLI executable hash differs from freeze")
    version = subprocess.run([str(cli), "--version"], capture_output=True, text=True)
    require(version.returncode == 0 and version.stdout.strip() == EXPECTED_CLI_VERSION, "CLI version differs from freeze")
    run_root = evidence_root / digest
    require(not run_root.exists(), f"refusing to overwrite evidence root {run_root}")
    longest_hook = run_root / call_directory_name(58) / "subject" / ".git" / "hooks" / "applypatch-msg.sample"
    if sys.platform == "win32":
        require(len(str(longest_hook)) < 248, f"evidence root leaves insufficient Windows path headroom: {longest_hook}")
    run_root.mkdir(parents=True)
    (run_root / "authorization.json").write_bytes(canonical(authorization))

    for item in freeze["schedule"]:
        call_root = run_root / call_directory_name(item["sequence"])
        call_root.mkdir()
        (call_root / "cell.json").write_bytes(canonical({"cell_id": item["cell_id"], "role": item["role"], "sequence": item["sequence"]}))
        repo = call_root / "subject"
        prepare_repo(repo)
        final_path = call_root / "final.json"
        prompt = (HERE / item["prompt"]).read_text(encoding="utf-8")
        command = command_for(cli, item, repo, final_path)
        (call_root / "command.json").write_bytes(canonical(command))
        completed = subprocess.run(command, input=prompt, capture_output=True, text=True)
        (call_root / "events.jsonl").write_text(completed.stdout, encoding="utf-8")
        (call_root / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        require(completed.returncode == 0, f"call {item['sequence']} failed; stopped without retry")
        validate_result(item["role"], repo, final_path)
        (call_root / "accepted.json").write_bytes(canonical({"accepted": True, "cell_id": item["cell_id"], "role": item["role"]}))

    (run_root / "completion.json").write_bytes(canonical({"freeze_sha256": digest, "calls_completed": 59, "all_pass": True, "retries": 0, "scientific_observations": 0}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "run"))
    parser.add_argument("--freeze", type=Path, default=HERE / "freeze_candidate.json")
    parser.add_argument("--receipt", type=Path, default=HERE / "offline_verification_receipt.json")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--cli", type=Path, default=Path("C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"))
    parser.add_argument("--evidence-root", type=Path, default=HERE.parent / "run" / "activation_v0_3")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verify(args.freeze, args.receipt)
        else:
            require(args.authorization is not None, "--authorization is required for live calls")
            run(args.freeze, args.receipt, args.authorization, args.cli, args.evidence_root)
    except (ActivationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("OK - activation freeze verified" if args.command == "verify" else "OK - 59/59 administrative canaries accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
