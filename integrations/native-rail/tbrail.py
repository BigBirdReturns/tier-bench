#!/usr/bin/env python3
"""tbrail v3 -- Tier Bench native private execution rail. Controller for octo-n01.

Stdlib only. No provider calls. Source arrives as a pre-verified exact-SHA git
bundle resolved under an admitted custody root, so the worker holds no GitHub
credential and performs no network I/O.

v3 repairs the boundaries the exact-head second desk found in v2 at
`8a84295cbaf7edadfb5b5df9cf46a0013f278fe4` (PR #165 comment 5263139142,
successor instruction tier-bench#164 comment 5263150454):

  1. lease continuity -- a verified same-host process identity dominates TTL,
     and a heartbeat runs for the whole duration of a phase
  2. the lease is held through workspace sanitation, receipt and sidecar
     publication and the verified atomic transition to SETTLED
  3. cross-phase state law -- a PASSed phase checkpoints its workspace, and
     recovery restores the checkpoint instead of recloning pristine source
  4. repository operations come from an accepted repository-operation manifest;
     the envelope may name an operation id and typed values only. There is no
     envelope-supplied script path, digest, argv or switch list
  5. every bind source is resolved under the repository, symlink and reparse
     sources are refused, and nested allowed subtrees are honoured exactly
  6. evidence validity is independent of outcome -- valid PASS, FAIL and HOLD
     receipts all verify, while binding the ledger terminal and envelope digest
  7. controller root, source custody, database, logs and receipts are owner-only
  8. output is streamed under a ceiling, and CPU, address space, file size, open
     files, process count and workspace bytes are enforced, not described
  9. the controller, sandbox engine, runtime closure, rail scripts and operation
     manifests are bound to an externally accepted runner profile

Layer law, unchanged and now fully enforced: the envelope is closed data. Issue
text, PR prose, comments and model output never become argv. A phase names an
operation id and typed parameters; the controller builds the command.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from pathlib import Path

SELF = Path(__file__).resolve()
HERE = SELF.parent
RAIL_HOME = Path(os.environ.get("TBRAIL_HOME", Path.home() / ".tbrail")).resolve()
DB_PATH = RAIL_HOME / "rail.db"
WORK_ROOT = RAIL_HOME / "work"
RECEIPT_ROOT = RAIL_HOME / "receipts"
SOURCE_ROOT = RAIL_HOME / "source"
CHECKPOINT_ROOT = RAIL_HOME / "checkpoints"
OPS_ROOT = HERE / "ops"
REPO_OPS_ROOT = HERE / "repo-ops"
# Neutral in-sandbox mount root. Host paths are never reproduced inside the
# worker, so the controller's home cannot appear even as an empty parent.
GUEST_ROOT = "/w"

TERMINAL_OK = "PASS"
TERMINAL_FAIL = "FAIL"
TERMINAL_HOLD = "HOLD"

ENVELOPE_SCHEMA = "tier-bench/native-transaction-envelope@3"
RECEIPT_SCHEMA = "tier-bench/native-transaction-receipt@3"
PROFILE_SCHEMA = "tier-bench/native-rail-runner-profile@1"
MANIFEST_SCHEMA = "tier-bench/repository-operation-manifest@1"

# ---- ceilings -------------------------------------------------------------
MAX_PHASES = 32
MAX_TIMEOUT = 1800
MAX_STR = 512
MAX_LIST = 64
MAX_IDENT = 64

# Owner-verified process identity dominates this TTL on the same host. The TTL
# only decides liveness where identity cannot be verified (a remote holder).
LEASE_TTL_SECONDS = 90.0
HEARTBEAT_SECONDS = 10.0

# Enforced resource ceilings. A phase may lower any of these; it may never
# raise one. Every value is applied to the child by the kernel or by an
# independent monitor, not merely recorded.
DEFAULT_LIMITS = {
    "max_output_bytes": 4 << 20,
    "cpu_seconds": 900,
    "address_space_bytes": 4 << 30,
    "file_size_bytes": 1 << 30,
    "open_files": 1024,
    # above the controller account's ambient process count, so the ceiling
    # constrains the phase rather than the host
    "max_processes": 512,
    "workspace_bytes": 8 << 30,
}
LIMIT_FIELDS = set(DEFAULT_LIMITS)
MAX_SETTLEMENT_PAUSE = 120

SAFE_IDENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,%d}$" % (MAX_IDENT - 1))
SAFE_RESOURCE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
SAFE_REPO = re.compile(r"^[A-Za-z0-9._-]{1,64}/[A-Za-z0-9._-]{1,64}$")
SAFE_RELPATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
SAFE_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63})*$")
SAFE_OPERATION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

RESERVED_IDENTS = {".", "..", "con", "prn", "aux", "nul"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS txn (
  txn_id        TEXT PRIMARY KEY,
  envelope_json TEXT NOT NULL,
  envelope_sha  TEXT NOT NULL,
  resource_key  TEXT NOT NULL,
  state         TEXT NOT NULL,
  terminal      TEXT,
  created_at    REAL NOT NULL,
  updated_at    REAL NOT NULL,
  receipt_path  TEXT
);
CREATE TABLE IF NOT EXISTS lease (
  resource_key   TEXT PRIMARY KEY,
  txn_id         TEXT NOT NULL,
  owner_uuid     TEXT NOT NULL,
  fence          INTEGER NOT NULL,
  host           TEXT NOT NULL,
  boot_id        TEXT NOT NULL,
  pid            INTEGER NOT NULL,
  pid_start      INTEGER NOT NULL,
  acquired_at    REAL NOT NULL,
  heartbeat_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fence_counter (
  resource_key TEXT PRIMARY KEY,
  value        INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS phase (
  txn_id     TEXT NOT NULL,
  idx        INTEGER NOT NULL,
  name       TEXT NOT NULL,
  op         TEXT NOT NULL,
  state      TEXT NOT NULL,
  attempt    INTEGER NOT NULL DEFAULT 1,
  exit_code  INTEGER,
  digest     TEXT,
  log_path   TEXT,
  started_at REAL,
  ended_at   REAL,
  ckpt_path  TEXT,
  ckpt_sha   TEXT,
  PRIMARY KEY (txn_id, idx)
);
"""


def now() -> float:
    return time.time()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------
# owner-only private custody
# --------------------------------------------------------------------------

DIR_MODE = 0o700
FILE_MODE = 0o600


def harden(path: Path) -> None:
    """Force owner-only permissions on a controller-owned path."""
    with contextlib.suppress(OSError):
        os.chmod(path, DIR_MODE if path.is_dir() else FILE_MODE)


def harden_tree(root: Path) -> None:
    if not root.exists():
        return
    harden(root)
    for p in root.rglob("*"):
        harden(p)


def private_custody_report() -> dict:
    """Observed permissions of every controller-private location."""
    items = {}
    ok = True
    for label, p in (("rail_home", RAIL_HOME), ("database", DB_PATH),
                     ("work_root", WORK_ROOT), ("receipt_root", RECEIPT_ROOT),
                     ("source_root", SOURCE_ROOT),
                     ("checkpoint_root", CHECKPOINT_ROOT)):
        if not p.exists():
            items[label] = {"present": False}
            continue
        st = p.stat()
        mode = st.st_mode & 0o777
        want = DIR_MODE if p.is_dir() else FILE_MODE
        good = (mode & 0o077) == 0 and mode <= want
        ok = ok and good
        items[label] = {"present": True, "mode": oct(mode), "owner_uid": st.st_uid,
                        "group_world_accessible": bool(mode & 0o077)}
    # sqlite writes -wal/-shm siblings; they carry the same content sensitivity
    for sib in (DB_PATH.parent.glob(DB_PATH.name + "-*") if DB_PATH.parent.exists() else []):
        mode = sib.stat().st_mode & 0o777
        good = (mode & 0o077) == 0
        ok = ok and good
        items[sib.name] = {"present": True, "mode": oct(mode),
                           "group_world_accessible": bool(mode & 0o077)}
    return {"property": "OWNER_ONLY_PRIVATE_CUSTODY", "owner_only": ok,
            "umask": oct(0o077), "paths": items}


def ensure_roots() -> None:
    os.umask(0o077)
    for d in (RAIL_HOME, WORK_ROOT, RECEIPT_ROOT, SOURCE_ROOT, CHECKPOINT_ROOT):
        d.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        harden(d)
    for p in (DB_PATH, DB_PATH.parent / (DB_PATH.name + "-wal"),
              DB_PATH.parent / (DB_PATH.name + "-shm")):
        if p.exists():
            harden(p)
    # retained private source custody must never be group or world readable
    if SOURCE_ROOT.is_dir():
        for p in SOURCE_ROOT.iterdir():
            harden(p)


def connect() -> sqlite3.Connection:
    ensure_roots()
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for p in (DB_PATH, DB_PATH.parent / (DB_PATH.name + "-wal"),
              DB_PATH.parent / (DB_PATH.name + "-shm")):
        if p.exists():
            harden(p)
    return conn


# --------------------------------------------------------------------------
# host identity
# --------------------------------------------------------------------------

def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown-boot"


