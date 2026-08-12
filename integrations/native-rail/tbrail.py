#!/usr/bin/env python3
"""tbrail v2 -- Tier Bench native private execution rail. Controller for octo-n01.

Stdlib only. No provider calls. Source arrives as a pre-verified exact-SHA git
bundle resolved under an admitted custody root, so the worker holds no GitHub
credential and performs no network I/O.

v2 repairs the blocking findings in the second-desk review of PR #165
(tier-bench#164 review comment 5262851689):

  1. closed envelope schema, safe identifier grammar, resolve-under-root
     containment for every derived path
  2. typed operation registry -- argv is built by the controller, never taken
     from the envelope, so a generic interpreter argument cannot be populated
  3. allowed_paths enforced structurally by a bubblewrap mount set, not merely
     declared
  4. fenced atomic leases with boot identity, process-start identity, heartbeat
     and a monotonic fencing token
  5. phase-level crash recovery with an explicit idempotency law
  6. process-group teardown with independent descendant-absence proof
  7. receipts that bind envelope, phase logs, source, ops and ledger, and a
     verifier that recomputes every bound digest
  8. exact runtime pinning by absolute path, version and digest
  9. ZERO_TRANSACTION_EXECUTION_RESIDUE, with retained source custody reported
     separately

Layer law, restated and now enforced: the envelope is closed data. Issue text,
PR prose, comments and model output never become argv. A phase names an
operation id and typed parameters; the controller builds the command.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

RAIL_HOME = Path(os.environ.get("TBRAIL_HOME", Path.home() / ".tbrail")).resolve()
DB_PATH = RAIL_HOME / "rail.db"
WORK_ROOT = RAIL_HOME / "work"
RECEIPT_ROOT = RAIL_HOME / "receipts"
SOURCE_ROOT = RAIL_HOME / "source"
OPS_ROOT = Path(__file__).resolve().parent / "ops"
# Neutral in-sandbox mount root. Host paths are never reproduced inside the
# worker, so the controller's home cannot appear even as an empty parent.
GUEST_ROOT = "/w"

TERMINAL_OK = "PASS"
TERMINAL_FAIL = "FAIL"
TERMINAL_HOLD = "HOLD"

ENVELOPE_SCHEMA = "tier-bench/native-transaction-envelope@2"
RECEIPT_SCHEMA = "tier-bench/native-transaction-receipt@2"

# ---- ceilings -------------------------------------------------------------
MAX_PHASES = 32
MAX_TIMEOUT = 1800
MAX_OUTPUT_BYTES = 4 << 20
MAX_STR = 512
MAX_LIST = 64
MAX_IDENT = 64
LEASE_TTL_SECONDS = 90.0
HEARTBEAT_SECONDS = 10.0

SAFE_IDENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,%d}$" % (MAX_IDENT - 1))
SAFE_RESOURCE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
SAFE_REPO = re.compile(r"^[A-Za-z0-9._-]{1,64}/[A-Za-z0-9._-]{1,64}$")
SAFE_RELPATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
SAFE_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63})*$")
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


def connect() -> sqlite3.Connection:
    RAIL_HOME.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
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


# --------------------------------------------------------------------------
# pinned runtimes and typed operations
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


class Op:
    """An admitted operation. `build` turns typed params into argv.

    The envelope supplies params only. It never supplies argv, an executable,
    a switch, or a program body.
    """

    def __init__(self, op_id, kind, effect, build, network=False, script=None):
        self.op_id = op_id
        self.kind = kind            # "python" | "git" | "rail"
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
    targets = _p_targets(params, ctx)
    return [ctx["python"], "-B", "-m", "py_compile", *targets]


def build_unittest(params, ctx):
    mod = params.get("module")
    if not isinstance(mod, str) or not SAFE_MODULE.match(mod):
        raise Reject("bad_param:module")
    argv = [ctx["python"], "-B", "-m", "unittest"]
    if params.get("verbose") is True:
        argv.append("-v")
    elif "verbose" in params and params["verbose"] is not False:
        raise Reject("bad_param:verbose")
    return argv + [mod]


ARG_TOKEN = re.compile(r"^[A-Za-z0-9._/-]{1,64}$")


def build_repo_script(params, ctx):
    """Run a repository script bound to an exact path AND an exact digest."""
    rel = check_relpath(params.get("script"), "script")
    ctx["require_allowed"](rel)
    want = params.get("script_sha256")
    if not isinstance(want, str) or not HEX64.match(want):
        raise Reject("bad_param:script_sha256")
    target = resolve_under(ctx["repo"], rel)
    if not target.is_file():
        raise Reject(f"script_missing:{rel}")
    actual = sha256_file(target)
    if actual != want:
        raise Reject(f"script_digest_mismatch:{rel}:{actual}")
    args = params.get("args", [])
    if not isinstance(args, list) or len(args) > MAX_LIST:
        raise Reject("bad_param:args")
    for a in args:
        if not isinstance(a, str) or not ARG_TOKEN.match(a):
            raise Reject("bad_param:args[]")
        if a.startswith("-") and a not in params.get("allowed_switches", []):
            raise Reject(f"undeclared_switch:{a}")
    for sw in params.get("allowed_switches", []):
        if not isinstance(sw, str) or not ARG_TOKEN.match(sw):
            raise Reject("bad_param:allowed_switches[]")
    return [ctx["python"], "-B", rel, *args]


def build_git_diff(params, ctx):
    if params:
        raise Reject("bad_param:git_diff_takes_no_params")
    return [RUNTIMES["git"]["path"], "diff", "--exit-code"]


def _rail_script(name, ctx):
    path = OPS_ROOT / name
    if not path.is_file():
        raise Reject(f"rail_script_missing:{name}")
    return path


def build_hold(params, ctx):
    secs = params.get("seconds")
    if not isinstance(secs, int) or isinstance(secs, bool) or not 1 <= secs <= 120:
        raise Reject("bad_param:seconds")
    return [ctx["python"], "-B", str(ctx["ops_mount"] / "hold_resource.py"), str(secs)]


def build_append(params, ctx):
    rel = check_relpath(params.get("target"), "target")
    ctx["require_allowed"](rel)
    return [ctx["python"], "-B", str(ctx["ops_mount"] / "append_byte.py"), rel]


def build_cred_probe(params, ctx):
    if params:
        raise Reject("bad_param:credential_probe_takes_no_params")
    return [ctx["python"], "-B", str(ctx["ops_mount"] / "credential_probe.py")]


def build_spawn_descendant(params, ctx):
    secs = params.get("seconds")
    if not isinstance(secs, int) or isinstance(secs, bool) or not 1 <= secs <= 600:
        raise Reject("bad_param:seconds")
    return [ctx["python"], "-B", str(ctx["ops_mount"] / "spawn_descendant.py"), str(secs)]


OPS: dict[str, Op] = {
    "python.py_compile": Op("python.py_compile", "python", "PURE", build_py_compile),
    "python.unittest": Op("python.unittest", "python", "PURE", build_unittest),
    "python.repo_script": Op("python.repo_script", "python", "PURE", build_repo_script),
    "git.diff_exit_code": Op("git.diff_exit_code", "git", "PURE", build_git_diff),
    "rail.hold_resource": Op("rail.hold_resource", "rail", "PURE", build_hold,
                             script="hold_resource.py"),
    "rail.append_byte": Op("rail.append_byte", "rail", "EFFECTFUL", build_append,
                           script="append_byte.py"),
    "rail.credential_probe": Op("rail.credential_probe", "rail", "PURE",
                                build_cred_probe, script="credential_probe.py"),
    "rail.spawn_descendant": Op("rail.spawn_descendant", "rail", "PURE",
                                build_spawn_descendant, script="spawn_descendant.py"),
}


def ops_manifest() -> dict:
    """Digest every admitted rail script and pinned runtime, for the receipt."""
    out = {"runtimes": RUNTIMES, "scripts": {}}
    for op in OPS.values():
        if op.script:
            p = OPS_ROOT / op.script
            out["scripts"][op.script] = sha256_file(p) if p.is_file() else None
    return out


# --------------------------------------------------------------------------
# envelope -- closed schema
# --------------------------------------------------------------------------

TOP_FIELDS = {
    "schema", "transaction_id", "repository", "visibility", "base_sha",
    "head_sha", "expected_tree", "coordinate", "trust_class", "runtime",
    "phases", "allowed_paths", "resource_key", "result_schema",
    "publication_ceiling", "source_bundle", "source_bundle_sha256",
}
PHASE_FIELDS = {"name", "op", "params", "timeout_seconds"}


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
    return errs


# --------------------------------------------------------------------------
# fenced lease
# --------------------------------------------------------------------------

class LeaseTaken(Exception):
    pass


class FencedOut(Exception):
    pass


class Lease:
    def __init__(self, conn, resource_key, txn_id):
        self.conn = conn
        self.resource_key = resource_key
        self.txn_id = txn_id
        self.owner = str(uuid.uuid4())
        self.fence = None
        self.last_beat = 0.0

    # -- holder liveness -------------------------------------------------
    def _holder_dead(self, row) -> tuple[bool, str]:
        (_, _, _, _, host, hboot, hpid, hstart, _, hbeat) = row
        if hboot != boot_id():
            return True, "holder_boot_id_differs"
        if host != os.uname().nodename:
            return False, "holder_on_other_host"
        start = pid_start_ticks(hpid)
        if start is None:
            return True, "holder_pid_absent"
        if start != hstart:
            return True, "holder_pid_reused"
        if now() - hbeat > LEASE_TTL_SECONDS:
            return True, "holder_heartbeat_expired"
        return False, "holder_alive"

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

    def beat(self):
        if now() - self.last_beat < HEARTBEAT_SECONDS:
            return
        self.conn.execute(
            "UPDATE lease SET heartbeat_at=? WHERE resource_key=? AND owner_uuid=?",
            (now(), self.resource_key, self.owner))
        self.last_beat = now()

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
        self.conn.execute(
            "DELETE FROM lease WHERE resource_key=? AND owner_uuid=?",
            (self.resource_key, self.owner))


# --------------------------------------------------------------------------
# source
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


# --------------------------------------------------------------------------
# sandboxed execution
# --------------------------------------------------------------------------

BWRAP = shutil.which("bwrap")


def sandbox_argv(env: dict, ws: Path, inner: list[str], network: bool) -> list[str]:
    """Build the bubblewrap wrapper that ENFORCES allowed_paths and net policy.

    Only the declared repo subtrees are writable, only pinned runtime trees are
    readable, and the controller's own home -- where credentials would live --
    is not mounted at all.
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
        target = repo if rel == "repo" else repo / rel
        guest = f"{GUEST_ROOT}/repo" if rel == "repo" else f"{GUEST_ROOT}/repo/{rel}"
        argv += ["--bind", str(target), guest]
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


