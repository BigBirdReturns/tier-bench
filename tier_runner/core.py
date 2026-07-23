from __future__ import annotations

# Production pilot activation binds this packet/session authority exactly.

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from typing import Any

from .manifest import Backend, ManifestError, expand_command, load_backend, sha256_file


def hidden_process_kwargs(
    platform_name: str = os.name, *, new_process_group: bool = False
) -> dict[str, object]:
    if platform_name == "nt":
        flags = subprocess.CREATE_NO_WINDOW
        if new_process_group:
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags}
    return {}


ACCEPTANCE_TIMEOUT_SECONDS = 300.0
TIMEOUT_RETURNCODE = 124
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


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunError(f"{label} must be a JSON object")
    return value


def _kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
            **hidden_process_kwargs(),
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _run(
    argv: list[str] | str,
    cwd: Path,
    *,
    check: bool = False,
    shell: bool = False,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    if timeout is None:
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            shell=shell,
            env=env,
            **hidden_process_kwargs(),
        )
    else:
        # A candidate patch can hang its own grader, and on Windows the spinning
        # process is a grandchild that outlives a plain child kill; supervise the
        # whole tree so a hang becomes a terminal verdict instead of a wedged desk.
        group = (
            hidden_process_kwargs(new_process_group=True)
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=shell,
            env=env,
            **group,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            stdout, stderr = process.communicate()
            stderr = (stderr or "") + f"\ntier run: command exceeded {timeout:g}s and was terminated\n"
            returncode = TIMEOUT_RETURNCODE
        result = subprocess.CompletedProcess(argv, returncode, stdout, stderr)
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


def _packet_temp_root() -> Path | None:
    if os.name != "nt":
        return None
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = (
        Path(local_app_data) / "Temp"
        if local_app_data
        else Path.home() / "AppData" / "Local" / "Temp"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


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
    template_markers = set(re.findall(r"\{\{[A-Z_]+\}\}", template))
    unknown = template_markers - set(replacements)
    if unknown:
        raise RunError(f"prompt template has unknown markers: {sorted(unknown)}")
    marker_pattern = re.compile("|".join(re.escape(marker) for marker in replacements))
    rendered = marker_pattern.sub(lambda match: replacements[match.group(0)], template)
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


def _validate_nonnegative_number(value: Any, label: str, *, integer: bool = False) -> None:
    expected = int if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, expected):
        raise RunError(f"backend call {label} must be a non-negative number")
    if not math.isfinite(float(value)) or value < 0:
        raise RunError(f"backend call {label} must be finite and non-negative")


def _reported_session_id(call: Any) -> str | None:
    if not isinstance(call, dict) or not isinstance(call.get("extra"), dict):
        return None
    session_id = call["extra"].get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def _validate_call(
    call: Any,
    backend: Backend,
    dispatch_hash: str,
    task_id: str,
) -> dict:
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
    if call["task_id"] != task_id:
        raise RunError("backend call task_id contradicts frozen dispatch")
    if call["account"] != backend.account or call["tier"] != backend.tier:
        raise RunError("backend call account/tier contradicts frozen manifest")
    if call["phase"] != backend.arm:
        raise RunError("backend call phase must equal selected arm")
    for key in ("ts", "account", "model", "tier", "task_id", "phase", "outcome", "effort", "note"):
        if not isinstance(call[key], str) or not call[key]:
            raise RunError(f"backend call {key} must be a non-empty string")
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
    try:
        parsed_ts = datetime.fromisoformat(call["ts"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunError("backend call ts must be an ISO-8601 timestamp") from exc
    if parsed_ts.tzinfo is None:
        raise RunError("backend call ts must include a timezone")
    for key in (
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "trial"
    ):
        _validate_nonnegative_number(call[key], key, integer=True)
    for key in ("cost_usd", "latency_ms"):
        _validate_nonnegative_number(call[key], key)
    return call


def _register_session(
    common_git: Path,
    *,
    session_id: str,
    run_id: str,
    task_id: str,
    arm: str,
    dispatch_hash: str,
) -> None:
    registry = common_git / "tier-session-registry.jsonl"
    lock = common_git / "tier-session-registry.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RunError("session registry is busy; refusing an unverified fresh session") from exc
    os.close(descriptor)
    try:
        session_hash = _sha(session_id.encode("utf-8"))
        if registry.exists():
            for number, line in enumerate(registry.read_text(encoding="utf-8").splitlines(), 1):
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RunError(f"invalid session registry row {number}") from exc
                if not isinstance(row, dict) or not isinstance(row.get("session_sha256"), str):
                    raise RunError(f"invalid session registry row {number}")
                if row["session_sha256"] == session_hash:
                    raise RunError("backend reused a session_id from an earlier tier run")
        row = {
            "arm": arm,
            "dispatch_receipt_sha256": dispatch_hash,
            "registered_at": _now(),
            "run_id": run_id,
            "session_sha256": session_hash,
            "task_id": task_id,
        }
        with registry.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(row).decode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        lock.unlink(missing_ok=True)


def _backend_artifacts(
    result: dict[str, Any], run_dir: Path
) -> dict[str, tuple[Path, str]]:
    declared = result.get("artifacts", [])
    if not isinstance(declared, list):
        raise RunError("backend result artifacts must be an array")
    artifacts: dict[str, tuple[Path, str]] = {}
    for entry in declared:
        if not isinstance(entry, dict) or set(entry) != {"name", "path", "sha256"}:
            raise RunError("backend artifact must contain exactly name, path, and sha256")
        name = entry["name"]
        relative = entry["path"]
        expected_hash = entry["sha256"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_.-]+", name):
            raise RunError("backend artifact name is unsafe")
        if name in artifacts:
            raise RunError(f"duplicate backend artifact name: {name}")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise RunError("backend artifact path/hash must be strings")
        path = (run_dir / relative).resolve()
        if not _inside(path, run_dir) or not path.is_file():
            raise RunError(f"backend artifact is missing or escapes run directory: {relative}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise RunError(f"backend artifact hash mismatch: {name}")
        artifacts[name] = (path, actual_hash)
    return artifacts


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
    manifest_rel, manifest_raw = _committed_blob(repo, base, manifest, "backend manifest")

    def git_reader(path: Path) -> bytes:
        label = "backend manifest" if path.resolve() == manifest else "prompt template"
        return _committed_blob(repo, base, path, label)[1]

    backend = load_backend(manifest, arm, read_bytes=git_reader)
    template_rel, template_raw = _committed_blob(
        repo, base, backend.template_path, "prompt template"
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{_safe_id(task_id)}-{stamp}-{uuid.uuid4().hex[:8]}"
    common_git = _git_common_dir(repo)
    default_runs = (common_git / "tier-runs").resolve()
    run_dir = (output_dir.resolve() if output_dir else default_runs / run_id)
    if _inside(run_dir, repo) and not _inside(run_dir, default_runs):
        raise RunError("output directory cannot modify the operator's checkout")
    if _inside(run_dir, common_git) and not _inside(run_dir, default_runs):
        raise RunError("output directory under the common Git directory must use tier-runs/")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RunError(f"output directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    # Keep the disposable checkout path short. This repository contains valid,
    # deeply nested evidence paths that exceed Windows' legacy path ceiling
    # when repeated beneath .git/tier-worktrees/<full-run-id>.
    worktree_root = common_git.parent.parent / ".tier-worktrees"
    worktree = worktree_root / ("tier-" + uuid.uuid4().hex[:8])
    prompt_path = run_dir / "prompt.txt"
    dispatch_path = run_dir / "dispatch-receipt.json"
    backend_result_path = run_dir / "backend-result.json"
    ledger_path = run_dir / "ledger.jsonl"
    patch_path = run_dir / "change.patch"
    receipt_path = run_dir / "receipt.json"
    manifest_copy_path = run_dir / "backend-manifest.json"
    template_copy_path = run_dir / "prompt-template.txt"
    manifest_copy_path.write_bytes(manifest_raw)
    template_copy_path.write_bytes(template_raw)

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
    packet = Path(
        tempfile.mkdtemp(
            prefix=f"tier-packet-{_safe_id(task_id)}-",
            dir=_packet_temp_root(),
        )
    )
    added_worktree = False
    try:
        _git(repo, "worktree", "add", "--detach", str(worktree), base)
        added_worktree = True
        packet.rmdir()
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
            "backend": {
                "account": backend.account,
                "cost_basis": backend.cost_basis,
                "effort": backend.effort,
                "model_id": backend.model_id,
                "protocol_commit": backend.protocol_commit,
                "surface": backend.surface,
                "tier": backend.tier,
                "tool_versions": backend.tool_versions,
            },
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
            "task_id": task_id,
            "worktree": str(packet),
        }
        command = expand_command(backend.command, values)
        env = {key: value for key, value in os.environ.items() if not key.startswith("TIER_")}
        env["PYTHONUTF8"] = "1"
        package_root = str(Path(__file__).resolve().parents[1])
        inherited_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            package_root
            if not inherited_pythonpath
            else package_root + os.pathsep + inherited_pythonpath
        )
        backend_process = _run(command, packet, env=env)
        receipt["backend_process"] = _write_process_artifacts(run_dir, "backend", backend_process)
        if backend_process.returncode:
            raise RunError(f"backend adapter exited {backend_process.returncode}")
        if not backend_result_path.is_file():
            raise RunError("backend adapter produced no backend-result.json")
        if prompt_path.read_bytes() != prompt_raw or dispatch_path.read_bytes() != dispatch_raw:
            raise RunError("backend modified an immutable prompt or dispatch receipt")
        if (
            manifest_copy_path.read_bytes() != manifest_raw
            or template_copy_path.read_bytes() != template_raw
        ):
            raise RunError("backend modified frozen manifest/template evidence")
        backend_result = _read_json_object(backend_result_path, "backend result")
        if backend_result.get("schema") != BACKEND_SCHEMA:
            raise RunError(f"backend result schema must be {BACKEND_SCHEMA}")
        calls = backend_result.get("calls")
        if not isinstance(calls, list) or not calls:
            raise RunError("tier run dispatch produced no model-call receipts")
        is_benchmark = backend.surface == "ollama-local-benchmark"
        if not is_benchmark and len(calls) != 1:
            raise RunError("one file-work dispatch must produce exactly one model-call receipt")
        if is_benchmark and len(calls) > 20:
            raise RunError("one benchmark dispatch may contain at most 20 model-call receipts")
        sealed_calls: list[dict[str, Any]] = []
        for raw_call in calls:
            reported_session = _reported_session_id(raw_call)
            if reported_session is not None:
                _register_session(
                    common_git,
                    session_id=reported_session,
                    run_id=run_id,
                    task_id=task_id,
                    arm=arm,
                    dispatch_hash=dispatch_hash,
                )
            call = _validate_call(raw_call, backend, dispatch_hash, task_id)
            if call["extra"].get("telemetry_complete") is not True:
                raise RunError("backend call telemetry is incomplete")
            if call["outcome"] != "pass":
                raise RunError(f"backend model call outcome is {call['outcome']!r}")
            sealed_calls.append(call)
        if is_benchmark and [call["trial"] for call in sealed_calls] != list(
            range(1, len(sealed_calls) + 1)
        ):
            raise RunError("benchmark call trials must be contiguous and start at one")
        ledger_path.write_bytes(b"".join(_canonical(call) for call in sealed_calls))
        for name, (path, digest) in _backend_artifacts(backend_result, run_dir).items():
            receipt["artifacts"][f"backend_{name}"] = {
                "path": path.relative_to(run_dir).as_posix(),
                "sha256": digest,
            }

        _, packet_violations = _sync_packet(packet, worktree, scopes, packet_baseline)
        changed = _changed_files(worktree)
        violations = sorted(set(packet_violations + [
            path for path in changed if not _in_scope(path, scopes)
        ]))
        patch_before_acceptance = subprocess.run(
            ["git", "diff", "--binary", "--full-index", "HEAD"],
            cwd=worktree,
            check=True,
            capture_output=True,
        ).stdout
        patch_path.write_bytes(patch_before_acceptance)
        receipt["changes"] = {"files": changed, "scope_violations": violations}
        if violations:
            raise RunError(f"backend changed files outside --files scope: {violations}")
        if not changed:
            raise RunError("backend produced no repository changes")

        acceptance_env = dict(os.environ)
        acceptance_env["PYTHONUTF8"] = "1"
        acceptance_env["PYTHONDONTWRITEBYTECODE"] = "1"
        acceptance_process = _run(
            acceptance,
            worktree,
            shell=True,
            env=acceptance_env,
            timeout=ACCEPTANCE_TIMEOUT_SECONDS,
        )
        receipt["acceptance"] = _write_process_artifacts(run_dir, "acceptance", acceptance_process)
        changed_after_acceptance = _changed_files(worktree)
        patch_after_acceptance = subprocess.run(
            ["git", "diff", "--binary", "--full-index", "HEAD"],
            cwd=worktree,
            check=True,
            capture_output=True,
        ).stdout
        if changed_after_acceptance != changed or patch_after_acceptance != patch_before_acceptance:
            receipt["changes_after_acceptance"] = {"files": changed_after_acceptance}
            raise RunError(
                "acceptance command mutated the candidate; no tested patch can be emitted"
            )
        if acceptance_process.returncode == TIMEOUT_RETURNCODE:
            receipt["state"] = "REJECTED"
            receipt["errors"].append(
                f"acceptance exceeded {ACCEPTANCE_TIMEOUT_SECONDS:g}s and was terminated; "
                "the candidate did not finish its own grader"
            )
        elif acceptance_process.returncode:
            receipt["state"] = "REJECTED"
            receipt["errors"].append(f"acceptance failed with rc={acceptance_process.returncode}")
        else:
            receipt["state"] = "ACCEPTED"
    except (
        ManifestError,
        RunError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
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
        try:
            shutil.rmtree(packet)
        except OSError as exc:
            receipt["errors"].append(f"failed to remove model packet: {exc}")
        receipt["packet_removed"] = not packet.exists()
        if not receipt["packet_removed"]:
            receipt["state"] = "ERROR"
        if not receipt["worktree_removed"]:
            receipt["state"] = "ERROR"
        receipt["completed_at"] = _now()
        for name, path in (
            ("backend_result", backend_result_path),
            ("backend_manifest", manifest_copy_path),
            ("dispatch_receipt", dispatch_path),
            ("ledger", ledger_path),
            ("patch", patch_path),
            ("prompt", prompt_path),
            ("prompt_template", template_copy_path),
        ):
            if path.is_file():
                receipt["artifacts"][name] = {"path": path.name, "sha256": sha256_file(path)}
        _write_json(receipt_path, receipt)
        if receipt["state"] == "ACCEPTED":
            self_errors = verify_run(run_dir)
            if self_errors:
                receipt["state"] = "ERROR"
                receipt["errors"].append(
                    "self-verification failed: " + "; ".join(self_errors)
                )
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
    if not isinstance(receipt, dict):
        return ["receipt.json must contain an object"]
    if receipt.get("schema") != RUN_SCHEMA:
        errors.append(f"receipt schema must be {RUN_SCHEMA}")
    if receipt.get("state") not in {"ACCEPTED", "REJECTED", "ERROR"}:
        errors.append("receipt state is invalid")
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
        required = {
            "backend_manifest", "backend_result", "dispatch_receipt", "ledger", "patch",
            "prompt", "prompt_template",
        }
        missing = required - set(resolved)
        if missing:
            errors.append(f"accepted receipt is missing artifacts: {sorted(missing)}")
        if receipt.get("errors"):
            errors.append("accepted receipt carries errors")
        if receipt.get("worktree_removed") is not True:
            errors.append("accepted receipt did not remove its worktree")
        if receipt.get("packet_removed") is not True:
            errors.append("accepted receipt did not remove its model packet")
        backend_process = receipt.get("backend_process")
        if not isinstance(backend_process, dict) or backend_process.get("returncode") != 0:
            errors.append("accepted receipt lacks a successful backend process")
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
    backend_result_path = resolved.get("backend_result")
    manifest_path = resolved.get("backend_manifest")
    template_path = resolved.get("prompt_template")
    if dispatch_path and dispatch_path.is_file():
        try:
            dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid dispatch receipt: {exc}")
            dispatch = {}
        if not isinstance(dispatch, dict):
            errors.append("dispatch receipt must be an object")
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
            "arm": receipt.get("arm"),
            "acceptance_sha256": _sha(acceptance_command.encode()),
            "base_commit": receipt.get("base_commit"),
            "backend_manifest_sha256": backend_binding.get("sha256"),
            "files": receipt.get("files"),
            "prompt_template_sha256": template_binding.get("sha256"),
            "run_id": receipt.get("run_id"),
            "task_id": receipt.get("task_id"),
            "task_sha256": _sha(task.encode()),
        }
        for key, value in expected_dispatch.items():
            if dispatch.get(key) != value:
                errors.append(f"dispatch {key} does not bind the final receipt")
        if prompt_path and prompt_path.is_file():
            if dispatch.get("prompt_sha256") != sha256_file(prompt_path):
                errors.append("dispatch prompt hash mismatch")
        if manifest_path and manifest_path.is_file():
            if backend_binding.get("sha256") != sha256_file(manifest_path):
                errors.append("frozen backend-manifest copy hash mismatch")
        if template_path and template_path.is_file():
            if template_binding.get("sha256") != sha256_file(template_path):
                errors.append("frozen prompt-template copy hash mismatch")
        if ledger_path and ledger_path.is_file():
            lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line]
            backend = dispatch.get("backend")
            if not isinstance(backend, dict):
                errors.append("dispatch has no frozen backend snapshot")
                backend = {}
            is_benchmark = backend.get("surface") == "ollama-local-benchmark"
            if not lines:
                errors.append("ledger must contain at least one call row")
            elif not is_benchmark and len(lines) != 1:
                errors.append("file-work ledger must contain exactly one call row")
            elif is_benchmark and len(lines) > 20:
                errors.append("benchmark ledger may contain at most 20 call rows")
            ledger_calls: list[dict[str, Any]] = []
            for index, line in enumerate(lines, 1):
                try:
                    call = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"invalid ledger row {index}: {exc}")
                    continue
                if not isinstance(call, dict):
                    errors.append(f"ledger call {index} must be an object")
                    continue
                ledger_calls.append(call)
                if set(call) != CALL_FIELDS:
                    errors.append(f"ledger call {index} fields do not match ledger.Call")
                extra = call.get("extra", {})
                if not isinstance(extra, dict):
                    errors.append(f"ledger call {index} extra must be an object")
                    extra = {}
                if extra.get("dispatch_receipt_sha256") != sha256_file(dispatch_path):
                    errors.append(f"ledger call {index} does not bind the dispatch receipt")
                call_bindings = {
                    "account": backend.get("account"),
                    "effort": backend.get("effort"),
                    "model": backend.get("model_id"),
                    "phase": dispatch.get("arm"),
                    "task_id": dispatch.get("task_id"),
                    "tier": backend.get("tier"),
                }
                for key, expected in call_bindings.items():
                    if call.get(key) != expected:
                        errors.append(
                            f"ledger call {index} {key} contradicts frozen dispatch"
                        )
                extra_bindings = {
                    "backend_manifest_sha256": dispatch.get("backend_manifest_sha256"),
                    "backend_surface": backend.get("surface"),
                    "cost_basis": backend.get("cost_basis"),
                    "prompt_template_sha256": dispatch.get("prompt_template_sha256"),
                    "runtime_model_id": backend.get("model_id"),
                    "tool_versions": backend.get("tool_versions"),
                }
                for key, expected in extra_bindings.items():
                    if extra.get(key) != expected:
                        errors.append(
                            f"ledger call {index} extra.{key} contradicts frozen dispatch"
                        )
                if extra.get("telemetry_complete") is not True:
                    errors.append(f"ledger call {index} telemetry is incomplete")
                if not isinstance(extra.get("session_id"), str) or not extra.get("session_id"):
                    errors.append(f"ledger call {index} has no session identity")
                if call.get("outcome") != "pass" and receipt.get("state") == "ACCEPTED":
                    errors.append(f"accepted receipt has non-pass backend call {index}")
                for key in (
                    "input_tokens", "output_tokens", "cache_read_tokens",
                    "cache_write_tokens", "trial",
                ):
                    value = call.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        errors.append(
                            f"ledger call {index} {key} must be a non-negative integer"
                        )
                for key in ("cost_usd", "latency_ms"):
                    value = call.get(key)
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        or value < 0
                    ):
                        errors.append(
                            f"ledger call {index} {key} must be finite and non-negative"
                        )
                raw_hash = extra.get("raw_result_sha256")
                raw_artifact = resolved.get("backend_provider_raw")
                if raw_hash is not None and (
                    not raw_artifact or not raw_artifact.is_file()
                    or sha256_file(raw_artifact) != raw_hash
                ):
                    errors.append(
                        f"provider raw result for call {index} is not hash-bound as an artifact"
                    )
                stderr_hash = extra.get("stderr_sha256")
                stderr_artifact = resolved.get("backend_provider_stderr")
                if stderr_hash is not None and (
                    not stderr_artifact or not stderr_artifact.is_file()
                    or sha256_file(stderr_artifact) != stderr_hash
                ):
                    errors.append(
                        f"provider stderr for call {index} is not hash-bound as an artifact"
                    )
            if is_benchmark and [call.get("trial") for call in ledger_calls] != list(
                range(1, len(ledger_calls) + 1)
            ):
                errors.append("benchmark ledger trials must be contiguous and start at one")
            if backend_result_path and backend_result_path.is_file():
                try:
                    backend_result = json.loads(
                        backend_result_path.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError as exc:
                    errors.append(f"invalid backend result: {exc}")
                else:
                    if not isinstance(backend_result, dict):
                        errors.append("backend result must be an object")
                    elif backend_result.get("schema") != BACKEND_SCHEMA:
                        errors.append("backend result schema mismatch")
                    elif backend_result.get("calls") != ledger_calls:
                        errors.append(
                            "backend result calls do not equal the sealed ledger rows"
                        )
                    declared_artifacts = backend_result.get("artifacts", [])
                    if not isinstance(declared_artifacts, list):
                        errors.append("backend result artifacts must be an array")
                    else:
                        for artifact in declared_artifacts:
                            if not isinstance(artifact, dict):
                                errors.append("backend result artifact must be an object")
                                continue
                            name = artifact.get("name")
                            sealed = resolved.get(f"backend_{name}")
                            if (
                                not isinstance(name, str)
                                or not sealed
                                or not sealed.is_file()
                                or artifact.get("sha256") != sha256_file(sealed)
                                or artifact.get("path")
                                != sealed.relative_to(run_dir).as_posix()
                            ):
                                errors.append(
                                    f"backend result artifact {name!r} is not sealed"
                                )
    return errors