def pid_start_ticks(pid: int) -> int | None:
    """Field 22 of /proc/<pid>/stat: process start time in clock ticks.

    PID plus start-ticks is a durable process identity; PID alone is reused.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # comm may contain spaces and parentheses; parse after the final ')'
    tail = raw[raw.rfind(")") + 2:].split()
    try:
        return int(tail[19])
    except (IndexError, ValueError):
        return None


def pids_in_group(pgid: int) -> list[int]:
    """Every live process whose process-group id matches -- descendant proof."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
        except OSError:
            continue
        tail = raw[raw.rfind(")") + 2:].split()
        try:
            if int(tail[2]) == pgid:
                found.append(int(entry.name))
        except (IndexError, ValueError):
            continue
    return sorted(found)


def tree_bytes(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


# --------------------------------------------------------------------------
# containment
# --------------------------------------------------------------------------

class Reject(Exception):
    pass


def check_ident(value, field: str) -> str:
    if not isinstance(value, str) or not SAFE_IDENT.match(value):
        raise Reject(f"bad_identifier:{field}")
    if value in RESERVED_IDENTS or ".." in value:
        raise Reject(f"reserved_identifier:{field}")
    return value


def check_relpath(value, field: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_STR:
        raise Reject(f"bad_path_type:{field}")
    if value.startswith("/") or "\\" in value:
        raise Reject(f"absolute_or_separator_path:{field}")
    if not SAFE_RELPATH.match(value):
        raise Reject(f"bad_path_grammar:{field}")
    parts = value.split("/")
    if any(p in (".", "..") for p in parts):
        raise Reject(f"dot_segment:{field}")
    return value


def resolve_under(root: Path, *parts: str) -> Path:
    """Resolve a derived path and prove it stays under root, symlinks included."""
    root_r = root.resolve()
    candidate = root_r.joinpath(*parts)
    resolved = Path(os.path.realpath(candidate))
    try:
        resolved.relative_to(root_r)
    except ValueError:
        raise Reject(f"path_escape:{candidate}")
    return resolved


def resolve_bind_source(repo: Path, rel: str) -> Path:
    """Resolve a bind source under the repository and refuse every escape.

    A source-controlled symlink or reparse point at an admitted subtree could
    otherwise change which host directory bubblewrap binds. Each component is
    checked, so a symlink in the middle of the path is refused too.
    """
    repo_r = Path(os.path.realpath(repo))
    if rel == "repo":
        return repo_r
    check_relpath(rel, "allowed_paths[]")
    cur = repo_r
    for part in rel.split("/"):
        cur = cur / part
        if os.path.islink(cur):
            raise Reject(f"symlink_bind_source_refused:{rel}")
    resolved = Path(os.path.realpath(cur))
    try:
        resolved.relative_to(repo_r)
    except ValueError:
        raise Reject(f"bind_source_escapes_repository:{rel}")
    if resolved != cur:
        raise Reject(f"bind_source_is_indirect:{rel}")
    if not cur.exists():
        raise Reject(f"bind_source_missing:{rel}")
    return resolved


# --------------------------------------------------------------------------
# pinned runtimes
# --------------------------------------------------------------------------

def _probe_runtime(path: str) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        ver = subprocess.run([str(p), "-V"], capture_output=True, text=True,
                             timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return {"path": str(p), "version": ver, "sha256": sha256_file(p)}


def _which_git() -> dict | None:
    g = shutil.which("git")
    if not g:
        return None
    real = Path(os.path.realpath(g))
    try:
        ver = subprocess.run([str(real), "--version"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return {"path": str(real), "version": ver, "sha256": sha256_file(real)}


RUNTIMES: dict[str, dict] = {}
for _rid, _p in (("python3.11", "/opt/tbrail/py311/bin/python3.11"),
                 ("python3.14", "/usr/bin/python3.14"),
                 ("python3.12", "/usr/bin/python3.12")):
    _info = _probe_runtime(_p)
    if _info:
        RUNTIMES[_rid] = _info
_g = _which_git()
if _g:
    RUNTIMES["git"] = _g

BWRAP = shutil.which("bwrap")


# --------------------------------------------------------------------------
# accepted repository-operation manifests
# --------------------------------------------------------------------------

VALUE_TYPES = {"repo_basename", "repo_relpath", "enum"}


def _load_manifests() -> dict[str, dict]:
    """Load every accepted repository-operation manifest shipped with the rail.

    A manifest is an admitted artifact. It fixes script identity, script digest
    and a closed per-operation parameter grammar. An envelope can never define
    a script, a digest, an argv or a switch.
    """
    out: dict[str, dict] = {}
    if not REPO_OPS_ROOT.is_dir():
        return out
    for p in sorted(REPO_OPS_ROOT.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("schema") != MANIFEST_SCHEMA:
            raise Reject(f"bad_manifest_schema:{p.name}")
        repo = data.get("repository")
        if not isinstance(repo, str) or not SAFE_REPO.match(repo):
            raise Reject(f"bad_manifest_repository:{p.name}")
        ops = data.get("operations")
        if not isinstance(ops, dict) or not ops:
            raise Reject(f"bad_manifest_operations:{p.name}")
        for op_id, spec in ops.items():
            if not SAFE_OPERATION.match(op_id):
                raise Reject(f"bad_manifest_operation_id:{op_id}")
            check_relpath(spec.get("script"), f"manifest.{op_id}.script")
            if not HEX64.match(str(spec.get("script_sha256", ""))):
                raise Reject(f"bad_manifest_script_sha:{op_id}")
            if not isinstance(spec.get("argv"), list):
                raise Reject(f"bad_manifest_argv:{op_id}")
            params = spec.get("params", {})
            if not isinstance(params, dict):
                raise Reject(f"bad_manifest_params:{op_id}")
            for pname, pspec in params.items():
                if not SAFE_OPERATION.match(pname):
                    raise Reject(f"bad_manifest_param_name:{op_id}.{pname}")
                if pspec.get("type") not in VALUE_TYPES:
                    raise Reject(f"bad_manifest_param_type:{op_id}.{pname}")
            for tok in spec["argv"]:
                if not isinstance(tok, str):
                    raise Reject(f"bad_manifest_argv_token:{op_id}")
                if tok.startswith("{") and tok.endswith("}") and tok[1:-1] not in params:
                    raise Reject(f"manifest_argv_unknown_placeholder:{op_id}:{tok}")
        data["_path"] = str(p)
        data["_sha256"] = sha256_file(p)
        out[repo] = data
    return out


MANIFESTS = _load_manifests()


def _check_value(name: str, spec: dict, value) -> str:
    if not isinstance(value, str) or not SAFE_VALUE.match(value):
        raise Reject(f"bad_operation_value:{name}")
    if value.startswith("-"):
        raise Reject(f"switch_shaped_value_refused:{name}")
    kind = spec["type"]
    if kind == "enum":
        if value not in spec.get("choices", []):
            raise Reject(f"value_not_in_enum:{name}")
        return value
    if kind == "repo_basename":
        if "/" in value:
            raise Reject(f"value_must_be_basename:{name}")
        check_relpath(value, f"value.{name}")
    else:
        check_relpath(value, f"value.{name}")
    suffix = spec.get("suffix")
    if suffix and not value.endswith(suffix):
        raise Reject(f"value_bad_suffix:{name}")
    if len(value) > int(spec.get("max_length", 128)):
        raise Reject(f"value_too_long:{name}")
    return value


def build_repo_operation(params, ctx):
    """Run an operation from the accepted manifest for this repository.

    The envelope supplies an operation id and typed values. Script path, script
    digest and every switch come from the manifest.
    """
    manifest = MANIFESTS.get(ctx["repository"])
    if manifest is None:
        raise Reject(f"repository_operations_not_admitted:{ctx['repository']}")
    op_id = params.get("operation")
    if not isinstance(op_id, str) or not SAFE_OPERATION.match(op_id):
        raise Reject("bad_param:operation")
    spec = manifest["operations"].get(op_id)
    if spec is None:
        raise Reject(f"operation_not_in_manifest:{op_id}")

    declared = spec.get("params", {})
    values = params.get("values", {})
    if not isinstance(values, dict):
        raise Reject("bad_param:values")
    unknown = sorted(set(values) - set(declared))
    if unknown:
        raise Reject(f"undeclared_operation_value:{unknown[0]}")
    missing = sorted(set(declared) - set(values))
    if missing:
        raise Reject(f"missing_operation_value:{missing[0]}")
    if set(params) - {"operation", "values"}:
        raise Reject("unknown_repo_operation_param")

    checked = {n: _check_value(n, declared[n], values[n]) for n in declared}

    rel = spec["script"]
    ctx["require_allowed"](rel)
    target = resolve_bind_source(ctx["repo"], rel)
    if not target.is_file():
        raise Reject(f"script_missing:{rel}")
    actual = sha256_file(target)
    if actual != spec["script_sha256"]:
        raise Reject(f"script_digest_mismatch:{rel}:{actual}")

    argv = [ctx["python"], "-B", rel]
    for tok in spec["argv"]:
        if tok.startswith("{") and tok.endswith("}"):
            argv.append(checked[tok[1:-1]])
        else:
            argv.append(tok)
    return argv


# --------------------------------------------------------------------------
# typed operation registry
# --------------------------------------------------------------------------

class Op:
    """An admitted operation. `build` turns typed params into argv.

    The envelope supplies params only. It never supplies argv, an executable,
    a switch, or a program body.
    """

    def __init__(self, op_id, kind, effect, build, network=False, script=None):
        self.op_id = op_id
        self.kind = kind            # "python" | "git" | "rail" | "repo"
        self.effect = effect        # "PURE" | "EFFECTFUL"
        self.build = build
        self.network = network
        self.script = script        # rail-shipped admitted script, digest-pinned


def _p_targets(params, ctx):
    targets = params.get("targets")
    if not isinstance(targets, list) or not targets or len(targets) > MAX_LIST:
        raise Reject("bad_param:targets")
    out = []
    for t in targets:
        rel = check_relpath(t, "targets[]")
        ctx["require_allowed"](rel)
        out.append(rel)
    return out


def build_py_compile(params, ctx):
    if set(params) - {"targets"}:
        raise Reject("unknown_param:py_compile")
    targets = _p_targets(params, ctx)
    return [ctx["python"], "-B", "-m", "py_compile", *targets]


def build_unittest(params, ctx):
    if set(params) - {"module", "verbose"}:
        raise Reject("unknown_param:unittest")
    mod = params.get("module")
    if not isinstance(mod, str) or not SAFE_MODULE.match(mod):
        raise Reject("bad_param:module")
    argv = [ctx["python"], "-B", "-m", "unittest"]
    if params.get("verbose") is True:
        argv.append("-v")
    elif "verbose" in params and params["verbose"] is not False:
        raise Reject("bad_param:verbose")
    return argv + [mod]


def build_git_diff(params, ctx):
    if params:
        raise Reject("bad_param:git_diff_takes_no_params")
    return [RUNTIMES["git"]["path"], "diff", "--exit-code"]


def _int_param(params, name, lo, hi):
    v = params.get(name)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise Reject(f"bad_param:{name}")
    return v


def _rail(ctx, script, *args):
    return [ctx["python"], "-B", str(ctx["ops_mount"] / script), *args]


def build_hold(params, ctx):
    return _rail(ctx, "hold_resource.py", str(_int_param(params, "seconds", 1, 600)))


def build_append(params, ctx):
    rel = check_relpath(params.get("target"), "target")
    ctx["require_allowed"](rel)
    return _rail(ctx, "append_byte.py", rel)


def build_cred_probe(params, ctx):
    if params:
        raise Reject("bad_param:credential_probe_takes_no_params")
    return _rail(ctx, "credential_probe.py")


def build_spawn_descendant(params, ctx):
    return _rail(ctx, "spawn_descendant.py",
                 str(_int_param(params, "seconds", 1, 600)))


def build_produce_artifact(params, ctx):
    rel = check_relpath(params.get("target"), "target")
    ctx["require_allowed"](rel)
    payload = params.get("payload")
    if not isinstance(payload, str) or not SAFE_VALUE.match(payload):
        raise Reject("bad_param:payload")
    return _rail(ctx, "produce_artifact.py", rel, payload)


def build_require_artifact(params, ctx):
    rel = check_relpath(params.get("target"), "target")
    ctx["require_allowed"](rel)
    want = params.get("sha256")
    if not isinstance(want, str) or not HEX64.match(want):
        raise Reject("bad_param:sha256")
    return _rail(ctx, "require_artifact.py", rel, want)


def build_burn_output(params, ctx):
    return _rail(ctx, "burn.py", "output",
                 str(_int_param(params, "megabytes", 1, 256)))


def build_burn_memory(params, ctx):
    return _rail(ctx, "burn.py", "memory",
                 str(_int_param(params, "megabytes", 1, 8192)))


def build_burn_disk(params, ctx):
    return _rail(ctx, "burn.py", "disk",
                 str(_int_param(params, "megabytes", 1, 8192)))


def build_burn_cpu(params, ctx):
    return _rail(ctx, "burn.py", "cpu",
                 str(_int_param(params, "seconds", 1, 600)))


def build_burn_pids(params, ctx):
    return _rail(ctx, "burn.py", "pids",
                 str(_int_param(params, "count", 1, 4096)))


OPS: dict[str, Op] = {
    "python.py_compile": Op("python.py_compile", "python", "PURE", build_py_compile),
    "python.unittest": Op("python.unittest", "python", "PURE", build_unittest),
    "repo.operation": Op("repo.operation", "repo", "PURE", build_repo_operation),
    "git.diff_exit_code": Op("git.diff_exit_code", "git", "PURE", build_git_diff),
    "rail.hold_resource": Op("rail.hold_resource", "rail", "PURE", build_hold,
                             script="hold_resource.py"),
    "rail.append_byte": Op("rail.append_byte", "rail", "EFFECTFUL", build_append,
                           script="append_byte.py"),
    "rail.credential_probe": Op("rail.credential_probe", "rail", "PURE",
                                build_cred_probe, script="credential_probe.py"),
    "rail.spawn_descendant": Op("rail.spawn_descendant", "rail", "PURE",
                                build_spawn_descendant, script="spawn_descendant.py"),
    "rail.produce_artifact": Op("rail.produce_artifact", "rail", "PURE",
                                build_produce_artifact, script="produce_artifact.py"),
    "rail.require_artifact": Op("rail.require_artifact", "rail", "PURE",
                                build_require_artifact, script="require_artifact.py"),
    "rail.burn_output": Op("rail.burn_output", "rail", "PURE", build_burn_output,
                           script="burn.py"),
    "rail.burn_memory": Op("rail.burn_memory", "rail", "PURE", build_burn_memory,
                           script="burn.py"),
    "rail.burn_disk": Op("rail.burn_disk", "rail", "PURE", build_burn_disk,
                         script="burn.py"),
    "rail.burn_cpu": Op("rail.burn_cpu", "rail", "PURE", build_burn_cpu,
                        script="burn.py"),
    "rail.burn_pids": Op("rail.burn_pids", "rail", "PURE", build_burn_pids,
                         script="burn.py"),
}


def ops_manifest() -> dict:
    """Digest every admitted rail script, runtime and repository manifest."""
    scripts = {}
    if OPS_ROOT.is_dir():
        for p in sorted(OPS_ROOT.glob("*.py")):
            scripts[p.name] = sha256_file(p)
    repos = {r: {"path": m["_path"], "sha256": m["_sha256"],
                 "operations": sorted(m["operations"])}
             for r, m in sorted(MANIFESTS.items())}
    return {"runtimes": RUNTIMES, "scripts": scripts, "repository_manifests": repos}


# --------------------------------------------------------------------------
# externally accepted runner profile
# --------------------------------------------------------------------------

def observed_profile() -> dict:
    """What this host actually is, as the controller can see it."""
    return {
        "schema": PROFILE_SCHEMA,
        "host": os.uname().nodename,
        "controller": {"path": str(SELF), "sha256": sha256_file(SELF)},
        "sandbox": {"engine": "bubblewrap", "path": BWRAP,
                    "sha256": sha256_file(Path(BWRAP)) if BWRAP else None},
        "guest_root": GUEST_ROOT,
        "ceilings": {"max_phases": MAX_PHASES, "max_timeout": MAX_TIMEOUT,
                     "lease_ttl_seconds": LEASE_TTL_SECONDS,
                     "heartbeat_seconds": HEARTBEAT_SECONDS,
                     "limits": DEFAULT_LIMITS},
        "operations": sorted(OPS),
        **ops_manifest(),
    }


class ProfileMismatch(Exception):
    pass


def profile_path(explicit: str | None) -> Path | None:
    for cand in (explicit, os.environ.get("TBRAIL_RUNNER_PROFILE"),
                 str(RAIL_HOME / "runner-profile.json"),
                 str(HERE / f"RUNNER-PROFILE.{os.uname().nodename}.json")):
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


def _diff_profile(accepted: dict, obs: dict, prefix="") -> list[str]:
    out = []
    for key in sorted(set(accepted) | set(obs)):
        if key.startswith("_"):
            continue
        a, b = accepted.get(key), obs.get(key)
        label = f"{prefix}{key}"
        if isinstance(a, dict) and isinstance(b, dict):
            out += _diff_profile(a, b, label + ".")
        elif a != b:
            out.append(label)
    return out


def enforce_profile(explicit: str | None, expect_sha: str | None) -> dict:
    """Admit this run against an externally accepted runner profile.

    Refuses to execute when the controller, sandbox engine, runtime closure,
    rail scripts, repository manifests or ceilings differ from the profile.
    """
    p = profile_path(explicit)
    if p is None:
        raise ProfileMismatch(
            "RUNNER_PROFILE_ABSENT: execution requires an accepted runner profile "
            "(--runner-profile / TBRAIL_RUNNER_PROFILE)")
    digest = sha256_file(p)
    want = expect_sha or os.environ.get("TBRAIL_RUNNER_PROFILE_SHA256")
    if want and want.strip() != digest:
        raise ProfileMismatch(
            f"RUNNER_PROFILE_DIGEST_MISMATCH: accepted={want.strip()} actual={digest}")
    accepted = json.loads(p.read_text(encoding="utf-8"))
    obs = observed_profile()
    drift = _diff_profile(accepted, obs)
    if drift:
        raise ProfileMismatch("RUNNER_PROFILE_MISMATCH: " + ",".join(drift[:8]))
    return {"path": str(p), "sha256": digest, "host": accepted.get("host"),
            "externally_pinned": bool(want), "verdict": "ADMITTED"}


# --------------------------------------------------------------------------
# envelope -- closed schema
# --------------------------------------------------------------------------

TOP_FIELDS = {
    "schema", "transaction_id", "repository", "visibility", "base_sha",
    "head_sha", "expected_tree", "coordinate", "trust_class", "runtime",
    "phases", "allowed_paths", "resource_key", "result_schema",
    "publication_ceiling", "source_bundle", "source_bundle_sha256",
}
PHASE_FIELDS = {"name", "op", "params", "timeout_seconds", "limits"}


def phase_limits(ph: dict) -> dict:
    """Merge a phase's declared limits over the defaults. Lowering only."""
    limits = dict(DEFAULT_LIMITS)
    for k, v in (ph.get("limits") or {}).items():
        limits[k] = v
    return limits


def validate_envelope(env) -> list[str]:
    errs: list[str] = []

    def bad(msg):
        errs.append(msg)

    if not isinstance(env, dict):
        return ["envelope_not_object"]

    unknown = sorted(set(env) - TOP_FIELDS)
    for u in unknown:
        bad(f"unknown_field:{u}")
    for missing in sorted(TOP_FIELDS - set(env)):
        bad(f"missing_field:{missing}")
    if errs:
        return errs

    if env["schema"] != ENVELOPE_SCHEMA:
        bad(f"bad_schema:{env['schema']}")
    try:
        check_ident(env["transaction_id"], "transaction_id")
    except Reject as exc:
        bad(str(exc))
    if not isinstance(env["repository"], str) or not SAFE_REPO.match(env["repository"]):
        bad("bad_repository")
    if env["visibility"] not in ("private", "public"):
        bad("bad_visibility")
    if env["trust_class"] != "TRUSTED_PRIVATE":
        bad("untrusted_class_forbidden_on_native_rail")
    if not isinstance(env["resource_key"], str) or not SAFE_RESOURCE.match(env["resource_key"]):
        bad("bad_resource_key")
    if env["publication_ceiling"] not in ("NONE", "STATUS_ONLY"):
        bad("bad_publication_ceiling")
    if env["runtime"] not in RUNTIMES or env["runtime"] == "git":
        bad(f"runtime_not_admitted:{env['runtime']}")
    for f in ("coordinate", "result_schema"):
        if not isinstance(env[f], str) or not 1 <= len(env[f]) <= MAX_STR:
            bad(f"bad_string:{f}")

    for f, rx in (("base_sha", HEX40), ("head_sha", HEX40),
                  ("expected_tree", HEX40), ("source_bundle_sha256", HEX64)):
        v = env[f]
        if not isinstance(v, str) or not rx.match(v):
            bad(f"bad_sha:{f}")

    # source bundle is a basename resolved under the admitted custody root
    sb = env["source_bundle"]
    if not isinstance(sb, str) or "/" in sb or "\\" in sb or not SAFE_RELPATH.match(sb):
        bad("source_bundle_must_be_basename_under_custody_root")
    else:
        try:
            resolve_under(SOURCE_ROOT, sb)
        except Reject as exc:
            bad(str(exc))

    ap = env["allowed_paths"]
    if not isinstance(ap, list) or not ap or len(ap) > MAX_LIST:
        bad("bad_allowed_paths")
    else:
        for a in ap:
            if a == "repo":
                continue
            try:
                check_relpath(a, "allowed_paths[]")
            except Reject as exc:
                bad(str(exc))

    phases = env["phases"]
    if not isinstance(phases, list) or not phases:
        bad("empty_phase_graph")
    elif len(phases) > MAX_PHASES:
        bad("too_many_phases")
    else:
        seen = set()
        for i, ph in enumerate(phases):
            if not isinstance(ph, dict):
                bad(f"phase_{i}_not_object")
                continue
            for u in sorted(set(ph) - PHASE_FIELDS):
                bad(f"phase_{i}_unknown_field:{u}")
            for m in sorted({"name", "op"} - set(ph)):
                bad(f"phase_{i}_missing:{m}")
            if "name" in ph:
                try:
                    check_ident(ph["name"], f"phase_{i}.name")
                except Reject as exc:
                    bad(str(exc))
                if ph.get("name") in seen:
                    bad(f"phase_{i}_duplicate_name")
                seen.add(ph.get("name"))
            if ph.get("op") not in OPS:
                bad(f"phase_{i}_op_not_admitted:{ph.get('op')}")
            if "params" in ph and not isinstance(ph["params"], dict):
                bad(f"phase_{i}_params_not_object")
            t = ph.get("timeout_seconds", 900)
            if not isinstance(t, int) or isinstance(t, bool) or not 1 <= t <= MAX_TIMEOUT:
                bad(f"phase_{i}_bad_timeout")
            lim = ph.get("limits", {})
            if not isinstance(lim, dict):
                bad(f"phase_{i}_limits_not_object")
            else:
                for k, v in sorted(lim.items()):
                    if k not in LIMIT_FIELDS:
                        bad(f"phase_{i}_unknown_limit:{k}")
                    elif not isinstance(v, int) or isinstance(v, bool) or v < 1:
                        bad(f"phase_{i}_bad_limit:{k}")
                    elif v > DEFAULT_LIMITS[k]:
                        bad(f"phase_{i}_limit_above_ceiling:{k}")
    return errs


# --------------------------------------------------------------------------
# fenced lease
# --------------------------------------------------------------------------

class LeaseTaken(Exception):
    pass


class FencedOut(Exception):
    pass


class Lease:
    """A fenced resource lease whose liveness is decided by process identity.

    On the granting host the holder's boot id, pid and process start ticks are
    checked directly, so a phase that runs longer than the TTL cannot be
    reclaimed while the holder is genuinely alive. The TTL only decides a
    holder whose identity this host cannot observe.
    """

    def __init__(self, conn, resource_key, txn_id):
        self.conn = conn
        self.resource_key = resource_key
        self.txn_id = txn_id
        self.owner = str(uuid.uuid4())
        self.fence = None
        self.last_beat = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.beats = 0

    # -- holder liveness -------------------------------------------------
    def _holder_dead(self, row) -> tuple[bool, str]:
        (_, _, _, _, host, hboot, hpid, hstart, _, hbeat) = row
        if host != os.uname().nodename:
            # identity is unobservable from here; only then does the TTL decide
            if now() - hbeat > LEASE_TTL_SECONDS:
                return True, "remote_holder_heartbeat_expired"
            return False, "holder_on_other_host"
        if hboot != boot_id():
            return True, "holder_boot_id_differs"
        start = pid_start_ticks(hpid)
        if start is None:
            return True, "holder_pid_absent"
        if start != hstart:
            return True, "holder_pid_reused"
        # verified live same-host holder: a stale heartbeat cannot evict it
        return False, "holder_alive_verified_process_identity"

    def acquire(self):
        conn = self.conn
        for _ in range(3):
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT resource_key,txn_id,owner_uuid,fence,host,boot_id,pid,"
                    "pid_start,acquired_at,heartbeat_at FROM lease WHERE resource_key=?",
                    (self.resource_key,)).fetchone()
                if row is not None:
                    dead, why = self._holder_dead(row)
                    if not dead:
                        holder_txn = row[1]
                        conn.execute("ROLLBACK")
                        raise LeaseTaken(
                            f"resource_key={self.resource_key} held by txn={holder_txn} "
                            f"pid={row[6]} ({why})")
                    conn.execute("DELETE FROM lease WHERE resource_key=?",
                                 (self.resource_key,))
                cur = conn.execute("SELECT value FROM fence_counter WHERE resource_key=?",
                                   (self.resource_key,)).fetchone()
                nxt = (cur[0] if cur else 0) + 1
                conn.execute(
                    "INSERT INTO fence_counter(resource_key,value) VALUES(?,?) "
                    "ON CONFLICT(resource_key) DO UPDATE SET value=excluded.value",
                    (self.resource_key, nxt))
                pid = os.getpid()
                conn.execute(
                    "INSERT INTO lease(resource_key,txn_id,owner_uuid,fence,host,boot_id,"
                    "pid,pid_start,acquired_at,heartbeat_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (self.resource_key, self.txn_id, self.owner, nxt,
                     os.uname().nodename, boot_id(), pid, pid_start_ticks(pid) or -1,
                     now(), now()))
                conn.execute("COMMIT")
                self.fence = nxt
                self.last_beat = now()
                return self
            except LeaseTaken:
                raise
            except sqlite3.OperationalError:
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute("ROLLBACK")
                time.sleep(0.2)
        raise LeaseTaken(f"resource_key={self.resource_key} contended")

    def beat(self, conn=None):
        (conn or self.conn).execute(
            "UPDATE lease SET heartbeat_at=? WHERE resource_key=? AND owner_uuid=?",
            (now(), self.resource_key, self.owner))
        self.last_beat = now()
        self.beats += 1

    def _heartbeat_loop(self):
        """Beat for the whole lifetime of the lease, including inside a phase."""
        conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
        try:
            while not self._stop.wait(HEARTBEAT_SECONDS / 2.0):
                if now() - self.last_beat >= HEARTBEAT_SECONDS:
                    with contextlib.suppress(sqlite3.Error):
                        self.beat(conn)
        finally:
            conn.close()

    def start_heartbeat(self):
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        return self

    def stop_heartbeat(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def assert_still_held(self):
        """Fencing check. A holder that lost its lease must not settle."""
        row = self.conn.execute(
            "SELECT owner_uuid, fence FROM lease WHERE resource_key=?",
            (self.resource_key,)).fetchone()
        if row is None or row[0] != self.owner or row[1] != self.fence:
            raise FencedOut(
                f"fencing_lost resource_key={self.resource_key} "
                f"mine=({self.owner},{self.fence}) current={row}")

    def release(self):
        self.stop_heartbeat()
        self.conn.execute(
            "DELETE FROM lease WHERE resource_key=? AND owner_uuid=?",
            (self.resource_key, self.owner))


# --------------------------------------------------------------------------
# source and cross-phase state
# --------------------------------------------------------------------------

def materialize_source(env: dict, ws: Path) -> tuple[bool, str]:
    try:
        bundle = resolve_under(SOURCE_ROOT, env["source_bundle"])
    except Reject as exc:
        return False, str(exc)
    if not bundle.is_file():
        return False, f"bundle_missing:{bundle.name}"
    actual = sha256_file(bundle)
    if actual != env["source_bundle_sha256"]:
        return False, f"bundle_digest_mismatch:{actual}"
    repo = ws / "repo"
    git = RUNTIMES["git"]["path"]
    r = subprocess.run([git, "clone", "--quiet", "--no-local", str(bundle), str(repo)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"clone_failed:{r.stderr.strip()[:200]}"
    co = subprocess.run([git, "-C", str(repo), "checkout", "--quiet", "--detach",
                         env["head_sha"]], capture_output=True, text=True)
    if co.returncode != 0:
        return False, f"checkout_failed:{co.stderr.strip()[:200]}"
    head = subprocess.run([git, "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    tree = subprocess.run([git, "-C", str(repo), "rev-parse", "HEAD^{tree}"],
                          capture_output=True, text=True).stdout.strip()
    if head != env["head_sha"]:
        return False, f"head_mismatch:{head}"
    if tree != env["expected_tree"]:
        return False, f"tree_mismatch:{tree}"
    return True, f"bound head={head} tree={tree}"


def checkpoint_path(txn_id: str, idx: int) -> Path:
    d = resolve_under(CHECKPOINT_ROOT, txn_id)
    d.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    harden(d)
    return d / f"{idx:02d}.tar"


def write_checkpoint(txn_id: str, idx: int, ws: Path) -> tuple[str, str]:
    """Capture the workspace a PASSed phase produced.

    Cross-phase state law: a later phase may depend on files an earlier phase
    created, so recovery restores the last checkpoint rather than recloning
    pristine source.
    """
    path = checkpoint_path(txn_id, idx)
    tmp = path.with_suffix(".tar.partial")
    with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tf:
        tf.add(str(ws), arcname=".", recursive=True)
    os.replace(tmp, path)
    harden(path)
    return str(path), sha256_file(path)


def restore_checkpoint(path: Path, digest: str, ws: Path) -> None:
    if not path.is_file():
        raise Reject(f"checkpoint_missing:{path.name}")
    actual = sha256_file(path)
    if actual != digest:
        raise Reject(f"checkpoint_digest_drift:{path.name}:{actual}")
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    try:
        with tarfile.open(path, "r") as tf:
            try:
                tf.extractall(str(ws), filter="fully_trusted")
            except TypeError:  # python < 3.12 has no extraction filters
                tf.extractall(str(ws))
    except tarfile.TarError as exc:
        raise Reject(f"checkpoint_unreadable:{path.name}:{exc}")


def purge_checkpoints(txn_id: str) -> int:
    d = CHECKPOINT_ROOT / txn_id
    n = 0
    if d.is_dir():
        n = len(list(d.glob("*.tar")))
        shutil.rmtree(d, ignore_errors=True)
    return n


# --------------------------------------------------------------------------
# sandboxed execution
# --------------------------------------------------------------------------

def sandbox_argv(env: dict, ws: Path, inner: list[str], network: bool) -> list[str]:
    """Build the bubblewrap wrapper that ENFORCES allowed_paths and net policy.

    Only the declared repo subtrees are writable, only pinned runtime trees are
    readable, and the controller's own home -- where credentials would live --
    is not mounted at all. Every bind source is resolved under the repository
    first, so a source-controlled symlink cannot redirect a mount.
    """
    if not BWRAP:
        raise Reject("bubblewrap_missing_cannot_enforce_allowed_paths")
    repo = ws / "repo"
    argv = [
        BWRAP,
        "--unshare-all", "--die-with-parent", "--new-session",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
    ]
    if network:
        argv.insert(1, "--share-net")
    rt = RUNTIMES[env["runtime"]]["path"]
    for tree in {str(Path(rt).parents[1]), str(Path(RUNTIMES["git"]["path"]).parents[1])}:
        if tree not in ("/usr", "/"):
            argv += ["--ro-bind", tree, tree]
    # The workspace is mounted at a NEUTRAL path, never at its host path, so the
    # controller's home directory does not exist inside the sandbox even as an
    # empty parent stub of the workspace.
    argv += ["--ro-bind", str(OPS_ROOT), f"{GUEST_ROOT}/ops"]
    # writable set = exactly the declared allowed_paths under the repo
    argv += ["--bind", str(ws / "home"), f"{GUEST_ROOT}/home"]
    for rel in env["allowed_paths"]:
        source = resolve_bind_source(repo, rel)
        guest = f"{GUEST_ROOT}/repo" if rel == "repo" else f"{GUEST_ROOT}/repo/{rel}"
        argv += ["--bind", str(source), guest]
    argv += ["--chdir", f"{GUEST_ROOT}/repo"]
    for k, v in worker_env().items():
        argv += ["--setenv", k, v]
    return argv + ["--"] + inner


def worker_env() -> dict:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": f"{GUEST_ROOT}/home",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def rlimit_setter(limits: dict):
    """Apply kernel-enforced ceilings to the child before it execs."""
    cpu = int(limits["cpu_seconds"])
    addr = int(limits["address_space_bytes"])
    fsize = int(limits["file_size_bytes"])
    nofile = int(limits["open_files"])
    nproc = int(limits["max_processes"])

    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
        resource.setrlimit(resource.RLIMIT_AS, (addr, addr))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
    return apply


def teardown_group(pgid: int) -> dict:
    """Kill the whole process group, then prove descendant absence."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, sig)
        deadline = time.time() + 5
        while time.time() < deadline:
            if not pids_in_group(pgid):
                return {"pgid": pgid, "signal": sig.name, "survivors": []}
            time.sleep(0.1)
    return {"pgid": pgid, "signal": "SIGKILL", "survivors": pids_in_group(pgid)}


def _pump_output(stream, log_path: Path, cap: int, state: dict, pgid: int):
    """Stream child output to disk under a hard ceiling.

    The controller never accumulates the child's output in memory, and a child
    that exceeds the ceiling is torn down rather than merely truncated.
    """
    with open(log_path, "wb") as fh:
        harden(log_path)
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            room = cap - state["recorded"]
            if room > 0:
                fh.write(chunk[:room])
                fh.flush()
                state["recorded"] += min(room, len(chunk))
            state["total"] += len(chunk)
            if state["total"] > cap and not state["ceiling_hit"]:
                state["ceiling_hit"] = True
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pgid, signal.SIGKILL)


def _monitor(pgid: int, ws: Path, limits: dict, state: dict, stop: threading.Event):
    """Independent enforcement of process-count and workspace-byte ceilings."""
    max_pids = int(limits["max_processes"])
    max_bytes = int(limits["workspace_bytes"])
    last_disk = 0.0
    while not stop.wait(0.25):
        pids = pids_in_group(pgid)
        state["peak_pids"] = max(state.get("peak_pids", 0), len(pids))
        if len(pids) > max_pids:
            state["pid_ceiling_hit"] = True
            teardown_group(pgid)
            return
        if time.time() - last_disk > 2.0:
            last_disk = time.time()
            used = tree_bytes(ws)
            state["peak_workspace_bytes"] = max(
                state.get("peak_workspace_bytes", 0), used)
            if used > max_bytes:
                state["workspace_ceiling_hit"] = True
                teardown_group(pgid)
                return


def run_one_phase(env, ws, log_path: Path, ph: dict, ctx) -> dict:
    op = OPS[ph["op"]]
    params = dict(ph.get("params") or {})
    limits = phase_limits(ph)
    inner = op.build(params, ctx)
    argv = sandbox_argv(env, ws, inner, op.network)
    timeout = int(ph.get("timeout_seconds", 900))
    started = now()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, cwd=str(ws),
                            preexec_fn=rlimit_setter(limits))
    pgid = os.getpgid(proc.pid)
    pump_state = {"total": 0, "recorded": 0, "ceiling_hit": False}
    mon_state: dict = {}
    stop = threading.Event()
    pump = threading.Thread(target=_pump_output,
                            args=(proc.stdout, log_path, int(limits["max_output_bytes"]),
                                  pump_state, pgid), daemon=True)
    mon = threading.Thread(target=_monitor, args=(pgid, ws, limits, mon_state, stop),
                           daemon=True)
    pump.start()
    mon.start()
    timed_out = False
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        teardown_group(pgid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
        code = 124
    stop.set()
    pump.join(timeout=15)
    mon.join(timeout=5)
    with contextlib.suppress(Exception):
        proc.stdout.close()
    # bounded teardown on the normal path too, then prove absence independently
    td = teardown_group(pgid)

    enforcement = {
        "limits": limits,
        "output_ceiling_hit": pump_state["ceiling_hit"],
        "output_bytes_total": pump_state["total"],
        "output_bytes_recorded": pump_state["recorded"],
        "pid_ceiling_hit": bool(mon_state.get("pid_ceiling_hit")),
        "peak_pids": mon_state.get("peak_pids", 0),
        "workspace_ceiling_hit": bool(mon_state.get("workspace_ceiling_hit")),
        "peak_workspace_bytes": mon_state.get("peak_workspace_bytes", 0),
        "signal": -code if code is not None and code < 0 else None,
    }
    if timed_out:
        with open(log_path, "ab") as fh:
            fh.write(f"\nphase_timeout after {timeout}s; teardown={td}\n".encode())
    if enforcement["output_ceiling_hit"]:
        with open(log_path, "ab") as fh:
            fh.write(b"\nOUTPUT_CEILING_EXCEEDED: child torn down\n")
    breached = (enforcement["output_ceiling_hit"] or enforcement["pid_ceiling_hit"]
                or enforcement["workspace_ceiling_hit"])
    state = "PASS" if (code == 0 and not breached) else "FAIL"
    return {
        "index": ph["_idx"], "name": ph["name"], "op": ph["op"],
        "argv_shape": [Path(inner[0]).name] + inner[1:4],
        "exit_code": code, "state": state,
        "output_sha256": sha256_file(log_path) if log_path.is_file() else None,
        "output_bytes": pump_state["recorded"],
        "log_path": str(log_path), "seconds": round(now() - started, 3),
        "timed_out": timed_out, "teardown": td, "replayed": False,
        "enforcement": enforcement,
    }


def run_phases(conn, env, ws, log_dir: Path, lease: Lease,
               resume_from: int) -> tuple[str, list[dict]]:
    repo = ws / "repo"
    txn = env["transaction_id"]
    allowed = set(env["allowed_paths"])

    def require_allowed(rel: str):
        # a path parameter must be an allowed subtree or live inside one
        if "repo" in allowed:
            return
        for a in allowed:
            if rel == a or rel.startswith(a + "/"):
                return
        raise Reject(f"path_not_in_allowed_paths:{rel}")

    ctx = {
        "python": RUNTIMES[env["runtime"]]["path"],
        "repo": repo,
        "repository": env["repository"],
        "ops_mount": Path(f"{GUEST_ROOT}/ops"),
        "require_allowed": require_allowed,
    }

    journal = {r[0]: r for r in conn.execute(
        "SELECT idx,name,op,state,attempt,exit_code,digest,log_path,ckpt_path,ckpt_sha "
        "FROM phase WHERE txn_id=?", (txn,))}

    results, terminal = [], TERMINAL_OK
    for idx, ph in enumerate(env["phases"]):
        ph = dict(ph)
        ph["_idx"] = idx
        prior = journal.get(idx)

        # ---- crash-recovery law -------------------------------------------
        if prior and prior[3] == "PASS":
            results.append({
                "index": idx, "name": prior[1], "op": prior[2], "exit_code": prior[5],
                "state": "PASS", "output_sha256": prior[6], "log_path": prior[7],
                "replayed": True,
                "workspace_restored_from_checkpoint": idx == resume_from - 1,
                "note": "recovered_from_journal_not_re_executed",
            })
            continue
        if prior and prior[3] == "RUNNING":
            if OPS[ph["op"]].effect == "EFFECTFUL":
                results.append({
                    "index": idx, "name": ph["name"], "op": ph["op"],
                    "state": "HOLD", "exit_code": None, "replayed": False,
                    "note": "CRASH_RECOVERY_AMBIGUOUS_EFFECTFUL_PHASE",
                })
                return TERMINAL_HOLD, results

        attempt = (prior[4] + 1) if prior else 1
        started = now()
        conn.execute(
            "INSERT INTO phase(txn_id,idx,name,op,state,attempt,started_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(txn_id,idx) DO UPDATE SET state=excluded.state, "
            "attempt=excluded.attempt, started_at=excluded.started_at",
            (txn, idx, ph["name"], ph["op"], "RUNNING", attempt, started))
        lease.beat()

        log_path = resolve_under(log_dir, f"{idx:02d}-{ph['name']}.log")
        try:
            res = run_one_phase(env, ws, log_path, ph, ctx)
        except Reject as exc:
            res = {"index": idx, "name": ph["name"], "op": ph["op"], "exit_code": None,
                   "state": "HOLD", "note": f"OPERATION_REJECTED:{exc}", "replayed": False}
            conn.execute("UPDATE phase SET state=?, ended_at=? WHERE txn_id=? AND idx=?",
                         ("HOLD", now(), txn, idx))
            results.append(res)
            return TERMINAL_HOLD, results

        res["attempt"] = attempt
        ckpt_path = ckpt_sha = None
        if res["state"] == "PASS":
            # cross-phase state law: capture what this phase produced
            ckpt_path, ckpt_sha = write_checkpoint(txn, idx, ws)
            res["checkpoint"] = {"path": ckpt_path, "sha256": ckpt_sha}
        conn.execute(
            "UPDATE phase SET state=?, exit_code=?, digest=?, log_path=?, ended_at=?, "
            "ckpt_path=?, ckpt_sha=? WHERE txn_id=? AND idx=?",
            (res["state"], res["exit_code"], res["output_sha256"], res["log_path"],
             now(), ckpt_path, ckpt_sha, txn, idx))
        lease.beat()
        results.append(res)
        if res["state"] != "PASS":
            terminal = TERMINAL_FAIL
            break
    return terminal, results


def sanitize(ws: Path) -> dict:
    """Delete the workspace. ws is always a resolved path under WORK_ROOT."""
    ws_r = Path(os.path.realpath(ws))
    try:
        ws_r.relative_to(WORK_ROOT.resolve())
    except ValueError:
        raise Reject(f"refusing_to_delete_outside_work_root:{ws_r}")
    existed = ws_r.exists()
    if existed:
        shutil.rmtree(ws_r, ignore_errors=True)
    return {"workspace": str(ws_r), "existed": existed, "absent_after": not ws_r.exists()}


# --------------------------------------------------------------------------
# transaction
# --------------------------------------------------------------------------

def submit(conn, env: dict) -> str:
    errs = validate_envelope(env)
    if errs:
        raise SystemExit("ENVELOPE_REJECTED " + json.dumps(sorted(errs)))
    txn_id = env["transaction_id"]
    esha = sha256_bytes(canonical(env).encode())
    existing = conn.execute("SELECT state, terminal FROM txn WHERE txn_id=?",
                            (txn_id,)).fetchone()
    if existing:
        return f"ALREADY_PRESENT state={existing[0]} terminal={existing[1]}"
    conn.execute("INSERT INTO txn(txn_id,envelope_json,envelope_sha,resource_key,"
                 "state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                 (txn_id, canonical(env), esha, env["resource_key"], "QUEUED",
                  now(), now()))
    return f"QUEUED {txn_id}"


def retained_source_custody() -> dict:
    """Retained controller source custody, reported separately from residue."""
    items = []
    owner_only = True
    if SOURCE_ROOT.is_dir():
        for p in sorted(SOURCE_ROOT.iterdir()):
            if p.is_file():
                st = p.stat()
                mode = st.st_mode & 0o777
                owner_only = owner_only and not (mode & 0o077)
                items.append({
                    "name": p.name, "bytes": st.st_size,
                    "sha256": sha256_file(p), "mode": oct(mode),
                    "owner_uid": st.st_uid,
                })
    return {
        "root": str(SOURCE_ROOT),
        "owner": "tier-bench native rail controller (octo-n01 local account)",
        "items": items,
        "total_bytes": sum(i["bytes"] for i in items),
        "owner_only": owner_only,
        "encrypted_at_rest": False,
        "confidentiality": "owner-only filesystem permissions on a single-tenant "
                           "controller account; not encrypted at rest",
        "quota_bytes": 5 << 30,
        "retention": "until the bound transaction is settled and its receipt is "
                     "externally anchored; purge with `tbrail purge-source`",
        "purge_law": "an item may be purged when no QUEUED or RUNNING transaction "
                     "references its digest",
    }


def _resume_plan(conn, txn_id: str) -> tuple[int, dict | None]:
    """Where to resume, and which checkpoint restores the state to resume onto."""
    rows = conn.execute(
        "SELECT idx,state,ckpt_path,ckpt_sha FROM phase WHERE txn_id=? ORDER BY idx",
        (txn_id,)).fetchall()
    last_pass = None
    for idx, state, cpath, csha in rows:
        if state == "PASS":
            last_pass = (idx, cpath, csha)
        else:
            break
    if last_pass is None:
        return 0, None
    idx, cpath, csha = last_pass
    if not cpath or not csha:
        raise Reject(f"checkpoint_absent_for_passed_phase:{idx}")
    return idx + 1, {"index": idx, "path": cpath, "sha256": csha}


def execute(conn, txn_id: str, profile: dict, pause: int = 0) -> dict:
    try:
        check_ident(txn_id, "txn_id")
    except Reject as exc:
        raise SystemExit(f"REJECTED {exc}")
    row = conn.execute("SELECT envelope_json, state, terminal, receipt_path "
                       "FROM txn WHERE txn_id=?", (txn_id,)).fetchone()
    if not row:
        raise SystemExit(f"UNKNOWN_TXN {txn_id}")
    env_json, state, terminal, receipt_path = row
    env = json.loads(env_json)

    if state == "SETTLED":
        return {"replay": True, "terminal": terminal, "receipt": receipt_path,
                "note": "already settled; no duplicate execution"}

    ws = resolve_under(WORK_ROOT, txn_id)
    receipt_dir = resolve_under(RECEIPT_ROOT, txn_id)
    log_dir = receipt_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    harden(receipt_dir)
    harden(log_dir)

    lease = Lease(conn, env["resource_key"], txn_id)
    started = now()
    try:
        lease.acquire()
    except LeaseTaken as exc:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("HELD", now(), txn_id))
        return {"terminal": TERMINAL_HOLD, "reason": "COLLISION_HELD",
                "detail": str(exc), "executed": False}
    lease.start_heartbeat()

    recovery = {"resumed": False}
    try:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("RUNNING", now(), txn_id))
        resume_from, ckpt = _resume_plan(conn, txn_id)
        if ws.exists():
            sanitize(ws)
        (ws / "home").mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        ok, detail = materialize_source(env, ws)
        if ok and ckpt is not None:
            # restore the state the completed phases produced, then continue
            restore_checkpoint(Path(ckpt["path"]), ckpt["sha256"], ws)
            recovery = {"resumed": True, "resume_from_phase": resume_from,
                        "restored_checkpoint": ckpt}
        if not ok:
            terminal, phases = TERMINAL_HOLD, []
            bind = {"bound": False, "detail": detail}
        else:
            bind = {"bound": True, "detail": detail}
            terminal, phases = run_phases(conn, env, ws, log_dir, lease, resume_from)
        lease.assert_still_held()
    except FencedOut as exc:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("FENCED_OUT", now(), txn_id))
        sanitize(ws)
        lease.release()
        return {"terminal": TERMINAL_HOLD, "reason": "FENCED_OUT",
                "detail": str(exc), "settled": False}
    except Reject as exc:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("HELD", now(), txn_id))
        sanitize(ws)
        lease.release()
        return {"terminal": TERMINAL_HOLD, "reason": "RECOVERY_REFUSED",
                "detail": str(exc), "settled": False}
    except BaseException:
        lease.release()
        raise

    # ---- settlement, all of it under the lease ---------------------------
    try:
        return _settle(conn, env, txn_id, ws, receipt_dir, phases, terminal, bind,
                       recovery, lease, profile, pause, started)
    except BaseException:
        lease.release()
        raise


def _settle(conn, env, txn_id, ws, receipt_dir, phases, terminal, bind, recovery,
            lease, profile, pause, started) -> dict:
    sanitation = sanitize(ws)
    checkpoints_purged = purge_checkpoints(txn_id)
    envelope_clean = {k: v for k, v in env.items() if not k.startswith("_")}
    (receipt_dir / "ENVELOPE.json").write_text(canonical(envelope_clean), encoding="utf-8")
    harden(receipt_dir / "ENVELOPE.json")

    log_bindings = []
    for p in phases:
        lp = p.get("log_path")
        if lp and Path(lp).is_file():
            log_bindings.append({"index": p["index"], "path": lp,
                                 "sha256": sha256_file(Path(lp))})

    # The receipt is written before the SETTLED update, so it binds the
    # transaction's immutable identity and its terminal, and asserts the state
    # the ledger must hold once settlement completes.
    ledger = {
        "txn_id": txn_id,
        "resource_key": env["resource_key"],
        "expected_state_after_settlement": "SETTLED",
        "envelope_sha256": sha256_bytes(canonical(envelope_clean).encode()),
        "terminal": terminal,
        "phase_rows": [list(r) for r in conn.execute(
            "SELECT idx,name,op,state,attempt,exit_code,digest FROM phase "
            "WHERE txn_id=? ORDER BY idx", (txn_id,))],
        "lease_fence_granted": lease.fence,
    }

    residue = {
        "property": "ZERO_TRANSACTION_EXECUTION_RESIDUE",
        "expected_lease_rows_after_release": 0,
        "workspace_absent": sanitation["absent_after"],
        "checkpoints_purged": checkpoints_purged,
        "descendants_remaining": sum(len(p.get("teardown", {}).get("survivors", []))
                                     for p in phases),
        "worker_credential_present": False,
        "worker_home_mounted": False,
        "note": "scope is transaction execution state only; retained controller "
                "source custody is reported separately and is NOT zero",
    }

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "transaction_id": txn_id,
        "envelope_sha256": sha256_bytes(canonical(envelope_clean).encode()),
        "repository": env["repository"],
        "visibility": env["visibility"],
        "coordinate": env["coordinate"],
        "trust_class": env["trust_class"],
        "runtime": {"id": env["runtime"], **RUNTIMES[env["runtime"]]},
        "revision": {"base_sha": env["base_sha"], "head_sha": env["head_sha"],
                     "expected_tree": env["expected_tree"]},
        "source": {"mode": "verified_exact_sha_bundle_under_custody_root",
                   "bundle": env["source_bundle"],
                   "bundle_sha256": env["source_bundle_sha256"],
                   "network_used": False, "credential_used": False},
        "binding": bind,
        "recovery": recovery,
        "phases": phases,
        "phase_log_bindings": log_bindings,
        "ops_manifest": ops_manifest(),
        "runner_profile": profile,
        "ledger": ledger,
        "terminal": terminal,
        "hosted_runner_minutes": 0,
        "provider_calls": 0,
        "sandbox": {"engine": "bubblewrap", "path": BWRAP, "network": "unshared",
                    "writable_set": env["allowed_paths"],
                    "controller_home_mounted": False,
                    "bind_sources": "resolved under the repository; symlink, "
                                    "reparse and out-of-tree sources refused"},
        "lease_law": {
            "held_through": "workspace sanitation, receipt and sidecar publication, "
                            "and the verified atomic transition to SETTLED",
            "liveness": "verified same-host process identity dominates the TTL",
            "heartbeats": lease.beats,
            "fence": lease.fence,
        },
        "cross_phase_state_law": {
            "mode": "CHECKPOINT_AND_RESTORE",
            "statement": "each PASSed phase checkpoints the workspace; recovery "
                         "restores the last checkpoint instead of recloning "
                         "pristine source, so artifact-producing phases survive",
        },
        "sanitation": sanitation,
        "residency": residue,
        "private_custody": private_custody_report(),
        "retained_source_custody": retained_source_custody(),
        "test_hooks": {"settlement_pause_seconds": int(pause)},
        "timing": {"started": started, "ended": now(),
                   "seconds": round(now() - started, 3)},
        "controller": {"host": os.uname().nodename, "boot_id": boot_id(),
                       "pid": os.getpid(), "rail_home": str(RAIL_HOME)},
    }
    rpath = receipt_dir / "RECEIPT.json"
    rpath.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    digest = sha256_file(rpath)
    (receipt_dir / "RECEIPT.sha256").write_text(digest + "\n", encoding="utf-8")
    harden(rpath)
    harden(receipt_dir / "RECEIPT.sha256")

    # still ours immediately before the transition, and verified after it
    lease.assert_still_held()
    conn.execute("UPDATE txn SET state=?, terminal=?, receipt_path=?, updated_at=? "
                 "WHERE txn_id=?", ("SETTLED", terminal, str(rpath), now(), txn_id))
    settled = conn.execute("SELECT state, terminal FROM txn WHERE txn_id=?",
                           (txn_id,)).fetchone()
    if settled != ("SETTLED", terminal):
        lease.release()
        raise SystemExit(f"SETTLEMENT_NOT_VERIFIED {settled}")
    lease.assert_still_held()

    # observation window: an external contender must still be refused here
    if pause:
        time.sleep(min(int(pause), MAX_SETTLEMENT_PAUSE))

    lease.release()
    receipt["receipt_sha256"] = digest
    return receipt


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def terminal_is_consistent(data: dict) -> tuple[bool, dict]:
    """Evidence validity is independent of outcome.

    A PASS, FAIL or HOLD receipt is all equally valid evidence; what must hold
    is that the recorded terminal is the one the phase states imply.
    """
    phases = data.get("phases", [])
    terminal = data.get("terminal")
    states = [p.get("state") for p in phases]
    bound = (data.get("binding") or {}).get("bound", True)
    detail = {"terminal": terminal, "phase_states": states, "source_bound": bound}
    if not bound:
        return terminal == TERMINAL_HOLD and not phases, detail
    if not phases:
        return False, detail
    if terminal == TERMINAL_OK:
        return all(s == "PASS" for s in states), detail
    if terminal == TERMINAL_FAIL:
        return states[-1] == "FAIL" and all(s == "PASS" for s in states[:-1]), detail
    if terminal == TERMINAL_HOLD:
        return states[-1] == "HOLD" and all(s == "PASS" for s in states[:-1]), detail
    return False, detail


def verify_receipt(path: Path, anchor: str | None = None) -> dict:
    """Recompute every digest the receipt binds, in a fresh process.

    Consults an external anchor for terminal receipt identity when supplied,
    so a self-consistent forged receipt+sidecar pair cannot pass alone.
    """
    checks: dict[str, object] = {}
    failures: list[str] = []

    def rec(name, ok, detail=None):
        checks[name] = {"pass": bool(ok), "detail": detail}
        if not ok:
            failures.append(name)

    data = json.loads(path.read_text(encoding="utf-8"))
    d = path.parent

    sidecar = d / "RECEIPT.sha256"
    expect = sidecar.read_text().strip() if sidecar.is_file() else None
    actual = sha256_file(path)
    rec("receipt_digest_matches_sidecar", expect == actual,
        {"expected": expect, "actual": actual})

    env_path = d / "ENVELOPE.json"
    if env_path.is_file():
        env_sha = sha256_bytes(env_path.read_bytes())
        stored = json.loads(env_path.read_text(encoding="utf-8"))
        rec("envelope_recomputes",
            env_sha == data["envelope_sha256"]
            and sha256_bytes(canonical(stored).encode()) == data["envelope_sha256"],
            {"expected": data["envelope_sha256"], "actual": env_sha})
        rec("envelope_revalidates_against_closed_schema",
            validate_envelope(stored) == [], {"errors": validate_envelope(stored)[:6]})
    else:
        rec("envelope_recomputes", False, "ENVELOPE.json missing")
        rec("envelope_revalidates_against_closed_schema", False, "ENVELOPE.json missing")

    bad_logs = []
    for b in data.get("phase_log_bindings", []):
        lp = Path(b["path"])
        if not lp.is_file():
            bad_logs.append({"index": b["index"], "why": "missing"})
        elif sha256_file(lp) != b["sha256"]:
            bad_logs.append({"index": b["index"], "why": "digest_mismatch"})
    rec("phase_logs_rehash", not bad_logs, {"bad": bad_logs})

    src = data.get("source", {})
    bundle = SOURCE_ROOT / src.get("bundle", "")
    if bundle.is_file():
        rec("source_bundle_rehashes", sha256_file(bundle) == src["bundle_sha256"],
            {"expected": src["bundle_sha256"]})
    else:
        rec("source_bundle_rehashes", False, f"bundle absent: {src.get('bundle')}")

    man = data.get("ops_manifest", {})
    drift = []
    for name, sha in (man.get("scripts") or {}).items():
        p = OPS_ROOT / name
        if not p.is_file() or sha256_file(p) != sha:
            drift.append(name)
    for rid, info in (man.get("runtimes") or {}).items():
        p = Path(info["path"])
        if not p.is_file() or sha256_file(p) != info["sha256"]:
            drift.append(rid)
    for repo, info in (man.get("repository_manifests") or {}).items():
        p = Path(info["path"])
        if not p.is_file() or sha256_file(p) != info["sha256"]:
            drift.append(repo)
    rec("ops_and_runtimes_unchanged", not drift, {"drifted": drift})

    prof = data.get("runner_profile") or {}
    pp = Path(prof.get("path", ""))
    rec("runner_profile_still_matches",
        bool(prof) and pp.is_file() and sha256_file(pp) == prof.get("sha256"),
        {"profile": prof.get("path"), "expected": prof.get("sha256")})

    if DB_PATH.is_file():
        conn = sqlite3.connect(DB_PATH, timeout=30)
        trow = conn.execute(
            "SELECT txn_id,state,resource_key,terminal,envelope_sha FROM txn "
            "WHERE txn_id=?", (data["transaction_id"],)).fetchone()
        prows = [list(r) for r in conn.execute(
            "SELECT idx,name,op,state,attempt,exit_code,digest FROM phase "
            "WHERE txn_id=? ORDER BY idx", (data["transaction_id"],))]
        leases = conn.execute("SELECT COUNT(*) FROM lease WHERE txn_id=?",
                              (data["transaction_id"],)).fetchone()[0]
        led = data.get("ledger", {})
        tid, tstate, tres, tterm, tesha = (trow or (None,) * 5)
        rec("ledger_binds",
            tid == led.get("txn_id")
            and tres == led.get("resource_key")
            and tstate == led.get("expected_state_after_settlement")
            and tterm == led.get("terminal") == data["terminal"]
            and tesha == led.get("envelope_sha256") == data["envelope_sha256"]
            and prows == led.get("phase_rows"),
            {"db_state": tstate, "db_terminal": tterm,
             "receipt_terminal": data["terminal"],
             "envelope_sha_matches": tesha == data["envelope_sha256"],
             "phase_rows_match": prows == led.get("phase_rows")})
        rec("lease_released_after_settlement", leases == 0, {"lease_rows": leases})
    else:
        rec("ledger_binds", False, "rail.db absent")
        rec("lease_released_after_settlement", False, "rail.db absent")

    ws = Path(data["sanitation"]["workspace"])
    ckpt_dir = CHECKPOINT_ROOT / data["transaction_id"]
    rec("no_execution_residue",
        not ws.exists() and data["residency"]["descendants_remaining"] == 0
        and not ckpt_dir.exists(),
        {"workspace_present": ws.exists(), "checkpoints_present": ckpt_dir.exists()})

    ok_term, term_detail = terminal_is_consistent(data)
    rec("terminal_consistent_with_phases", ok_term, term_detail)

    custody = private_custody_report()
    rec("private_custody_owner_only",
        custody["owner_only"] and data.get("retained_source_custody", {}).get("owner_only", False),
        {"paths": custody["paths"]})

    rec("hosted_minutes_zero", data["hosted_runner_minutes"] == 0)
    rec("provider_calls_zero", data["provider_calls"] == 0)

    if anchor:
        rec("external_anchor_matches", anchor.strip() == actual,
            {"anchor": anchor.strip(), "receipt": actual})
    else:
        checks["external_anchor_matches"] = {
            "pass": None, "detail": "no anchor supplied; local self-consistency only"}

    return {
        "receipt": str(path), "terminal": data["terminal"],
        "verdict": "VERIFIED" if not failures else "REFUSED",
        "evidence_validity": "independent of outcome; PASS, FAIL and HOLD receipts "
                             "are all verifiable evidence",
        "failures": failures, "checks": checks,
        "reconstructed_in_fresh_process": True,
    }


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(prog="tbrail")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit"); s.add_argument("envelope")
    e = sub.add_parser("execute"); e.add_argument("txn_id")
    e.add_argument("--runner-profile", default=None)
    e.add_argument("--runner-profile-sha256", default=None)
    e.add_argument("--settlement-pause-seconds", type=int, default=0)
    sub.add_parser("list")
    v = sub.add_parser("verify"); v.add_argument("receipt")
    v.add_argument("--anchor", default=None)
    sub.add_parser("residency")
    sub.add_parser("runtimes")
    pe = sub.add_parser("profile-emit"); pe.add_argument("out")
    pc = sub.add_parser("profile-check")
    pc.add_argument("--runner-profile", default=None)
    pc.add_argument("--runner-profile-sha256", default=None)
    sub.add_parser("custody")

    a = ap.parse_args()
    conn = connect()

    if a.cmd == "submit":
        env = json.loads(Path(a.envelope).read_text(encoding="utf-8"))
        print(submit(conn, env))
    elif a.cmd == "execute":
        try:
            profile = enforce_profile(a.runner_profile, a.runner_profile_sha256)
        except ProfileMismatch as exc:
            print(json.dumps({"terminal": TERMINAL_HOLD, "reason": "RUNNER_PROFILE_REFUSED",
                              "detail": str(exc), "executed": False}, indent=2))
            sys.exit(3)
        pause = int(os.environ.get("TBRAIL_SETTLEMENT_PAUSE_SECONDS",
                                   a.settlement_pause_seconds or 0))
        print(json.dumps(execute(conn, a.txn_id, profile, pause), indent=2, sort_keys=True))
    elif a.cmd == "list":
        for r in conn.execute("SELECT txn_id,state,terminal,resource_key FROM txn "
                              "ORDER BY created_at"):
            print("\t".join(str(x) for x in r))
    elif a.cmd == "verify":
        out = verify_receipt(Path(a.receipt), a.anchor)
        print(json.dumps(out, indent=2, sort_keys=True))
        sys.exit(0 if out["verdict"] == "VERIFIED" else 1)
    elif a.cmd == "residency":
        leases = conn.execute("SELECT COUNT(*) FROM lease").fetchone()[0]
        works = sorted(p.name for p in WORK_ROOT.iterdir()) if WORK_ROOT.exists() else []
        ckpts = sorted(p.name for p in CHECKPOINT_ROOT.iterdir()) if CHECKPOINT_ROOT.exists() else []
        print(json.dumps({
            "property": "ZERO_TRANSACTION_EXECUTION_RESIDUE",
            "leases_held": leases, "workspaces_present": works,
            "checkpoints_present": ckpts,
            "rail_home": str(RAIL_HOME),
            "private_custody": private_custody_report(),
            "retained_source_custody": retained_source_custody(),
        }, indent=2, sort_keys=True))
    elif a.cmd == "runtimes":
        print(json.dumps(ops_manifest(), indent=2, sort_keys=True))
    elif a.cmd == "profile-emit":
        out = Path(a.out)
        out.write_text(json.dumps(observed_profile(), indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(json.dumps({"emitted": str(out), "sha256": sha256_file(out)}, indent=2))
    elif a.cmd == "profile-check":
        try:
            print(json.dumps(enforce_profile(a.runner_profile, a.runner_profile_sha256),
                             indent=2, sort_keys=True))
        except ProfileMismatch as exc:
            print(json.dumps({"verdict": "REFUSED", "detail": str(exc)}, indent=2))
            sys.exit(3)
    elif a.cmd == "custody":
        print(json.dumps(private_custody_report(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