def run_one_phase(env, ws, log_path: Path, ph: dict, ctx) -> dict:
    op = OPS[ph["op"]]
    params = dict(ph.get("params") or {})
    inner = op.build(params, ctx)
    argv = sandbox_argv(env, ws, inner, op.network)
    timeout = int(ph.get("timeout_seconds", 900))
    started = now()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, cwd=str(ws))
    pgid = os.getpgid(proc.pid)
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        td = teardown_group(pgid)
        with contextlib.suppress(Exception):
            out, _ = proc.communicate(timeout=10)
        out = (out or b"") + f"\nphase_timeout after {timeout}s; teardown={td}\n".encode()
        code = 124
    body = (out or b"")[:MAX_OUTPUT_BYTES]
    # bounded teardown on the normal path too, then prove absence independently
    td = teardown_group(pgid)
    log_path.write_bytes(body)
    return {
        "index": ph["_idx"], "name": ph["name"], "op": ph["op"],
        "argv_shape": [Path(inner[0]).name] + inner[1:4],
        "exit_code": code, "state": "PASS" if code == 0 else "FAIL",
        "output_sha256": sha256_bytes(body), "output_bytes": len(body),
        "log_path": str(log_path), "seconds": round(now() - started, 3),
        "timed_out": timed_out, "teardown": td, "replayed": False,
    }


