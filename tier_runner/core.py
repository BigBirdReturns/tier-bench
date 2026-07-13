from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import uuid
from typing import Any

from .manifest import Backend, ManifestError, expand_command, load_backend, sha256_file


RUN_SCHEMA = "tier-bench/tier-run-receipt@1"
DISPATCH_SCHEMA = "tier-bench/tier-dispatch-receipt@1"
BACKEND_SCHEMA = "tier-bench/tier-backend-result@1"
CALL_FIELDS = {
    "ts", "account", "model", "tier", "task_id", "phase", "outcome", "effort",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "cost_usd", "latency_ms", "trial", "note", "extra",
}


class RunError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path: Path, data: Any) -> bytes:
    raw = _canonical(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _run(
    argv: list[str] | str,
    cwd: Path,
    *,
    check: bool = False,
    shell: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        shell=shell,
        env=env,
    )
    if check and result.returncode:
        command = argv if isinstance(argv, str) else " ".join(argv)
        raise RunError(f"command failed ({result.returncode}): {command}\n{result.stderr}")
    return result


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", *args], repo, check=check)


def _repo_root(repo: Path) -> Path:
    repo = repo.resolve()
    result = _git(repo, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve()


def _git_common_dir(repo: Path) -> Path:
    value = _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    path = Path(value)
    return (repo / path).resolve() if not path.is_absolute() else path.resolve()


def _safe_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    if not slug:
        raise RunError("task id has no safe filename characters")
    return slug[:80]


def _normalize_scope(repo: Path, values: list[str]) -> list[tuple[str, bool]]:
    scopes: list[tuple[str, bool]] = []
    for raw_value in values:
        for raw in raw_value.split(","):
            raw = raw.strip().replace("\\", "/")
            if not raw:
                continue
            pure = PurePosixPath(raw.rstrip("/"))
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                raise RunError(f"unsafe --files scope: {raw!r}")
            if pure.parts[0] == ".git":
                raise RunError(".git cannot be in --files scope")
            normalized = pure.as_posix()
            is_dir = raw.endswith("/") or (repo / Path(*pure.parts)).is_dir()
            scopes.append((normalized, is_dir))
    if not scopes:
        raise RunError("--files must name at least one repository path")
    return sorted(set(scopes))


def _in_scope(path: str, scopes: list[tuple[str, bool]]) -> bool:
    path = PurePosixPath(path).as_posix()
    return any(
        path == scope or (is_dir and path.startswith(scope + "/"))
        for scope, is_dir in scopes
    )


def _committed_blob(repo: Path, base: str, path: Path, label: str) -> tuple[str, bytes]:
    try:
        rel = path.resolve().relative_to(repo).as_posix()
    except ValueError as exc:
        raise RunError(f"{label} must live inside the target repository") from exc
    binary = subprocess.run(
        ["git", "cat-file", "blob", f"{base}:{rel}"], cwd=repo, capture_output=True
    )
    if binary.returncode:
        raise RunError(f"{label} is not committed at base {base}: {rel}")
    return rel, binary.stdout


def _render_prompt(backend: Backend, task: str, scopes: list[tuple[str, bool]], acceptance: str,
                   base: str) -> bytes:
    template = backend.template_bytes.decode("utf-8")
    replacements = {
        "{{ACCEPTANCE}}": acceptance,
        "{{BASE_COMMIT}}": base,
        "{{FILES}}": "\n".join(scope + ("/" if is_dir else "") for scope, is_dir in scopes),
        "{{TASK}}": task,
    }
    absent = [marker for marker in replacements if marker not in template]
    if absent:
        raise RunError(f"prompt template is missing required markers: {absent}")
    rendered = template
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    missing = [marker for marker in replacements if marker in rendered]
    if missing:
        raise RunError(f"unexpanded prompt markers: {missing}")
    return rendered.encode("utf-8")


def _is_instruction_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return (
        pure.name.lower() in {"agents.md", "claude.md"}
        or any(part.lower() in {".claude", ".codex"} for part in pure.parts)
    )


def _copy_packet_file(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise RunError(f"symlinks are not allowed in model packet scope: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _prepare_packet(worktree: Path, packet: Path, scopes: list[tuple[str, bool]]) -> set[str]:
    packet.mkdir(parents=True, exist_ok=False)
    baseline: set[str] = set()
    for scope, is_dir in scopes:
        if _is_instruction_path(scope):
            raise RunError(f"instruction files cannot be model-edit scope: {scope}")
        source = worktree / Path(*PurePosixPath(scope).parts)
        if is_dir:
            if not source.is_dir():
                raise RunError(f"scoped directory does not exist at base: {scope}")
            for item in source.rglob("*"):
                if not item.is_file():
                    continue
                rel = item.relative_to(worktree).as_posix()
                if _is_instruction_path(rel):
                    continue
                _copy_packet_file(item, packet / Path(*PurePosixPath(rel).parts))
                baseline.add(rel)
        elif source.exists():
            if not source.is_file():
                raise RunError(f"scoped path is not a regular file: {scope}")
            _copy_packet_file(source, packet / Path(*PurePosixPath(scope).parts))
            baseline.add(scope)
        else:
            (packet / Path(*PurePosixPath(scope).parts)).parent.mkdir(parents=True, exist_ok=True)
    return baseline


def _sync_packet(
    packet: Path,
    worktree: Path,
    scopes: list[tuple[str, bool]],
    baseline: set[str],
) -> tuple[list[str], list[str]]:
    current: set[str] = set()
    violations: list[str] = []
    for item in packet.rglob("*"):
        if item.is_symlink():
            violations.append(item.relative_to(packet).as_posix() + " (symlink)")
            continue
        if not item.is_file():
            continue
        rel = item.relative_to(packet).as_posix()
        current.add(rel)
        if _is_instruction_path(rel) or not _in_scope(rel, scopes):
            violations.append(rel)
            continue
        _copy_packet_file(item, worktree / Path(*PurePosixPath(rel).parts))
    for rel in baseline - current:
        target = worktree / Path(*PurePosixPath(rel).parts)
        if target.exists():
            target.unlink()
    return sorted(current), sorted(set(violations))


def _validate_call(call: Any, backend: Backend, dispatch_hash: str) -> dict:
    if not isinstance(call, dict):
        raise RunError("backend result call must be an object")
    missing = CALL_FIELDS - set(call)
    unknown = set(call) - CALL_FIELDS
    if missing or unknown:
        raise RunError(
            f"backend call fields mismatch; missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    if call["model"] != backend.model_id or call["effort"] != backend.effort:
        raise RunError("backend call model/effort contradicts frozen manifest")
    if call["account"] != backend.account or call["tier"] != backend.tier:
        raise RunError("backend call account/tier contradicts frozen manifest")
    if call["phase"] != backend.arm:
        raise RunError("backend call phase must equal selected arm")
    extra = call.get("extra")
    if not isinstance(extra, dict):
        raise RunError("backend call extra must be an object")
    expected = {
        "backend_manifest_sha256": backend.manifest_sha256,
        "backend_surface": backend.surface,
        "cost_basis": backend.cost_basis,
        "dispatch_receipt_sha256": dispatch_hash,
        "prompt_template_sha256": backend.template_sha256,
        "runtime_model_id": backend.model_id,
    }
    for key, value in expected.items():
        if extra.get(key) != value:
            raise RunError(f"backend call extra.{key} contradicts frozen dispatch")
    if not isinstance(extra.get("session_id"), str) or not extra["session_id"]:
        raise RunError("backend call must preserve a fresh session_id or opaque hash")
    if extra.get("tool_versions") != backend.tool_versions:
        raise RunError("backend call tool_versions contradict the frozen manifest")
    if backend.cost_basis != "real-billed" and call["note"].find(backend.cost_basis) < 0:
        raise RunError("non-billed call note must name its cost basis")
    return call


def _changed_files(worktree: Path) -> list[str]:
    untracked = _git(worktree, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    if untracked:
        _git(worktree, "add", "-N", "--", *untracked)
    changed = _git(worktree, "diff", "--name-only", "HEAD").stdout.splitlines()
    return sorted({x.replace("\\", "/") for x in changed if x.strip()})


def _write_process_artifacts(
    run_dir: Path, prefix: str, result: subprocess.CompletedProcess
) -> dict:
    stdout_path = run_dir / f"{prefix}.stdout.txt"
    stderr_path = run_dir / f"{prefix}.stderr.txt"
    stdout_path.write_text(result.stdout or "", encoding="utf-8")
    stderr_path.write_text(result.stderr or "", encoding="utf-8")
    return {
        "returncode": result.returncode,
        "stderr_path": stderr_path.name,
        "stderr_sha256": sha256_file(stderr_path),
        "stdout_path": stdout_path.name,
        "stdout_sha256": sha256_file(stdout_path),
    }


def run_task(
    *,
    repo: Path,
    task_id: str,
    task: str,
    files: list[str],
    acceptance: str,
    manifest: Path,
    arm: str,
    output_dir: Path | None = None,
) -> dict:
    repo = _repo_root(repo)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise RunError("target repository HEAD is not a full Git SHA")
    scopes = _normalize_scope(repo, files)
    manifest = manifest.resolve()
    manifest_rel, _ = _committed_blob(repo, base, manifest, "backend manifest")

    def git_reader(path: Path) -> bytes:
        label = "backend manifest" if path.resolve() == manifest else "prompt template"
        return _committed_blob(repo, base, path, label)[1]

    backend = load_backend(manifest, arm, read_bytes=git_reader)
    template_rel, _ = _committed_blob(repo, base, backend.template_path, "prompt template")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{_safe_id(task_id)}-{stamp}-{uuid.uuid4().hex[:8]}"
    common_git = _git_common_dir(repo)
    run_dir = (output_dir.resolve() if output_dir else common_git / "tier-runs" / run_id)
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RunError(f"output directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    worktree = common_git / "tier-worktrees" / run_id
    packet = run_dir / "model-packet"
    prompt_path = run_dir / "prompt.txt"
    dispatch_path = run_dir / "dispatch-receipt.json"
    backend_result_path = run_dir / "backend-result.json"
    ledger_path = run_dir / "ledger.jsonl"
    patch_path = run_dir / "change.patch"
    receipt_path = run_dir / "receipt.json"

    receipt: dict[str, Any] = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "state": "ERROR",
        "started_at": _now(),
        "task_id": task_id,
        "task": task,
        "repo": str(repo),
        "base_commit": base,
        "arm": arm,
        "files": [scope + ("/" if is_dir else "") for scope, is_dir in scopes],
        "acceptance_command": acceptance,
        "backend_manifest": {"path": manifest_rel, "sha256": backend.manifest_sha256},
        "prompt_template": {"path": template_rel, "sha256": backend.template_sha256},
        "artifacts": {},
        "errors": [],
    }
    added_worktree = False
    try:
        _git(repo, "worktree", "add", "--detach", str(worktree), base)
        added_worktree = True
        packet_baseline = _prepare_packet(worktree, packet, scopes)
        prompt_raw = _render_prompt(backend, task, scopes, acceptance, base)
        prompt_path.write_bytes(prompt_raw)
        prompt_hash = _sha(prompt_raw)
        dispatch = {
            "schema": DISPATCH_SCHEMA,
            "run_id": run_id,
            "task_id": task_id,
            "arm": arm,
            "base_commit": base,
            "backend_manifest_sha256": backend.manifest_sha256,
            "acceptance_sha256": _sha(acceptance.encode("utf-8")),
            "files": receipt["files"],
            "prompt_sha256": prompt_hash,
            "prompt_template_sha256": backend.template_sha256,
            "task_sha256": _sha(task.encode("utf-8")),
            "dispatched_at": _now(),
        }
        dispatch_raw = _write_json(dispatch_path, dispatch)
        dispatch_hash = _sha(dispatch_raw)
        values = {
            "arm": arm,
            "backend_result": str(backend_result_path),
            "dispatch_receipt": str(dispatch_path),
            "prompt": str(prompt_path),
            "run_dir": str(run_dir),
            "task_id": task_id,
            "worktree": str(packet),
        }
        command = expand_command(backend.command, values)
        env = dict(os.environ)
        env.update({
            "PYTHONUTF8": "1",
            "TIER_ARM": arm,
            "TIER_DISPATCH_RECEIPT": str(dispatch_path),
            "TIER_PROMPT": str(prompt_path),
            "TIER_RUN_DIR": str(run_dir),
            "TIER_WORKTREE": str(packet),
        })
        backend_process = _run(command, packet, env=env)
        receipt["backend_process"] = _write_process_artifacts(run_dir, "backend", backend_process)
        if backend_process.returncode:
            raise RunError(f"backend adapter exited {backend_process.returncode}")
        if not backend_result_path.is_file():
            raise RunError("backend adapter produced no backend-result.json")
        backend_result = json.loads(backend_result_path.read_text(encoding="utf-8"))
        if not isinstance(backend_result, dict) or backend_result.get("schema") != BACKEND_SCHEMA:
            raise RunError(f"backend result schema must be {BACKEND_SCHEMA}")
        calls = backend_result.get("calls")
        if not isinstance(calls, list) or len(calls) != 1:
            raise RunError("one tier run dispatch must produce exactly one model-call receipt")
        call = _validate_call(calls[0], backend, dispatch_hash)
        ledger_path.write_bytes(_canonical(call))
        if call["extra"].get("telemetry_complete") is not True:
            raise RunError("backend call telemetry is incomplete")
        if call["outcome"] != "pass":
            raise RunError(f"backend model call outcome is {call['outcome']!r}")

        _, packet_violations = _sync_packet(packet, worktree, scopes, packet_baseline)
        changed = _changed_files(worktree)
        violations = sorted(set(packet_violations + [
            path for path in changed if not _in_scope(path, scopes)
        ]))
        patch = subprocess.run(
            ["git", "diff", "--binary", "--full-index", "HEAD"],
            cwd=worktree,
            check=True,
            capture_output=True,
        ).stdout
        patch_path.write_bytes(patch)
        receipt["changes"] = {"files": changed, "scope_violations": violations}
        if violations:
            raise RunError(f"backend changed files outside --files scope: {violations}")
        if not changed:
            raise RunError("backend produced no repository changes")

        acceptance_env = dict(os.environ)
        acceptance_env["PYTHONUTF8"] = "1"
        acceptance_process = _run(acceptance, worktree, shell=True, env=acceptance_env)
        receipt["acceptance"] = _write_process_artifacts(run_dir, "acceptance", acceptance_process)
        if acceptance_process.returncode:
            receipt["state"] = "REJECTED"
            receipt["errors"].append(f"acceptance failed with rc={acceptance_process.returncode}")
        else:
            receipt["state"] = "ACCEPTED"
    except (ManifestError, RunError, OSError, ValueError, json.JSONDecodeError) as exc:
        receipt["errors"].append(str(exc))
    finally:
        if not patch_path.exists():
            patch_path.write_bytes(b"")
        if added_worktree:
            removed = _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
            receipt["worktree_removed"] = removed.returncode == 0
            if removed.returncode:
                receipt["errors"].append(f"failed to remove worktree: {removed.stderr.strip()}")
        else:
            receipt["worktree_removed"] = not worktree.exists()
        shutil.rmtree(packet, ignore_errors=True)
        if not receipt["worktree_removed"]:
            receipt["state"] = "ERROR"
        receipt["completed_at"] = _now()
        for name, path in (
            ("backend_result", backend_result_path),
            ("dispatch_receipt", dispatch_path),
            ("ledger", ledger_path),
            ("patch", patch_path),
            ("prompt", prompt_path),
        ):
            if path.is_file():
                receipt["artifacts"][name] = {"path": path.name, "sha256": sha256_file(path)}
        _write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def verify_run(run_dir: Path) -> list[str]:
    run_dir = run_dir.resolve()
    errors: list[str] = []
    receipt_path = run_dir / "receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read receipt.json: {exc}"]
    if receipt.get("schema") != RUN_SCHEMA:
        errors.append(f"receipt schema must be {RUN_SCHEMA}")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        return errors + ["receipt artifacts must be an object"]
    resolved: dict[str, Path] = {}
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            errors.append(f"artifact {name} is not an object")
            continue
        relative = artifact.get("path")
        if not isinstance(relative, str):
            errors.append(f"artifact {name} has no path")
            continue
        path = (run_dir / relative).resolve()
        try:
            path.relative_to(run_dir)
        except ValueError:
            errors.append(f"artifact {name} escapes run directory")
            continue
        resolved[name] = path
        if not path.is_file():
            errors.append(f"artifact {name} is missing: {relative}")
        elif sha256_file(path) != artifact.get("sha256"):
            errors.append(f"artifact {name} hash mismatch")

    for process_name in ("backend_process", "acceptance"):
        process = receipt.get(process_name)
        if process is None:
            continue
        if not isinstance(process, dict):
            errors.append(f"{process_name} must be an object")
            continue
        for stream in ("stdout", "stderr"):
            relative = process.get(f"{stream}_path")
            expected = process.get(f"{stream}_sha256")
            if not isinstance(relative, str):
                errors.append(f"{process_name} has no {stream} path")
                continue
            path = (run_dir / relative).resolve()
            try:
                path.relative_to(run_dir)
            except ValueError:
                errors.append(f"{process_name} {stream} escapes run directory")
                continue
            if not path.is_file():
                errors.append(f"{process_name} {stream} is missing")
            elif sha256_file(path) != expected:
                errors.append(f"{process_name} {stream} hash mismatch")

    if receipt.get("state") == "ACCEPTED":
        required = {"backend_result", "dispatch_receipt", "ledger", "patch", "prompt"}
        missing = required - set(resolved)
        if missing:
            errors.append(f"accepted receipt is missing artifacts: {sorted(missing)}")
        if receipt.get("errors"):
            errors.append("accepted receipt carries errors")
        if receipt.get("worktree_removed") is not True:
            errors.append("accepted receipt did not remove its worktree")
        acceptance_result = receipt.get("acceptance")
        if not isinstance(acceptance_result, dict) or acceptance_result.get("returncode") != 0:
            errors.append("accepted receipt lacks a passing acceptance process")
        changes = receipt.get("changes")
        if not isinstance(changes, dict) or not changes.get("files"):
            errors.append("accepted receipt has no changed files")
        elif changes.get("scope_violations"):
            errors.append("accepted receipt carries scope violations")
        patch = resolved.get("patch")
        if patch and patch.is_file() and not patch.read_bytes():
            errors.append("accepted receipt has an empty patch")

    dispatch_path = resolved.get("dispatch_receipt")
    ledger_path = resolved.get("ledger")
    prompt_path = resolved.get("prompt")
    if dispatch_path and dispatch_path.is_file():
        try:
            dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid dispatch receipt: {exc}")
            dispatch = {}
        if dispatch.get("schema") != DISPATCH_SCHEMA:
            errors.append(f"dispatch schema must be {DISPATCH_SCHEMA}")
        acceptance_command = receipt.get("acceptance_command")
        task = receipt.get("task")
        backend_binding = receipt.get("backend_manifest")
        template_binding = receipt.get("prompt_template")
        if not isinstance(acceptance_command, str):
            errors.append("receipt acceptance_command must be a string")
            acceptance_command = ""
        if not isinstance(task, str):
            errors.append("receipt task must be a string")
            task = ""
        if not isinstance(backend_binding, dict):
            errors.append("receipt backend_manifest must be an object")
            backend_binding = {}
        if not isinstance(template_binding, dict):
            errors.append("receipt prompt_template must be an object")
            template_binding = {}
        expected_dispatch = {
            "acceptance_sha256": _sha(acceptance_command.encode()),
            "backend_manifest_sha256": backend_binding.get("sha256"),
            "files": receipt.get("files"),
            "prompt_template_sha256": template_binding.get("sha256"),
            "task_sha256": _sha(task.encode()),
        }
        for key, value in expected_dispatch.items():
            if dispatch.get(key) != value:
                errors.append(f"dispatch {key} does not bind the final receipt")
        if prompt_path and prompt_path.is_file():
            if dispatch.get("prompt_sha256") != sha256_file(prompt_path):
                errors.append("dispatch prompt hash mismatch")
        if ledger_path and ledger_path.is_file():
            lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line]
            if len(lines) != 1:
                errors.append("ledger must contain exactly one call row")
            else:
                try:
                    call = json.loads(lines[0])
                except json.JSONDecodeError as exc:
                    errors.append(f"invalid ledger row: {exc}")
                else:
                    extra = call.get("extra", {})
                    if extra.get("dispatch_receipt_sha256") != sha256_file(dispatch_path):
                        errors.append("ledger does not bind the dispatch receipt")
                    if extra.get("backend_manifest_sha256") != dispatch.get(
                        "backend_manifest_sha256"
                    ):
                        errors.append("ledger manifest hash mismatch")
                    if extra.get("prompt_template_sha256") != dispatch.get(
                        "prompt_template_sha256"
                    ):
                        errors.append("ledger prompt-template hash mismatch")
    return errors