def run_phases(conn, env, ws, log_dir: Path, lease: Lease) -> tuple[str, list[dict]]:
    repo = ws / "repo"
    txn = env["transaction_id"]
    allowed = set(env["allowed_paths"])

    def require_allowed(rel: str):
        # every path parameter must live inside a declared allowed subtree
        if "repo" in allowed:
            return
        head = rel.split("/")[0]
        if head not in allowed and rel not in allowed:
            raise Reject(f"path_not_in_allowed_paths:{rel}")

    ctx = {
        "python": RUNTIMES[env["runtime"]]["path"],
        "repo": repo,
        "ops_mount": Path(f"{GUEST_ROOT}/ops"),
        "require_allowed": require_allowed,
    }

    journal = {r[0]: r for r in conn.execute(
        "SELECT idx,name,op,state,attempt,exit_code,digest,log_path FROM phase "
        "WHERE txn_id=?", (txn,))}

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
                "replayed": True, "note": "recovered_from_journal_not_re_executed",
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
        conn.execute(
            "UPDATE phase SET state=?, exit_code=?, digest=?, log_path=?, ended_at=? "
            "WHERE txn_id=? AND idx=?",
            (res["state"], res["exit_code"], res["output_sha256"], res["log_path"],
             now(), txn, idx))
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
    if SOURCE_ROOT.is_dir():
        for p in sorted(SOURCE_ROOT.iterdir()):
            if p.is_file():
                st = p.stat()
                items.append({
                    "name": p.name, "bytes": st.st_size,
                    "sha256": sha256_file(p), "mode": oct(st.st_mode & 0o777),
                    "owner_uid": st.st_uid,
                })
    return {
        "root": str(SOURCE_ROOT),
        "owner": "tier-bench native rail controller (octo-n01 local account)",
        "items": items,
        "total_bytes": sum(i["bytes"] for i in items),
        "encrypted_at_rest": False,
        "quota_bytes": 5 << 30,
        "retention": "until the bound transaction is settled and its receipt is "
                     "externally anchored; purge with `tbrail purge-source`",
        "purge_law": "an item may be purged when no QUEUED or RUNNING transaction "
                     "references its digest",
    }


def execute(conn, txn_id: str) -> dict:
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
    log_dir.mkdir(parents=True, exist_ok=True)

    lease = Lease(conn, env["resource_key"], txn_id)
    started = now()
    try:
        lease.acquire()
    except LeaseTaken as exc:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("HELD", now(), txn_id))
        return {"terminal": TERMINAL_HOLD, "reason": "COLLISION_HELD",
                "detail": str(exc), "executed": False}

    try:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("RUNNING", now(), txn_id))
        # a crashed attempt can leave a workspace behind; every attempt starts
        # from a clean clone. Phases already PASSed are replayed from the
        # journal rather than re-executed, so this cannot duplicate an effect.
        if ws.exists():
            sanitize(ws)
        (ws / "home").mkdir(parents=True, exist_ok=True)
        ok, detail = materialize_source(env, ws)
        if not ok:
            terminal, phases = TERMINAL_HOLD, []
            bind = {"bound": False, "detail": detail}
        else:
            bind = {"bound": True, "detail": detail}
            terminal, phases = run_phases(conn, env, ws, log_dir, lease)
        lease.assert_still_held()
    except FencedOut as exc:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("FENCED_OUT", now(), txn_id))
        sanitize(ws)
        return {"terminal": TERMINAL_HOLD, "reason": "FENCED_OUT",
                "detail": str(exc), "settled": False}
    finally:
        lease.release()

    sanitation = sanitize(ws)
    lease_rows = conn.execute("SELECT COUNT(*) FROM lease WHERE txn_id=?",
                              (txn_id,)).fetchone()[0]
    envelope_clean = {k: v for k, v in env.items() if not k.startswith("_")}
    (receipt_dir / "ENVELOPE.json").write_text(canonical(envelope_clean), encoding="utf-8")

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
        "terminal": terminal,
        "phase_rows": [list(r) for r in conn.execute(
            "SELECT idx,name,op,state,attempt,exit_code,digest FROM phase "
            "WHERE txn_id=? ORDER BY idx", (txn_id,))],
        "lease_fence_granted": lease.fence,
    }

    residue = {
        "property": "ZERO_TRANSACTION_EXECUTION_RESIDUE",
        "lease_rows_remaining": lease_rows,
        "workspace_absent": sanitation["absent_after"],
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
        "phases": phases,
        "phase_log_bindings": log_bindings,
        "ops_manifest": ops_manifest(),
        "ledger": ledger,
        "terminal": terminal,
        "hosted_runner_minutes": 0,
        "provider_calls": 0,
        "sandbox": {"engine": "bubblewrap", "path": BWRAP, "network": "unshared",
                    "writable_set": env["allowed_paths"],
                    "controller_home_mounted": False},
        "sanitation": sanitation,
        "residency": residue,
        "retained_source_custody": retained_source_custody(),
        "timing": {"started": started, "ended": now(),
                   "seconds": round(now() - started, 3)},
        "controller": {"host": os.uname().nodename, "boot_id": boot_id(),
                       "pid": os.getpid(), "rail_home": str(RAIL_HOME)},
    }
    rpath = receipt_dir / "RECEIPT.json"
    rpath.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    digest = sha256_file(rpath)
    (receipt_dir / "RECEIPT.sha256").write_text(digest + "\n", encoding="utf-8")

    conn.execute("UPDATE txn SET state=?, terminal=?, receipt_path=?, updated_at=? "
                 "WHERE txn_id=?", ("SETTLED", terminal, str(rpath), now(), txn_id))
    receipt["receipt_sha256"] = digest
    return receipt


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

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
    rec("ops_and_runtimes_unchanged", not drift, {"drifted": drift})

    if DB_PATH.is_file():
        conn = sqlite3.connect(DB_PATH, timeout=30)
        trow = conn.execute("SELECT txn_id,state,resource_key FROM txn WHERE txn_id=?",
                            (data["transaction_id"],)).fetchone()
        prows = [list(r) for r in conn.execute(
            "SELECT idx,name,op,state,attempt,exit_code,digest FROM phase "
            "WHERE txn_id=? ORDER BY idx", (data["transaction_id"],))]
        led = data.get("ledger", {})
        tid, tstate, tres = (trow or (None, None, None))
        rec("ledger_binds",
            tid == led.get("txn_id")
            and tres == led.get("resource_key")
            and tstate == led.get("expected_state_after_settlement")
            and prows == led.get("phase_rows"),
            {"db_state": tstate,
             "expected_state": led.get("expected_state_after_settlement"),
             "phase_rows_match": prows == led.get("phase_rows")})
    else:
        rec("ledger_binds", False, "rail.db absent")

    ws = Path(data["sanitation"]["workspace"])
    rec("no_execution_residue",
        not ws.exists() and data["residency"]["descendants_remaining"] == 0,
        {"workspace_present": ws.exists()})

    rec("phases_all_pass",
        bool(data["phases"]) and all(p["state"] == "PASS" for p in data["phases"]),
        {"terminal": data["terminal"]})
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
    sub.add_parser("list")
    v = sub.add_parser("verify"); v.add_argument("receipt")
    v.add_argument("--anchor", default=None)
    sub.add_parser("residency")
    sub.add_parser("runtimes")

    a = ap.parse_args()
    conn = connect()
    for d in (WORK_ROOT, RECEIPT_ROOT, SOURCE_ROOT):
        d.mkdir(parents=True, exist_ok=True)

    if a.cmd == "submit":
        env = json.loads(Path(a.envelope).read_text(encoding="utf-8"))
        print(submit(conn, env))
    elif a.cmd == "execute":
        print(json.dumps(execute(conn, a.txn_id), indent=2, sort_keys=True))
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
        print(json.dumps({
            "property": "ZERO_TRANSACTION_EXECUTION_RESIDUE",
            "leases_held": leases, "workspaces_present": works,
            "rail_home": str(RAIL_HOME),
            "retained_source_custody": retained_source_custody(),
        }, indent=2, sort_keys=True))
    elif a.cmd == "runtimes":
        print(json.dumps(ops_manifest(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
