#!/usr/bin/env python3
"""tbrail v5 -- Tier Bench native private execution rail.

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

v4 repairs the boundaries the exact-head second desk found in v3 at
`ad36bf604166b3f867f017470a3b68c872a7ab48` (PR #165 comment 5263842981,
successor instruction tier-bench#164 comment 5263848172):

  1. settlement is crash-recoverable. A SETTLING state and a settlement journal
     are published BEFORE the workspace is sanitized, and checkpoints are
     purged only AFTER the ledger transition to SETTLED is verified, so every
     pre-SETTLED crash boundary is reconstructible without replaying work
  2. checkpoint restoration validates every archive member -- links, devices,
     absolute paths and traversal are refused before a byte is written
  3. checkpoint custody is bounded: latest-only retention under an enforced
     transaction quota, accounted in the receipt
  4. an externally supplied runner-profile digest is REQUIRED for execute and
     profile-check; absence refuses before lease acquisition
  5. receipt verification establishes receipt identity against the anchor
     first, then derives or contains every path under admitted controller roots
  6. no `preexec_fn`. Phases launch through `systemd-run --user --scope` into a
     delegated cgroup-v2 scope, then `prlimit(1)`, then bubblewrap -- no Python
     runs in the forked child of the threaded controller
  7. resource semantics are exact. cgroup-v2 enforces AGGREGATE memory and task
     ceilings and meters aggregate CPU; `prlimit` applies the explicitly named
     PER-PROCESS rlimits. Source custody and checkpoint bytes are under
     enforced disk quotas
  8. the v1/v2 surface is retired to `historical/`, and the documented bounded
     `purge-source` operation exists

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
import shutil
import signal
import sqlite3
import stat
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
CUSTODY_ROOT = RAIL_HOME / "custody"
SOURCE_CUSTODY_PATH = CUSTODY_ROOT / "SOURCE-CUSTODY.json"
SOURCE_CUSTODY_SCHEMA = "tier-bench/native-source-custody@1"
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
RECEIPT_SCHEMA = "tier-bench/native-transaction-receipt@4"
PROFILE_SCHEMA = "tier-bench/native-rail-runner-profile@2"
MANIFEST_SCHEMA = "tier-bench/repository-operation-manifest@1"
SETTLEMENT_SCHEMA = "tier-bench/native-settlement-journal@1"

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
    # new tasks a phase may create, measured ABOVE the account's ambient task
    # count at phase start, so the ceiling constrains the phase and not the host
    "max_processes": 512,
    "workspace_bytes": 8 << 30,
}
LIMIT_FIELDS = set(DEFAULT_LIMITS)
MAX_SETTLEMENT_PAUSE = 120

# ---- enforced disk budgets ------------------------------------------------
# Checkpoint custody is bounded independently of the workspace ceiling: one
# checkpoint may not exceed this quota, and the bound is enforced WHILE the
# archive streams, so an oversized workspace is refused before its bytes have
# been taken into custody rather than after.
CHECKPOINT_QUOTA_BYTES = 2 << 30
# The prior restore point is retained until the new checkpoint AND its phase row
# are durably committed, so a crash in the install window can never strand a
# PASSed phase without a restore point. Two checkpoints therefore exist inside
# that window, and the transaction's checkpoint custody ceiling is stated as
# what it actually is rather than as the single-checkpoint quota.
CHECKPOINT_CUSTODY_CEILING_BYTES = 2 * CHECKPOINT_QUOTA_BYTES
# Retained controller source custody is enforced, not merely declared.
SOURCE_QUOTA_BYTES = 5 << 30

# ---- admitted crash points ------------------------------------------------
# Crash recovery is only honest if the windows can be entered on demand. Each
# point is a named, admitted abort site; the selected point is recorded in the
# receipt's test_hooks. Entering ANY of them requires an admitted qualification
# mode carried by the accepted runner profile (see `qualification_mode`), so an
# inherited or stale variable cannot kill a production transaction.
CRASH_POINTS = (
    "after_settling_journal",
    "after_sanitation",
    "after_receipt_write",
    "after_sidecar_write",
    "before_settled_update",
    "after_settled_update",
)
CHECKPOINT_CRASH_POINTS = (
    "after_checkpoint_install",
    "after_phase_commit",
)

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


def fsync_dir(d: Path) -> bool:
    """Durably commit a directory entry (rename, create, unlink).

    Writing and fsyncing a file is not enough: the NAME that reaches it lives in
    the parent directory, and after a power cut an unsynced directory can be
    missing an entry whose data blocks are already on disk.
    """
    try:
        fd = os.open(str(d), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return False
    try:
        os.fsync(fd)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def require_dir_durable(d: Path, what: str) -> None:
    """Refuse the transition when a required directory entry cannot be fsynced.

    `fsync_dir` returns a Boolean and every required publication path used to
    throw it away, so the controller could report a record as durably published
    while the directory entry that names it was never committed. A durability
    protocol that cannot fail is not a durability protocol: this fails CLOSED.

    One retry, because a transient EIO that clears is not a reason to hold a
    transaction; a second failure is.
    """
    if fsync_dir(d) or fsync_dir(d):
        return
    raise Reject(f"directory_durability_unavailable:{what}:{d}")


def require_file_durable(fh, what: str) -> None:
    """Same law for the file itself: an unsyncable body is not published."""
    try:
        os.fsync(fh.fileno())
    except OSError as exc:
        raise Reject(f"file_durability_unavailable:{what}:{exc.__class__.__name__}")


def durable_write(path: Path, data: bytes) -> str:
    """Publish a controller record so it survives sudden power loss.

    probe(parent) -> write -> flush -> fsync(file) -> atomic rename ->
    fsync(parent directory). Every settlement record the ledger depends on is
    published this way, so the durability claim in the receipt is a description
    of the code rather than an aspiration.

    The parent directory is proved syncable BEFORE the temporary file is
    written, so a directory that cannot be committed refuses the publication
    while refusing is still free -- no partial, no rename, no half-durable
    record whose name may never reach the disk. The post-rename sync is checked
    too, so the caller's transition is refused rather than reported as durable.
    """
    require_dir_durable(path.parent, "pre_publication:" + path.name)
    tmp = path.with_name(path.name + ".partial")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            require_file_durable(fh, "publication:" + path.name)
        harden(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    require_dir_durable(path.parent, "publication:" + path.name)
    harden(path)
    return sha256_bytes(data)


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
    for d in (RAIL_HOME, WORK_ROOT, RECEIPT_ROOT, SOURCE_ROOT, CHECKPOINT_ROOT,
              CUSTODY_ROOT):
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
    # WAL defaults to synchronous=NORMAL, under which a committed transaction
    # can be lost to a power cut even though the application was told it
    # committed. The ledger's SETTLED transition is the commit point of this
    # whole rail, so it is worth an fsync per commit.
    conn.execute("PRAGMA synchronous=FULL")
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


def _proc_parents() -> dict[int, int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
        except OSError:
            continue
        tail = raw[raw.rfind(")") + 2:].split()
        try:
            parents[int(entry.name)] = int(tail[1])
        except (IndexError, ValueError):
            continue
    return parents


def descendants_of(pid: int) -> list[int]:
    """Every live process whose parent chain reaches `pid`.

    A phase runs in its own PID namespace, so `/proc/<pid>/stat` reports a
    process-group id of 0 for anything inside it and a group-based count sees
    only the bubblewrap process. The parent chain stays host-visible, so this is
    what a process-count ceiling must be built on.
    """
    parents = _proc_parents()
    out = []
    for p in parents:
        cur, hops = p, 0
        while cur > 1 and hops < 128:
            cur = parents.get(cur, 0)
            hops += 1
            if cur == pid:
                out.append(p)
                break
    return sorted(out)


def uid_task_count(uid: int | None = None) -> int:
    """Tasks (threads included) currently charged to this account.

    RLIMIT_NPROC is charged per account, not per process tree, so the ambient
    count decides how much headroom a phase actually gets. Measuring it is what
    turns a declared per-phase process ceiling into an effective one.
    """
    want = os.geteuid() if uid is None else uid
    total = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != want:
                continue
            total += len(os.listdir(entry / "task"))
        except OSError:
            continue
    return total


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
# The phase launch chain. None of these run Python in the forked child of the
# threaded controller: systemd-run registers a delegated cgroup-v2 scope,
# prlimit applies the per-process rlimits, and bubblewrap builds the sandbox.
SYSTEMD_RUN = shutil.which("systemd-run")
PRLIMIT = shutil.which("prlimit")
SH = shutil.which("sh")
CGROUP_MOUNT = Path("/sys/fs/cgroup")


def _tool_digest(path: str | None) -> dict | None:
    if not path:
        return None
    real = Path(os.path.realpath(path))
    if not real.is_file():
        return None
    return {"path": str(real), "sha256": sha256_file(real)}


def user_manager_slice() -> Path | None:
    """The delegated cgroup-v2 subtree `systemd-run --user --scope` writes into.

    A process in an SSH session scope cannot migrate itself into this subtree:
    the common ancestor of `session-N.scope` and `user@UID.service` is
    `user-UID.slice`, which is root-owned, so a direct `cgroup.procs` write is
    denied. The user manager performs the migration on our behalf, which is why
    the launch chain goes through systemd-run rather than writing cgroup files.
    """
    root = CGROUP_MOUNT / "user.slice" / f"user-{os.getuid()}.slice" / \
        f"user@{os.getuid()}.service"
    return root if root.is_dir() else None


def cgroup_delegation() -> dict:
    """What aggregate enforcement this host can actually provide, measured."""
    root = user_manager_slice()
    control = ""
    if root is not None:
        with contextlib.suppress(OSError):
            control = (root / "cgroup.subtree_control").read_text().strip()
    have = set(control.split())
    return {
        "mechanism": "cgroup-v2 scope via systemd-run --user --scope",
        "delegated_root": str(root) if root else None,
        "subtree_control": sorted(have),
        "controllers_required": ["cpu", "memory", "pids"],
        "usable": bool(root) and {"cpu", "memory", "pids"} <= have
        and bool(SYSTEMD_RUN) and bool(PRLIMIT),
    }


def read_cgroup_int(cg: Path, name: str) -> int | None:
    with contextlib.suppress(OSError, ValueError):
        return int((cg / name).read_text().strip())
    return None


def read_cgroup_text(cg: Path, name: str) -> str | None:
    """Raw value. `pids.max` is `max` when unlimited, which is not an integer."""
    with contextlib.suppress(OSError):
        return (cg / name).read_text().strip()
    return None


def read_cgroup_kv(cg: Path, name: str) -> dict:
    out: dict[str, int] = {}
    with contextlib.suppress(OSError):
        for line in (cg / name).read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("-").isdigit():
                out[parts[0]] = int(parts[1])
    return out


def cgroup_cpu_seconds(cg: Path) -> float | None:
    usec = read_cgroup_kv(cg, "cpu.stat").get("usage_usec")
    return None if usec is None else usec / 1e6


def cgroup_kill(cg: Path) -> bool:
    """Kill every process in the scope atomically, including inside its PID
    namespace, which `killpg` from the host cannot reach."""
    with contextlib.suppress(OSError):
        (cg / "cgroup.kill").write_text("1")
        return True
    return False


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


def build_workspace_shape(params, ctx):
    shape = params.get("shape")
    if shape not in ("symlink", "lock"):
        raise Reject(f"workspace_shape_not_admitted:{shape!r}")
    rel = check_relpath(params.get("target"), "target")
    ctx["require_allowed"](rel)
    return _rail(ctx, "workspace_shape.py", shape, rel)


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
    "rail.workspace_shape": Op("rail.workspace_shape", "rail", "EFFECTFUL",
                               build_workspace_shape,
                               script="workspace_shape.py"),
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
    # The launch chain is admitted machinery: its identity is pinned exactly the
    # way runtimes and rail scripts are, so a swapped systemd-run or prlimit is
    # profile drift rather than an invisible change of enforcement.
    launch = {k: v for k, v in (("systemd-run", _tool_digest(SYSTEMD_RUN)),
                                ("prlimit", _tool_digest(PRLIMIT)),
                                ("sh", _tool_digest(SH)),
                                ("bwrap", _tool_digest(BWRAP))) if v}
    return {"runtimes": RUNTIMES, "scripts": scripts, "repository_manifests": repos,
            "launch_chain": launch}


# --------------------------------------------------------------------------
# externally accepted runner profile
# --------------------------------------------------------------------------

def interpreter_identity() -> dict:
    """Exact identity of the Python actually executing this controller."""
    exe = Path(os.path.realpath(sys.executable)) if sys.executable else None
    return {
        "path": str(exe) if exe else None,
        "version": "%d.%d.%d" % sys.version_info[:3],
        "sha256": sha256_file(exe) if exe and exe.is_file() else None,
    }


def observed_profile() -> dict:
    """What this host actually is, as the controller can see it."""
    return {
        "schema": PROFILE_SCHEMA,
        "host": os.uname().nodename,
        "controller": {"path": str(SELF), "sha256": sha256_file(SELF)},
        # The controller's own bytes are pinned; the program that INTERPRETS
        # them was not. Identical controller bytes under a different Python are
        # a different runner, and until this was pinned that substitution
        # produced no drift at all.
        "interpreter": interpreter_identity(),
        "sandbox": {"engine": "bubblewrap", "path": BWRAP,
                    "sha256": sha256_file(Path(BWRAP)) if BWRAP else None},
        "guest_root": GUEST_ROOT,
        "ceilings": {"max_phases": MAX_PHASES, "max_timeout": MAX_TIMEOUT,
                     "lease_ttl_seconds": LEASE_TTL_SECONDS,
                     "heartbeat_seconds": HEARTBEAT_SECONDS,
                     "limits": DEFAULT_LIMITS,
                     "checkpoint_quota_bytes": CHECKPOINT_QUOTA_BYTES,
                     "source_quota_bytes": SOURCE_QUOTA_BYTES},
        "resource_semantics": resource_semantics(),
        "aggregate_enforcement": {k: v for k, v in cgroup_delegation().items()
                                  if k != "usable"},
        "operations": sorted(OPS),
        **ops_manifest(),
    }


def resource_semantics(limits: dict | None = None) -> dict:
    """Name each ceiling by the boundary that actually enforces it.

    The previous revision called per-process rlimits "phase" ceilings. They are
    not: RLIMIT_AS, RLIMIT_FSIZE and RLIMIT_NOFILE bind one process, not a
    process tree. Aggregate memory and task ceilings come from the cgroup;
    aggregate CPU is metered from `cpu.stat` and enforced by the controller's
    monitor. Nothing here is described without being applied.
    """
    lim = limits or DEFAULT_LIMITS
    return {
        "aggregate": {
            "mechanism": "cgroup-v2 scope (systemd-run --user --scope)",
            "memory_max_bytes": int(lim["address_space_bytes"]),
            "memory_swap_max_bytes": 0,
            "tasks_max": int(lim["max_processes"]),
            "cpu_seconds_budget": int(lim["cpu_seconds"]),
            "cpu_enforced_by": "controller monitor sampling cgroup cpu.stat "
                               "usage_usec, then cgroup.kill",
            "workspace_bytes": int(lim["workspace_bytes"]),
            "workspace_enforced_by": "controller monitor sampling workspace tree "
                                     "bytes, then cgroup.kill",
            "output_bytes": int(lim["max_output_bytes"]),
            "output_enforced_by": "controller output pump, then cgroup.kill",
        },
        "per_process": {
            "mechanism": "prlimit(1), applied outside the sandbox before exec",
            "rlimit_as_bytes": int(lim["address_space_bytes"]),
            "rlimit_cpu_seconds": int(lim["cpu_seconds"]),
            "rlimit_fsize_bytes": int(lim["file_size_bytes"]),
            "rlimit_nofile": int(lim["open_files"]),
        },
        "statement": "max_processes is AGGREGATE (cgroup pids.max). "
                     "address_space_bytes and cpu_seconds are enforced BOTH "
                     "aggregate (cgroup memory.max / cpu.stat monitor) AND "
                     "per-process (RLIMIT_AS / RLIMIT_CPU). file_size_bytes and "
                     "open_files are PER-PROCESS ONLY (RLIMIT_FSIZE / "
                     "RLIMIT_NOFILE); no aggregate file-size or descriptor "
                     "budget is claimed. workspace_bytes and max_output_bytes "
                     "are controller-monitored aggregates. RLIMIT_NPROC is no "
                     "longer used: it is charged per account, so it could never "
                     "express a phase ceiling.",
        "disk": {
            "checkpoint_quota_bytes": CHECKPOINT_QUOTA_BYTES,
            "checkpoint_retention": "latest admitted checkpoint only",
            "source_quota_bytes": SOURCE_QUOTA_BYTES,
            "statement": "source materialization and checkpoint bytes are "
                         "enforced against these quotas, not merely declared",
        },
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

    The anchor digest is MANDATORY. Without it the controller would only be
    comparing the adjacent profile file to its own observed bytes, so the
    controller and its profile could drift together and still self-admit. An
    external authority must name the exact digest it accepted. This refuses
    before any lease is acquired, because it is called from the CLI before
    `execute()`.
    """
    want = (expect_sha or os.environ.get("TBRAIL_RUNNER_PROFILE_SHA256") or "").strip()
    if not want:
        raise ProfileMismatch(
            "RUNNER_PROFILE_ANCHOR_REQUIRED: an externally accepted profile digest "
            "is required (--runner-profile-sha256 / TBRAIL_RUNNER_PROFILE_SHA256); "
            "a locally self-consistent profile is not an authority")
    if not HEX64.match(want):
        raise ProfileMismatch(f"RUNNER_PROFILE_ANCHOR_MALFORMED: {want[:16]}")
    p = profile_path(explicit)
    if p is None:
        raise ProfileMismatch(
            "RUNNER_PROFILE_ABSENT: execution requires an accepted runner profile "
            "(--runner-profile / TBRAIL_RUNNER_PROFILE)")
    digest = sha256_file(p)
    if want != digest:
        raise ProfileMismatch(
            f"RUNNER_PROFILE_DIGEST_MISMATCH: accepted={want} actual={digest}")
    accepted = json.loads(p.read_text(encoding="utf-8"))
    obs = observed_profile()

    # The interpreter is checked by name before the generic diff, so drift in it
    # is refused as itself rather than as one more mismatched key.
    pinned = accepted.get("interpreter")
    if not isinstance(pinned, dict) or not pinned.get("path") or not pinned.get("sha256"):
        raise ProfileMismatch(
            "CONTROLLER_INTERPRETER_NOT_PINNED: the accepted profile does not "
            "name the interpreter executing the controller")
    live = obs["interpreter"]
    if live != pinned:
        raise ProfileMismatch(
            "CONTROLLER_INTERPRETER_DRIFT: accepted="
            f"{pinned.get('path')}@{pinned.get('version')}/"
            f"{str(pinned.get('sha256'))[:12]} actual={live.get('path')}@"
            f"{live.get('version')}/{str(live.get('sha256'))[:12]}")

    drift = _diff_profile(accepted, obs)
    if drift:
        raise ProfileMismatch("RUNNER_PROFILE_MISMATCH: " + ",".join(drift[:8]))
    deleg = cgroup_delegation()
    if not deleg["usable"]:
        raise ProfileMismatch(
            "AGGREGATE_ENFORCEMENT_UNAVAILABLE: " + json.dumps(deleg))
    return {"path": str(p), "sha256": digest, "host": accepted.get("host"),
            "externally_pinned": True, "anchor_source": "external",
            "interpreter": live,
            "qualification_mode": bool(accepted.get("_qualification_mode")),
            "aggregate_enforcement": deleg, "verdict": "ADMITTED"}


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
    # retained source custody is an enforced budget, not a declared one
    held = tree_bytes(SOURCE_ROOT)
    if held > SOURCE_QUOTA_BYTES:
        return False, f"source_custody_quota_exceeded:{held}>{SOURCE_QUOTA_BYTES}"
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


def checkpoint_bytes(txn_id: str) -> int:
    """Every byte the transaction holds under the checkpoint root.

    Partials count. A controller killed mid-write leaves a `.partial` behind,
    and custody accounting that only globbed `*.tar` would report disk it was
    actually holding as zero.
    """
    d = CHECKPOINT_ROOT / txn_id
    if not d.is_dir():
        return 0
    return sum(p.stat().st_size for p in d.iterdir() if p.is_file())


def checkpoint_custody(txn_id: str) -> dict:
    d = CHECKPOINT_ROOT / txn_id
    items = sorted(p.name for p in d.glob("*.tar")) if d.is_dir() else []
    partials = sorted(p.name for p in d.glob("*.partial")) if d.is_dir() else []
    return {
        "mode": "LATEST_ADMITTED_CHECKPOINT_ONLY",
        "quota_bytes": CHECKPOINT_QUOTA_BYTES,
        "custody_ceiling_bytes": CHECKPOINT_CUSTODY_CEILING_BYTES,
        "retained": items,
        "retained_count": len(items),
        "stale_partials": partials,
        "retained_bytes": checkpoint_bytes(txn_id),
        "law": "one checkpoint is retained at a time and it may not exceed the "
               "quota, which is enforced WHILE the archive is written; recovery "
               "needs only the last consecutive checkpoint, so per-phase "
               "accumulation is refused rather than bounded after the fact. The "
               "superseded checkpoint is retired only after the new checkpoint "
               "and its phase row are durably committed, so custody holds two "
               "restore points for that window and never fewer than one -- the "
               "ceiling is stated as twice the quota because that is what it "
               "actually is. Checkpoints are purged only after the ledger "
               "transition to SETTLED is verified, so no crash window can strand "
               "a PASSed phase without its restore point.",
        "normalization_law": "a crash after a later phase row commits but before "
                             "its superseded restore point is retired leaves two "
                             "checkpoints that the resume path -- which skips "
                             "every already-PASS phase -- would never revisit. "
                             "Recovery therefore NORMALIZES custody before it "
                             "runs or settles: it verifies the checkpoint named "
                             "by the last consecutive committed PASS row by "
                             "digest and under the extraction law, retires every "
                             "other restore point, durably commits the directory "
                             "entry, rechecks the bound, and retains the retired "
                             "identities in the recovery record.",
        "quota_enforcement": "a bounded writer refuses any write that would "
                             "carry the partial past the quota, so PEAK partial "
                             "bytes -- not merely final bytes -- are what the "
                             "ceiling binds; the payload preflight is retained "
                             "as an earlier, cheaper refusal.",
        "durability_law": "checkpoint publication fails CLOSED: the checkpoint "
                          "directory entry must be fsyncable before a byte is "
                          "taken into custody and after the install rename, or "
                          "the transition is refused. Retirement is cleanup and "
                          "its directory sync is retried and reported, never "
                          "described as durable when it failed.",
        "creation_law": "a checkpoint may contain exactly what the extraction "
                        "law will restore: directories, regular files with one "
                        "link, and symbolic links. A workspace holding a hard "
                        "link, device or special file is REFUSED at creation "
                        "and the transaction is held, rather than installing a "
                        "checkpoint that recovery could not restore.",
        "symlink_law": "symbolic links are captured and restored verbatim, "
                       "including links that point outside the workspace: a "
                       "repository legitimately contains them and a restore "
                       "point that cannot round-trip its own source is not one. "
                       "They are safe by ORDERING -- restoration writes every "
                       "directory and file first and creates links last, and a "
                       "member under a symlinked ancestor is refused -- so no "
                       "byte is ever written through a link. Bind sources are "
                       "separately resolved under the repository with symlinked "
                       "sources refused, so a captured link cannot redirect a "
                       "later mount either.",
    }


def _checkpoint_source_plan(ws: Path) -> tuple[list[tuple[Path, str]], int]:
    """Every member a checkpoint of `ws` would contain, or a refusal.

    Creation is closed against exactly what restoration accepts. `tarfile.add`
    stores a second reference to an inode as a hard link, which the restoration
    law rejects -- so a workspace containing one used to produce an installed
    checkpoint that could never be restored. The disagreement is resolved here,
    at the only point where a refusal is still free, and the total payload is
    measured before a byte is taken into custody.

    Symbolic links are CAPTURED, not refused. A real repository contains them,
    including links that point outside the tree, and a checkpoint that cannot
    round-trip its own source is not a restore point. They are safe to carry
    because a link is never used as a write path: restoration creates every
    directory and file first and every symlink last, and the sandbox resolves
    each bind source under the repository with symlinked sources refused.
    """
    members: list[tuple[Path, str]] = []
    total = 0
    root = Path(os.path.realpath(ws))
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        rel_dir = here.relative_to(root)
        members.append((here, "./" + rel_dir.as_posix() if rel_dir.parts else "."))
        for name in sorted(dirnames + filenames):
            p = here / name
            st = p.lstat()
            mode = st.st_mode
            rel = (rel_dir / name).as_posix()
            if stat.S_ISLNK(mode):
                members.append((p, "./" + rel))
                continue
            if stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode):
                raise Reject(f"checkpoint_source_special:{rel}")
            if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
                raise Reject(f"checkpoint_source_device:{rel}")
            if stat.S_ISDIR(mode):
                continue          # walked on its own turn
            if not stat.S_ISREG(mode):
                raise Reject(f"checkpoint_source_type:{rel}:{stat.S_IFMT(mode):#o}")
            if st.st_nlink > 1:
                raise Reject(f"checkpoint_source_hardlink:{rel}")
            members.append((p, "./" + rel))
            total += st.st_size
    return members, total


def assert_restorable(path: Path, ws: Path) -> dict:
    """Prove an installed checkpoint satisfies the restoration law right now.

    An archive that only the writer has ever validated is a claim. This opens
    the installed bytes and runs the SAME member validation extraction runs, so
    "every installed checkpoint is immediately restorable" is a checked property
    of each install rather than a property of the code that wrote it.
    """
    with tarfile.open(path, "r") as tf:
        files, links = _validated_members(tf, ws)
    return {"verified": True, "members": len(files) + len(links),
            "symlink_members": len(links),
            "law": "validated under the extraction law at install time"}


class QuotaRefused(Reject):
    """A write was refused AT the ceiling, carrying what was measured there."""

    def __init__(self, message: str, evidence: dict):
        super().__init__(message)
        self.evidence = evidence


class BoundedWriter:
    """A file object that refuses a write BEFORE the file would cross a ceiling.

    The revision this replaces handed `tarfile` an ordinary file object and
    checked `fh.tell()` after each completed `addfile()`. By then the member's
    header, body and padding were already written: the partial's PEAK size
    exceeded the quota even though its FINAL size never did, and the controller
    was reporting a bound it had already broken. Peak bytes are what custody
    accounting actually holds, so the bound has to be enforced at the write, not
    audited after it.

    The stream is unbuffered on purpose. `self.written` is then the exact size
    of the file on disk rather than a logical position that a buffer may not
    have flushed yet, so the refusal can name what the filesystem is holding at
    the instant it fires, and `os.fstat` is used to say so rather than trusting
    this class's own counter.
    """

    def __init__(self, fh, quota: int):
        self._fh = fh
        self.quota = int(quota)
        self.written = 0
        self.peak = 0
        self.refusal: dict | None = None

    def write(self, data) -> int:
        view = memoryview(data)
        n = view.nbytes
        if self.written + n > self.quota:
            self.refusal = {
                "quota_bytes": self.quota,
                "bytes_on_disk_before_refusal": self.written,
                "measured_file_size_at_refusal": self._measure(),
                "refused_write_bytes": n,
                "would_have_reached": self.written + n,
                "enforced": "refused before the underlying write",
            }
            raise QuotaRefused(
                f"checkpoint_quota_refused_before_write:{self.written}+{n}>"
                f"{self.quota}", self.refusal)
        while view:
            wrote = self._fh.write(view)
            if not wrote:
                raise Reject("checkpoint_partial_write_stalled")
            self.written += wrote
            view = view[wrote:]
        self.peak = max(self.peak, self.written)
        return n

    def _measure(self) -> int:
        # -1, never an exception: this runs inside a refusal path and on a file
        # object the caller may already have closed.
        try:
            return os.fstat(self._fh.fileno()).st_size
        except (OSError, ValueError):
            return -1

    def tell(self) -> int:
        return self.written

    def flush(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._fh.flush()

    def fileno(self) -> int:
        return self._fh.fileno()

    def measured_peak(self) -> int:
        """Peak bytes as the FILESYSTEM saw them, not as this object counted."""
        return max(self.peak, self._measure())


def write_checkpoint(txn_id: str, idx: int, ws: Path) -> tuple[str, str, dict]:
    """Capture the workspace a PASSed phase produced, under a bound.

    Cross-phase state law: a later phase may depend on files an earlier phase
    created, so recovery restores the last checkpoint rather than recloning
    pristine source.

    Three things are true of every checkpoint this function installs, and none
    of them were true of the revision it replaces: the quota bounds the bytes
    while they are being written rather than after a larger archive already
    exists, every member is one the extraction law will accept, and the PRIOR
    restore point is still on disk when this returns. Retiring it is the
    caller's next step, after the phase row is durably committed -- a crash
    between install and commit must never leave the last committed PASS phase
    pointing at a checkpoint that has already been deleted.
    """
    path = checkpoint_path(txn_id, idx)
    # A controller killed mid-write leaves a partial behind; clear any before
    # starting so a crash loop cannot accumulate uncounted bytes.
    for stale in path.parent.glob("*.partial"):
        stale.unlink(missing_ok=True)
    members, payload = _checkpoint_source_plan(ws)
    if payload > CHECKPOINT_QUOTA_BYTES:
        raise Reject(f"checkpoint_quota_exceeded:{payload}>{CHECKPOINT_QUOTA_BYTES}")
    # The checkpoint directory entry is the publication, so its durability is
    # proved before a byte is taken into custody rather than discarded after.
    require_dir_durable(path.parent, "checkpoint_pre_publication:" + path.name)
    tmp = path.with_suffix(".tar.partial")
    quota = CHECKPOINT_QUOTA_BYTES
    bw: BoundedWriter | None = None
    try:
        with open(tmp, "wb", buffering=0) as fh:
            harden(tmp)
            bw = BoundedWriter(fh, quota)
            with tarfile.open(fileobj=bw, mode="w", format=tarfile.PAX_FORMAT) as tf:
                for src, arcname in members:
                    info = tf.gettarinfo(str(src), arcname=arcname)
                    if info.islnk():
                        raise Reject(f"checkpoint_source_hardlink:{arcname}")
                    if info.isfile():
                        with open(src, "rb") as body:
                            tf.addfile(info, body)
                    else:
                        tf.addfile(info)
            require_file_durable(fh, "checkpoint:" + path.name)
            # measured while the descriptor is still open, so the peak is the
            # filesystem's number rather than this writer's own bookkeeping
            peak = bw.measured_peak()
        size = tmp.stat().st_size
        if size > quota:
            # Unreachable while the bounded writer is the only path to the file;
            # retained as the belt to its braces.
            raise Reject(f"checkpoint_quota_exceeded:{size}>{quota}")
        install = assert_restorable(tmp, ws)
        install["peak_partial_bytes"] = peak
        install["final_bytes"] = size
        install["quota_bytes"] = quota
        install["bound"] = ("refused before any write that would carry the "
                            "partial past the quota; peak partial bytes, not "
                            "final bytes, are what the ceiling binds")
        os.replace(tmp, path)
        require_dir_durable(path.parent, "checkpoint_publication:" + path.name)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    harden(path)
    return str(path), sha256_file(path), install


def retire_superseded_checkpoints(txn_id: str, keep: Path) -> dict:
    """Drop restore points the durably committed journal can no longer reach.

    Called only AFTER the phase row naming `keep` is committed, so the window in
    which both exist is the window in which either one would do. A crash before
    this runs is what `normalize_checkpoint_custody()` cleans up on recovery.
    """
    retired = []
    for old in sorted(keep.parent.glob("*.tar")):
        if old != keep:
            old.unlink(missing_ok=True)
            retired.append(old.name)
    # Retirement is cleanup, not publication: a failed directory sync here is
    # retried and REPORTED rather than described as durable, and it does not
    # refuse a transition whose commit point is already behind it.
    durable = True
    if retired:
        durable = fsync_dir(keep.parent) or fsync_dir(keep.parent)
    return {"retired": retired, "keep": keep.name, "directory_durable": durable,
            "law": "cleanup-only fsync: retried and reported, never claimed"}


def normalize_checkpoint_custody(txn_id: str, keep_path: str, keep_sha: str,
                                 keep_index: int, ws: Path) -> dict:
    """Force checkpoint custody back to the ONE checkpoint the journal names.

    The window this closes: a later phase row commits to a new checkpoint and
    the controller dies before `retire_superseded_checkpoints()` runs. Recovery
    then skips every already-PASS phase, so nothing on the resume path ever
    retired the superseded restore point -- and if the crashed phase was the
    last one, settlement published a receipt whose checkpoint custody held two
    restore points, which that receipt's own verifier rejects.

    Normalization runs BEFORE anything is run or settled: the surviving
    checkpoint named by the last consecutive committed PASS row is verified by
    digest and under the extraction law, every other restore point is retired,
    the directory entry is durably committed, and the custody bound is
    rechecked. The retired identities are retained in the recovery record.
    """
    keep = Path(keep_path)
    d = keep.parent
    observed = sorted(p.name for p in d.glob("*.tar")) if d.is_dir() else []
    if not keep.is_file():
        raise Reject(f"checkpoint_absent_for_committed_phase:{keep_index}:{keep.name}")
    actual = sha256_file(keep)
    if actual != keep_sha:
        raise Reject(f"checkpoint_digest_drift:{keep.name}:{actual}!={keep_sha}")
    with tarfile.open(keep, "r") as tf:
        _validated_members(tf, ws)
    retired = []
    for old in sorted(d.glob("*.tar")):
        if old != keep:
            old.unlink(missing_ok=True)
            retired.append(old.name)
    for stale in sorted(d.glob("*.partial")):
        stale.unlink(missing_ok=True)
        retired.append(stale.name)
    if retired:
        require_dir_durable(d, "checkpoint_normalization:" + txn_id)
    custody = checkpoint_custody(txn_id)
    if custody["retained_count"] > 1 or custody["retained_bytes"] > CHECKPOINT_QUOTA_BYTES:
        raise Reject(
            f"checkpoint_custody_unbounded_after_normalization:"
            f"{custody['retained_count']}:{custody['retained_bytes']}")
    return {
        "normalized": True,
        "observed_at_recovery": observed,
        "committed_phase_index": keep_index,
        "checkpoint_named_by_last_committed_pass": keep.name,
        "checkpoint_sha256": keep_sha,
        "verified": "digest and extraction law",
        "retired_superseded": retired,
        "retained_after": custody["retained"],
        "retained_bytes_after": custody["retained_bytes"],
        "quota_bytes": CHECKPOINT_QUOTA_BYTES,
        "law": "recovery normalizes checkpoint custody to the single checkpoint "
               "named by the last consecutive committed PASS row before running "
               "or settling; a later-phase post-commit crash cannot leave a "
               "superseded restore point outside the committed phase identity",
    }


def _validated_members(tf: tarfile.TarFile,
                       root: Path) -> tuple[list[tarfile.TarInfo], list[tarfile.TarInfo]]:
    """Close the checkpoint archive against every member restoration cannot
    safely place under the new workspace.

    The archive is controller-created, but its members originate in the
    transaction workspace, which the phase controls. `fully_trusted` extraction
    therefore trusted worker-authored metadata. Nothing is written until every
    member has passed.

    Hard links, devices and special files are refused, and so is any member
    whose NAME leaves the workspace. Symbolic links are admitted -- a
    repository contains them -- and returned separately, because the way they
    are made safe is ordering: they are created after every directory and file,
    so no member can ever be written THROUGH a link. A member that would be
    placed under a symlinked ancestor is refused outright, which is the classic
    archive escape and the only thing a link in this position could achieve.
    """
    root = Path(os.path.realpath(root))
    files: list[tarfile.TarInfo] = []
    links: list[tarfile.TarInfo] = []
    link_prefixes: set[str] = set()

    def rel_parts(name: str) -> list[str]:
        if name.startswith("/") or name.startswith("\\") or ":" in name.split("/")[0]:
            raise Reject(f"checkpoint_member_absolute:{name}")
        parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise Reject(f"checkpoint_member_traversal:{name}")
        target = Path(os.path.normpath(str(root / "/".join(parts))))
        if target != root and root not in target.parents:
            raise Reject(f"checkpoint_member_escapes_workspace:{name}")
        return parts

    for m in tf.getmembers():
        name = m.name
        if m.islnk():
            raise Reject(f"checkpoint_member_hardlink:{name}")
        if m.ischr() or m.isblk() or m.isfifo() or m.isdev():
            raise Reject(f"checkpoint_member_device:{name}")
        if not (m.isfile() or m.isdir() or m.issym()):
            raise Reject(f"checkpoint_member_type:{name}:{m.type!r}")
        parts = rel_parts(name)
        for depth in range(1, len(parts)):
            if "/".join(parts[:depth]) in link_prefixes:
                raise Reject(f"checkpoint_member_under_symlink:{name}")
        # never restore setuid/setgid/sticky or group/other-writable bits
        m.mode = (m.mode or 0) & 0o755
        m.uid, m.gid = os.getuid(), os.getgid()
        m.uname = m.gname = ""
        if m.issym():
            if not m.linkname:
                raise Reject(f"checkpoint_member_empty_link_target:{name}")
            link_prefixes.add("/".join(parts))
            links.append(m)
        else:
            files.append(m)
    return files, links


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
            files, links = _validated_members(tf, ws)   # refuses before any write
            try:
                tf.extractall(str(ws), members=files, filter="tar")
            except TypeError:  # python < 3.12 has no extraction filters
                tf.extractall(str(ws), members=files)
            # Links last, and only onto a real directory: by the time any link
            # exists, nothing further is written, so no member can be placed
            # through one.
            for m in links:
                # never `lstrip("./")`: that would eat the leading dot of a
                # dotfile. The validated components are the only safe source.
                parts = [p for p in m.name.replace("\\", "/").split("/")
                         if p not in ("", ".")]
                dest = ws.joinpath(*parts)
                parent = dest.parent
                walk = ws
                for part in parent.relative_to(ws).parts:
                    walk = walk / part
                    if walk.is_symlink():
                        raise Reject(f"checkpoint_link_parent_is_symlink:{m.name}")
                parent.mkdir(parents=True, exist_ok=True)
                dest.unlink(missing_ok=True)
                os.symlink(m.linkname, dest)
    except tarfile.TarError as exc:
        raise Reject(f"checkpoint_unreadable:{path.name}:{exc}")


def purge_checkpoints(txn_id: str) -> int:
    try:
        d = resolve_under(CHECKPOINT_ROOT, txn_id)
    except Reject:
        return 0
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
        # The worker environment is CONSTRUCTED, never inherited. Without this
        # the sandbox would set the variables it declares on top of whatever the
        # controller happened to be holding, so a controller that legitimately
        # carries a narrow publication token would hand that token to the
        # operation. `--clearenv` unsets everything first; only the variables
        # `--setenv` names below survive into the operation.
        "--clearenv",
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
    """The COMPLETE environment of an operation. Nothing else reaches it."""
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


# Variables the transient scope genuinely needs to be created at all. Anything
# outside this set is not passed to the launch chain, so the controller's own
# environment is not the sandbox's fallback.
LAUNCH_ENV_PASSTHROUGH = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


def controller_launch_env() -> dict:
    """The minimum admitted environment for `systemd-run --user`.

    `systemd-run` executes in the CONTROLLER's environment: it is the caller's
    own process that talks to the user manager, so anything the controller holds
    is inherited by the whole launch chain unless the chain is given an explicit
    environment. Bubblewrap clears the environment again further in; this is the
    outer half of the same closure, and it also keeps controller-held material
    out of the transient scope's own recorded properties.
    """
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": str(Path.home()),
        "USER": os.environ.get("USER", ""),
        "LOGNAME": os.environ.get("LOGNAME", ""),
    }
    for key in LAUNCH_ENV_PASSTHROUGH:
        val = os.environ.get(key)
        if val:
            env[key] = val
    return {k: v for k, v in env.items() if v}


def environment_closure() -> dict:
    """What the receipt is entitled to claim about the worker environment."""
    return {
        "controller_environment_inherited_by_launch": False,
        "launch_environment_keys": sorted(controller_launch_env()),
        "launch_environment_law": "systemd-run is executed with an explicitly "
                                  "constructed environment; the controller's own "
                                  "environment is never the default",
        "sandbox_clearenv": True,
        "worker_environment_keys": sorted(worker_env()),
        "worker_environment_law": "bubblewrap --clearenv unsets every inherited "
                                  "variable before the declared worker set is "
                                  "applied, so the operation's environment is "
                                  "exactly the declared set",
    }


# The phase supervisor. It runs in the scope systemd created, records the exact
# cgroup it landed in, and execs the rest of the chain. Only shell built-ins are
# used, so it depends on no external binary. Its single purpose is to make
# "aggregate enforcement actually started" a durable artifact rather than
# something the controller has to infer by winning a polling race: the marker is
# written BEFORE exec, so even a phase that exits immediately leaves the proof.
PHASE_SUPERVISOR = ('read -r l < /proc/self/cgroup; '
                    'printf "%s\\n" "${l#0::}" > "$1"; shift; exec "$@"')


def scope_unit(txn_id: str, idx: int) -> str:
    return f"tbrail-{txn_id}-{idx:02d}-{os.getpid()}-{uuid.uuid4().hex[:8]}.scope"


def launch_argv(unit: str, marker: Path, limits: dict,
                inner: list[str]) -> list[str]:
    """Build the phase launch chain.

    scope (aggregate cgroup ceilings) -> supervisor (records the scope) ->
    prlimit (per-process rlimits) -> bubblewrap (namespace isolation) -> op.

    No step runs Python in the forked child of this threaded controller. The
    previous revision used `preexec_fn`, whose fork-time callback can deadlock
    before exec once the lease heartbeat thread exists; every ceiling it applied
    is now applied by an exec'd program instead.
    """
    if not SYSTEMD_RUN or not PRLIMIT or not SH:
        raise Reject("launch_chain_missing_cannot_enforce_resource_ceilings")
    if not cgroup_delegation()["usable"]:
        raise Reject("cgroup_delegation_unusable_cannot_enforce_aggregate_limits")
    mem = int(limits["address_space_bytes"])
    argv = [
        SYSTEMD_RUN, "--user", "--scope", "--quiet", "--collect", f"--unit={unit}",
        "-p", f"MemoryMax={mem}",
        "-p", "MemorySwapMax=0",
        "-p", f"TasksMax={int(limits['max_processes'])}",
        "--",
        SH, "-c", PHASE_SUPERVISOR, "sh", str(marker),
        PRLIMIT,
        f"--as={mem}",
        f"--cpu={int(limits['cpu_seconds'])}",
        f"--fsize={int(limits['file_size_bytes'])}",
        f"--nofile={int(limits['open_files'])}",
        "--",
    ]
    return argv + inner


def _read_marker(marker: Path) -> Path | None:
    with contextlib.suppress(OSError):
        text = marker.read_text().strip()
        if text.startswith("/"):
            return CGROUP_MOUNT / text.lstrip("/")
    return None


def await_scope(marker: Path, proc: subprocess.Popen,
                timeout: float = 15.0) -> Path | None:
    """Resolve the scope cgroup the phase actually landed in.

    The marker is written before the supervisor execs, so once the process has
    exited one final read is authoritative: absence then means the scope was
    never entered and the phase ran without aggregate enforcement.
    """
    deadline = time.time() + timeout
    while True:
        cg = _read_marker(marker)
        if cg is not None:
            return cg
        if proc.poll() is not None:
            return _read_marker(marker)
        if time.time() > deadline:
            return None
        time.sleep(0.02)


def _survivors(pgid: int, root_pid: int | None) -> list[int]:
    live = set(pids_in_group(pgid))
    if root_pid:
        live |= set(descendants_of(root_pid))
    return sorted(live)


def teardown_group(pgid: int, root_pid: int | None = None,
                   cg: Path | None = None) -> dict:
    """Kill the whole phase, then prove descendant absence.

    The cgroup is the authoritative reach: `cgroup.kill` terminates every task
    in the scope including those inside the phase's own PID namespace, which a
    host-side `killpg` cannot enumerate. Signals remain as the fallback when the
    scope has already been released. Absence is then proved two ways: no process
    remains in the group, and none remains whose parent chain reaches the phase
    root.
    """
    killed_via = None
    if cg is not None and cgroup_kill(cg):
        killed_via = "cgroup.kill"
        deadline = time.time() + 5
        while time.time() < deadline:
            if not _survivors(pgid, root_pid):
                return {"pgid": pgid, "signal": killed_via, "survivors": []}
            time.sleep(0.1)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, sig)
        deadline = time.time() + 5
        while time.time() < deadline:
            if not _survivors(pgid, root_pid):
                return {"pgid": pgid, "signal": sig.name,
                        "cgroup_kill_attempted": killed_via is not None,
                        "survivors": []}
            time.sleep(0.1)
    return {"pgid": pgid, "signal": "SIGKILL",
            "cgroup_kill_attempted": killed_via is not None,
            "survivors": _survivors(pgid, root_pid)}


def _pump_output(stream, log_path: Path, cap: int, state: dict, kill_all):
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
                kill_all()


def sample_cgroup(cg: Path, state: dict) -> float | None:
    """Read the scope's live accounting into `state`.

    A cgroup only exists while the scope holds tasks, so a phase that finishes
    faster than the sampling interval can leave nothing to read. That case is
    reported as `metered: false` with null figures rather than as zeros, because
    "used no memory" and "was never sampled" are different claims and only one
    of them is true.
    """
    cur = read_cgroup_int(cg, "pids.current")
    if cur is not None:
        state["peak_cgroup_pids"] = max(state.get("peak_cgroup_pids") or 0, cur)
    peak_mem = read_cgroup_int(cg, "memory.peak")
    if peak_mem is not None:
        state["peak_memory_bytes"] = max(state.get("peak_memory_bytes") or 0, peak_mem)
    mev = read_cgroup_kv(cg, "memory.events")
    if mev:
        state["memory_events"] = mev
    pev = read_cgroup_kv(cg, "pids.events")
    if pev:
        state["pids_events"] = pev
    pev_local = read_cgroup_kv(cg, "pids.events.local")
    if pev_local:
        state["pids_events_local"] = pev_local
    # Direct kernel witness for the task ceiling. `pids.max` refusing a fork is
    # only INFERRED from "a fork failed while a limit existed"; the kernel says
    # so itself by incrementing the `max` counter in pids.events. The counter
    # lives in a cgroup that disappears with its last task, so it is captured
    # here, from the exact scope, while the scope is still alive -- not
    # reconstructed afterwards from a limit and an errno.
    fired = 0
    for src in (pev, pev_local):
        with contextlib.suppress(TypeError, ValueError):
            fired = max(fired, int((src or {}).get("max", 0)))
    if fired >= 1 and not state.get("pids_kernel_witness"):
        state["pids_kernel_witness"] = {
            "cgroup": str(cg),
            "observed_at": now(),
            "observed_while_scope_alive": True,
            "pids_max": read_cgroup_text(cg, "pids.max"),
            "pids_current": read_cgroup_int(cg, "pids.current"),
            "pids_events": dict(pev or {}),
            "pids_events_local": dict(pev_local or {}),
            "statement": "the kernel counted at least one fork refused by this "
                         "scope's pids.max; the ceiling is witnessed, not inferred",
        }
    cpu_used = cgroup_cpu_seconds(cg)
    if cpu_used is not None:
        state["cpu_seconds_used"] = cpu_used
        state["metered"] = True
    return state.get("cpu_seconds_used")


def _monitor(pgid: int, root_pid: int, ws: Path, limits: dict, state: dict,
             stop: threading.Event, scope: dict, kill_all):
    """Independent enforcement of the ceilings the kernel cannot bind directly.

    Aggregate memory and task count are enforced by the cgroup itself; this
    monitor meters them and enforces the two ceilings that have no kernel
    counterpart: aggregate CPU seconds (cgroup v2 exposes `cpu.stat` usage but
    caps only bandwidth, not a total) and workspace bytes. The per-descendant
    PID count is kept as a second, independent witness of the cgroup's
    `pids.max`.

    This is detect-and-teardown, not prevention: a burst can briefly exceed a
    monitored ceiling before the scope is killed, and the peaks record what was
    actually observed rather than what was requested.
    """
    max_pids = int(limits["max_processes"])
    max_bytes = int(limits["workspace_bytes"])
    max_cpu = float(limits["cpu_seconds"])
    last_disk = 0.0
    while not stop.wait(0.25):
        cg = scope.get("cg")
        live = 1 + len(descendants_of(root_pid))
        state["peak_pids"] = max(state.get("peak_pids", 0), live)
        if cg is not None:
            cpu_used = sample_cgroup(cg, state)
            if cpu_used is not None and cpu_used > max_cpu:
                state["cpu_ceiling_hit"] = True
                teardown_group(pgid, root_pid, cg)
                return
        if live > max_pids:
            state["pid_ceiling_hit"] = True
            teardown_group(pgid, root_pid, cg)
            return
        if time.time() - last_disk > 2.0:
            last_disk = time.time()
            used = tree_bytes(ws)
            state["peak_workspace_bytes"] = max(
                state.get("peak_workspace_bytes", 0), used)
            if used > max_bytes:
                state["workspace_ceiling_hit"] = True
                teardown_group(pgid, root_pid, cg)
                return


def run_one_phase(env, ws, log_path: Path, ph: dict, ctx) -> dict:
    op = OPS[ph["op"]]
    params = dict(ph.get("params") or {})
    limits = phase_limits(ph)
    inner = op.build(params, ctx)
    sandboxed = sandbox_argv(env, ws, inner, op.network)
    idx = ph["_idx"]
    unit = scope_unit(env["transaction_id"], idx)
    scope_dir = log_path.parent.parent / "scopes"
    scope_dir.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    harden(scope_dir)
    marker = scope_dir / f"{idx:02d}.cgroup"
    marker.unlink(missing_ok=True)
    argv = launch_argv(unit, marker, limits, sandboxed)
    timeout = int(ph.get("timeout_seconds", 900))
    started = now()
    ambient = uid_task_count()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, cwd=str(ws),
                            env=controller_launch_env())
    pgid = os.getpgid(proc.pid)
    scope: dict = {"cg": None}

    def kill_all():
        teardown_group(pgid, proc.pid, scope.get("cg"))

    pump_state = {"total": 0, "recorded": 0, "ceiling_hit": False}
    mon_state: dict = {}
    stop = threading.Event()
    pump = threading.Thread(target=_pump_output,
                            args=(proc.stdout, log_path, int(limits["max_output_bytes"]),
                                  pump_state, kill_all), daemon=True)
    mon = threading.Thread(target=_monitor,
                           args=(pgid, proc.pid, ws, limits, mon_state, stop,
                                 scope, kill_all),
                           daemon=True)
    pump.start()
    mon.start()
    scope["cg"] = await_scope(marker, proc)
    if scope["cg"] is not None:
        # sample once immediately: a short phase can outrun the monitor's poll
        sample_cgroup(scope["cg"], mon_state)
    timed_out = False
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        teardown_group(pgid, proc.pid, scope.get("cg"))
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
        code = 124
    if scope.get("cg") is not None:
        # one last read before the scope is released; best effort, the cgroup
        # disappears with its final task
        sample_cgroup(scope["cg"], mon_state)
    stop.set()
    pump.join(timeout=15)
    mon.join(timeout=5)
    with contextlib.suppress(Exception):
        proc.stdout.close()
    # bounded teardown on the normal path too, then prove absence independently
    td = teardown_group(pgid, proc.pid, scope.get("cg"))

    # A phase that never entered its scope ran without aggregate enforcement.
    # That is a controller failure, not a phase result: refuse it rather than
    # report a score earned outside the boundary the receipt claims.
    if scope["cg"] is None:
        raise Reject(f"aggregate_enforcement_did_not_start:{unit}")

    enforcement = {
        "limits": limits,
        "semantics": resource_semantics(limits),
        "aggregate": {
            "mechanism": "cgroup-v2 scope via systemd-run --user --scope",
            "unit": unit,
            "cgroup": str(scope["cg"]),
            "entered": True,
            "marker": str(marker),
            "memory_max_bytes": int(limits["address_space_bytes"]),
            "tasks_max": int(limits["max_processes"]),
            # null, not zero, when the phase finished before any sample: the
            # scope was still entered and enforced, it was simply too short to
            # meter, and reporting 0 would assert something untrue
            "metered": bool(mon_state.get("metered")),
            "peak_memory_bytes": mon_state.get("peak_memory_bytes"),
            "peak_cgroup_pids": mon_state.get("peak_cgroup_pids"),
            "cpu_seconds_used": mon_state.get("cpu_seconds_used"),
            "cpu_ceiling_hit": bool(mon_state.get("cpu_ceiling_hit")),
            "memory_events": mon_state.get("memory_events", {}),
            "pids_events": mon_state.get("pids_events", {}),
            "pids_events_local": mon_state.get("pids_events_local", {}),
            "pids_kernel_witness": mon_state.get("pids_kernel_witness"),
        },
        "per_process": {
            "mechanism": "prlimit(1)",
            "rlimit_as_bytes": int(limits["address_space_bytes"]),
            "rlimit_cpu_seconds": int(limits["cpu_seconds"]),
            "rlimit_fsize_bytes": int(limits["file_size_bytes"]),
            "rlimit_nofile": int(limits["open_files"]),
        },
        "preexec_fn_used": False,
        "environment": environment_closure(),
        "account_tasks_at_start": ambient,
        "account_tasks_note": "observation only; RLIMIT_NPROC is not used, "
                              "because it is charged per account and can never "
                              "express a per-phase ceiling",
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
                or enforcement["workspace_ceiling_hit"]
                or enforcement["aggregate"]["cpu_ceiling_hit"])
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
               resume_from: int, ckpt_crash: str | None = None) -> tuple[str, list[dict]]:
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
            # cross-phase state law: capture what this phase produced. The prior
            # restore point survives this call.
            try:
                ckpt_path, ckpt_sha, restorable = write_checkpoint(txn, idx, ws)
            except Reject as exc:
                # An unrestorable or oversized workspace is a custody refusal,
                # not a phase score: hold rather than admit a PASS whose restore
                # point does not exist.
                conn.execute("UPDATE phase SET state=?, ended_at=? WHERE txn_id=? AND idx=?",
                             ("HOLD", now(), txn, idx))
                res["state"] = "HOLD"
                res["note"] = f"CHECKPOINT_REFUSED:{exc}"
                res["checkpoint"] = {"installed": False, "refusal": str(exc)}
                results.append(res)
                return TERMINAL_HOLD, results
            res["checkpoint"] = {"path": ckpt_path, "sha256": ckpt_sha,
                                 "restorable": restorable}
            _crash_if("after_checkpoint_install", ckpt_crash)
        # The phase row is the durable commit of "this phase PASSed, and THIS is
        # its restore point". Nothing is retired before it lands.
        conn.execute(
            "UPDATE phase SET state=?, exit_code=?, digest=?, log_path=?, ended_at=?, "
            "ckpt_path=?, ckpt_sha=? WHERE txn_id=? AND idx=?",
            (res["state"], res["exit_code"], res["output_sha256"], res["log_path"],
             now(), ckpt_path, ckpt_sha, txn, idx))
        _crash_if("after_phase_commit", ckpt_crash)
        if ckpt_path:
            retirement = retire_superseded_checkpoints(txn, Path(ckpt_path))
            res["checkpoint"]["retired_superseded"] = retirement["retired"]
            res["checkpoint"]["retirement"] = retirement
        lease.beat()
        results.append(res)
        if res["state"] != "PASS":
            terminal = TERMINAL_FAIL
            break
    return terminal, results


def sanitize(ws: Path, attempts: int = 2) -> dict:
    """Delete the workspace, and REPORT whether that actually happened.

    The previous revision deleted with errors ignored and then described the
    result; settlement went on to publish a receipt claiming zero execution
    residue whether or not the tree was gone. Failures are collected here and
    the caller is expected to refuse the commit when the workspace survives:
    a terminal ledger row whose own verifier would reject its residue claim is
    worse than an unsettled transaction.
    """
    ws_r = Path(os.path.realpath(ws))
    try:
        ws_r.relative_to(WORK_ROOT.resolve())
    except ValueError:
        raise Reject(f"refusing_to_delete_outside_work_root:{ws_r}")
    existed = ws_r.exists()
    errors: list[str] = []
    tries = 0
    for _ in range(max(1, attempts)):
        if not ws_r.exists():
            break
        tries += 1
        errors = []

        def _failed(func, path, exc):
            errors.append(f"{getattr(func, '__name__', func)}:{path}:"
                          f"{exc.__class__.__name__ if isinstance(exc, BaseException) else exc}")

        try:
            shutil.rmtree(ws_r, onexc=_failed)
        except TypeError:      # python < 3.12
            shutil.rmtree(ws_r, onerror=lambda f, p, e: _failed(f, p, e[1]))
        except OSError as exc:
            errors.append(f"rmtree:{ws_r}:{exc.__class__.__name__}")
    absent = not ws_r.exists()
    # Cleanup-only: retried and REPORTED. A failed sync here does not refuse the
    # transition, and it is never described as durable when it failed.
    parent_durable = fsync_dir(ws_r.parent) or fsync_dir(ws_r.parent)
    return {"workspace": str(ws_r), "existed": existed, "absent_after": absent,
            "attempts": tries, "errors": errors[:20] if not absent else [],
            "parent_directory_durable": parent_durable,
            "law": "settlement may not commit while the workspace survives"}


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
        # derived, never hardcoded: the deployment's identity belongs in its own
        # runner profile and receipts, not in the public product's source
        "owner": f"tier-bench native rail controller ({os.uname().nodename} "
                 f"local account, uid {os.getuid()})",
        "items": items,
        "total_bytes": sum(i["bytes"] for i in items),
        "owner_only": owner_only,
        "encrypted_at_rest": False,
        "confidentiality": "owner-only filesystem permissions on a single-tenant "
                           "controller account; not encrypted at rest",
        "quota_bytes": SOURCE_QUOTA_BYTES,
        "quota_enforced_at": "materialize_source; a transaction is refused when "
                             "retained custody already exceeds the quota",
        "quota_breached": sum(i["bytes"] for i in items) > SOURCE_QUOTA_BYTES,
        "retention": "until every transaction referencing it is resolved AND no "
                     "retained receipt still needs the bytes to verify; purge "
                     "with `tbrail purge-source`",
        "purge_law": "the hot copy may be removed only when no unresolved "
                     "transaction in ANY state references its digest, and every "
                     "retained receipt that needs the bytes is covered by an "
                     "independently verified successor-custody entry",
        "custody_manifest": str(SOURCE_CUSTODY_PATH),
    }


def load_source_custody() -> dict:
    """The accepted successor-custody manifest, if one has been recorded."""
    if SOURCE_CUSTODY_PATH.is_file():
        with contextlib.suppress(ValueError, OSError):
            data = json.loads(SOURCE_CUSTODY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("schema") == SOURCE_CUSTODY_SCHEMA:
                return data
    return {"schema": SOURCE_CUSTODY_SCHEMA, "entries": {}}


def verify_successor_custody(digest: str, entry) -> dict:
    """Prove the bytes still exist somewhere this controller can reach.

    A successor-custody claim is only worth the rehash that backs it: the named
    object must exist, must live outside the hot custody root that is about to
    be emptied, and must hash to the SAME digest the receipts name. Anything
    less would let a purge trade verifiable receipts for a promise.
    """
    out = {"digest": digest, "verified": False, "checks": {}}
    if not isinstance(entry, dict):
        out["checks"]["entry_present"] = False
        return out
    out["checks"]["entry_present"] = True
    out["holder"] = entry.get("holder")
    raw = str(entry.get("successor_path") or "")
    out["successor_path"] = raw
    p = Path(raw)
    out["checks"]["absolute_path"] = p.is_absolute()
    out["checks"]["exists"] = p.is_file()
    outside = True
    with contextlib.suppress(ValueError, OSError):
        Path(os.path.realpath(p)).relative_to(SOURCE_ROOT.resolve())
        outside = False
    out["checks"]["outside_hot_custody_root"] = outside
    if p.is_file():
        actual = sha256_file(p)
        out["successor_sha256"] = actual
        out["checks"]["rehashes_to_digest"] = (actual == digest)
        declared = str(entry.get("successor_sha256") or digest)
        out["checks"]["matches_declared_digest"] = (actual == declared)
    out["verified"] = all(out["checks"].values())
    return out


def receipts_requiring_source() -> dict[str, list[str]]:
    """Which retained receipts would stop verifying without which bytes."""
    need: dict[str, list[str]] = {}
    if not RECEIPT_ROOT.is_dir():
        return need
    for rp in sorted(RECEIPT_ROOT.glob("*/RECEIPT.json")):
        with contextlib.suppress(ValueError, OSError):
            data = json.loads(rp.read_text(encoding="utf-8"))
            digest = str(((data or {}).get("source") or {}).get("bundle_sha256") or "")
            if digest:
                need.setdefault(digest, []).append(str(rp))
    return need


def source_custody_route(digest: str) -> dict:
    """Verification route for a bundle whose hot copy is gone."""
    entry = (load_source_custody().get("entries") or {}).get(digest)
    route = verify_successor_custody(digest, entry)
    route["route"] = "successor_custody" if route["verified"] else "unavailable"
    return route


def purge_source(conn, dry_run: bool = True, manifest: str | None = None) -> dict:
    """Transfer retained source custody, or refuse.

    This is not a garbage collector. The receipt verifier rehashes the source
    bundle, so deleting bytes a retained receipt still names does not free
    space: it silently converts verifiable receipts into unverifiable ones. The
    operation is therefore a CUSTODY TRANSITION with three refusals -- any
    unresolved transaction in any state (including FENCED_OUT) protects its
    bundle, any retained receipt protects the bytes it needs, and that
    protection lifts only for an independently verified successor-custody entry.
    Every retained receipt is re-verified after the transition and the result is
    part of the report.
    """
    def verify_all() -> dict[str, dict]:
        out = {}
        if RECEIPT_ROOT.is_dir():
            for rp in sorted(RECEIPT_ROOT.glob("*/RECEIPT.json")):
                report = {}
                with contextlib.suppress(Exception):
                    report = verify_receipt(rp)
                out[str(rp)] = {"ok": report.get("verdict") == "VERIFIED",
                                "failures": report.get("failures", ["unreadable"])}
        return out

    verified_before = verify_all()
    protected: dict[str, list[str]] = {}
    for (txn_id, state, env_json) in conn.execute(
            "SELECT txn_id, state, envelope_json FROM txn"):
        if state == "SETTLED":
            continue          # the ONLY resolved state
        with contextlib.suppress(Exception):
            env = json.loads(env_json)
            digest = str(env.get("source_bundle_sha256", ""))
            if digest:
                protected.setdefault(digest, []).append(f"{txn_id}:{state}")

    required = receipts_requiring_source()
    supplied = None
    if manifest:
        mp = Path(manifest)
        if not mp.is_file():
            raise Reject(f"successor_custody_manifest_missing:{manifest}")
        supplied = json.loads(mp.read_text(encoding="utf-8"))
        if supplied.get("schema") != SOURCE_CUSTODY_SCHEMA:
            raise Reject(f"successor_custody_manifest_schema:{supplied.get('schema')}")
    entries = dict((load_source_custody().get("entries") or {}))
    if supplied:
        entries.update(supplied.get("entries") or {})

    kept, purgeable, routes = [], [], {}
    if SOURCE_ROOT.is_dir():
        for p in sorted(SOURCE_ROOT.iterdir()):
            if not p.is_file():
                continue
            digest = sha256_file(p)
            item = {"name": p.name, "bytes": p.stat().st_size, "sha256": digest}
            if digest in protected:
                item["why"] = "referenced_by_unresolved_transaction"
                item["holders"] = protected[digest]
                kept.append(item)
                continue
            if digest in required:
                route = verify_successor_custody(digest, entries.get(digest))
                routes[digest] = route
                item["receipts_requiring_bytes"] = required[digest]
                if not route["verified"]:
                    item["why"] = "retained_receipts_require_these_bytes_and_no_" \
                                  "verified_successor_custody_exists"
                    item["successor_custody"] = route
                    kept.append(item)
                    continue
                item["why"] = "custody_transferred_to_verified_successor"
                item["successor_custody"] = route
            else:
                item["why"] = "no_unresolved_reference_and_no_retained_receipt"
            purgeable.append(item)

    applied = False
    deletion_durable = None
    if not dry_run and purgeable:
        # Record the accepted successor entries BEFORE removing anything, so the
        # verification route a receipt will take exists before the bytes it
        # replaces are gone.
        transferred = {d: entries[d] for d in routes if routes[d]["verified"]}
        if transferred:
            CUSTODY_ROOT.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
            harden(CUSTODY_ROOT)
            current = load_source_custody()
            current["entries"] = {**(current.get("entries") or {}), **transferred}
            current["schema"] = SOURCE_CUSTODY_SCHEMA
            durable_write(SOURCE_CUSTODY_PATH,
                          json.dumps(current, indent=2, sort_keys=True).encode("utf-8"))
        for item in purgeable:
            (SOURCE_ROOT / item["name"]).unlink(missing_ok=True)
        # Deletion is cleanup: retried and reported, never claimed as durable
        # when it failed. The custody manifest above is the publication, and it
        # already refused to proceed if its directory could not be committed.
        deletion_durable = fsync_dir(SOURCE_ROOT) or fsync_dir(SOURCE_ROOT)
        applied = True

    # After the transition, prove the claim that matters: NO receipt that
    # verified before the purge fails after it. A receipt that was already
    # failing -- a deliberately tampered one, say -- is not evidence about this
    # operation either way, so the claim is stated as the absence of a
    # regression rather than as universal verifiability.
    verified_after = verify_all()
    regressions = sorted(k for k, v in verified_after.items()
                         if not v["ok"] and (verified_before.get(k) or {}).get("ok"))
    all_ok = all(v["ok"] for v in verified_after.values()) if verified_after else True

    return {
        "operation": "purge-source", "dry_run": dry_run, "applied": applied,
        "deletion_directory_durable": deletion_durable,
        "purge_law": "no transaction in an unresolved state -- QUEUED, RUNNING, "
                     "SETTLING, HELD, FENCED_OUT or any other non-SETTLED state "
                     "-- references the digest, AND no retained receipt needs the "
                     "bytes unless a verified successor-custody entry holds them",
        "protected_digests": protected,
        "retained": kept,
        "purged" if applied else "purgeable": purgeable,
        "purged_bytes": sum(i["bytes"] for i in purgeable) if applied else 0,
        "successor_custody_routes": routes,
        "custody_manifest": str(SOURCE_CUSTODY_PATH),
        "receipts_checked": len(verified_after),
        "retained_receipts_verified_after": [
            {"receipt": k, **v} for k, v in sorted(verified_after.items())],
        "verification_regressions": regressions,
        "no_verification_regressions": not regressions,
        "all_retained_receipts_verify": all_ok,
        "custody_after": retained_source_custody(),
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

    # Crash hooks are resolved here, before the ledger, the lease or the
    # workspace is touched: an unadmitted or stale value refuses the run instead
    # of killing a transaction that was already in flight.
    crash = admitted_crash_point(profile)
    ckpt_crash = admitted_checkpoint_crash_point(profile)

    ws = resolve_under(WORK_ROOT, txn_id)
    receipt_dir = resolve_under(RECEIPT_ROOT, txn_id)

    if state == "SETTLED":
        # The commit point is already behind this transaction. Finish the
        # idempotent tail a crash may have interrupted -- purge and journal
        # clear -- and re-execute nothing.
        return {"replay": True, "terminal": terminal, "receipt": receipt_path,
                "note": "already settled; no duplicate execution",
                "reconciled": _reconcile_settled(conn, txn_id, receipt_dir, ws)}

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

    if state == "SETTLING":
        # A crash inside the settlement window. The journal holds the terminal
        # and the phase results, so settlement finishes from it: no phase is
        # re-executed and no second receipt identity is minted.
        journal = read_settlement_journal(receipt_dir)
        if journal is None or journal.get("transaction_id") != txn_id:
            conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                         ("HELD", now(), txn_id))
            lease.release()
            return {"terminal": TERMINAL_HOLD, "reason": "SETTLEMENT_JOURNAL_ABSENT",
                    "detail": "cannot reconstruct settlement without its journal",
                    "settled": False}
        try:
            # Settlement counts checkpoint custody before the purge, so custody
            # is normalized here too: a receipt may not report two restore
            # points its own verifier would reject.
            _rf, _ck = _resume_plan(conn, txn_id)
            if _ck is not None:
                journal.setdefault("recovery", {})
                journal["recovery"]["checkpoint_normalization"] = \
                    normalize_checkpoint_custody(txn_id, _ck["path"],
                                                 _ck["sha256"], _ck["index"], ws)
            return _finish_settlement(
                conn, env, txn_id, ws, receipt_dir, journal,
                sha256_file(settlement_journal_path(receipt_dir)),
                lease, profile, pause, crash, resumed=True)
        except BaseException:
            lease.release()
            raise

    recovery = {"resumed": False}
    try:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("RUNNING", now(), txn_id))
        resume_from, ckpt = _resume_plan(conn, txn_id)
        if ws.exists():
            sanitize(ws)
        if ckpt is not None:
            # Before anything is run or settled: custody is forced back to the
            # single checkpoint the last consecutive committed PASS row names.
            # A crash after a later phase row committed but before its
            # superseded restore point was retired is otherwise invisible to
            # the resume path, which skips every already-PASS phase.
            recovery["checkpoint_normalization"] = normalize_checkpoint_custody(
                txn_id, ckpt["path"], ckpt["sha256"], ckpt["index"], ws)
        (ws / "home").mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        ok, detail = materialize_source(env, ws)
        if ok and ckpt is not None:
            # restore the state the completed phases produced, then continue
            restore_checkpoint(Path(ckpt["path"]), ckpt["sha256"], ws)
            recovery.update({"resumed": True, "resume_from_phase": resume_from,
                             "restored_checkpoint": ckpt})
        if not ok:
            terminal, phases = TERMINAL_HOLD, []
            bind = {"bound": False, "detail": detail}
        else:
            bind = {"bound": True, "detail": detail}
            terminal, phases = run_phases(conn, env, ws, log_dir, lease,
                                          resume_from, ckpt_crash)
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
                       recovery, lease, profile, pause, started, crash)
    except BaseException:
        lease.release()
        raise


class SettlementCrash(BaseException):
    """Marker for an injected abort at an admitted settlement boundary."""


def _admitted_crash_point(profile: dict | None, var: str, points: tuple) -> str | None:
    """Resolve an admitted crash point, or refuse the run.

    The hook kills the controller mid-transaction, so it is not enough for it to
    be off by default: an inherited or stale variable must not be able to reach
    the abort site at all. Admission is carried by the ACCEPTED RUNNER PROFILE,
    which is externally anchored by digest, so entering a crash window requires
    an authority outside this process. Anything else -- an unknown point, a
    stale value, a production profile -- refuses here, before the transaction is
    touched, rather than during settlement.
    """
    want = (os.environ.get(var) or "").strip()
    if not want:
        return None
    if not (profile or {}).get("qualification_mode"):
        raise SystemExit(
            f"CRASH_HOOK_NOT_ADMITTED {var}={want}: the accepted runner profile "
            "does not admit qualification mode; refusing before execution")
    if want not in points:
        raise SystemExit(f"UNKNOWN_CRASH_POINT {var}={want}")
    return want


def admitted_crash_point(profile: dict | None = None) -> str | None:
    return _admitted_crash_point(profile, "TBRAIL_SETTLEMENT_CRASH_AT", CRASH_POINTS)


def admitted_checkpoint_crash_point(profile: dict | None = None) -> str | None:
    return _admitted_crash_point(profile, "TBRAIL_CHECKPOINT_CRASH_AT",
                                 CHECKPOINT_CRASH_POINTS)


def _crash_if(point: str, want: str | None) -> None:
    """Enter an admitted settlement crash window.

    SIGKILL to self, not an exception: no unwinding, no atexit, no flush and no
    lease release, which is exactly what a power loss or an OOM kill looks like
    to the ledger. Recovery has to be real, not a tidy shutdown path.
    """
    if want and point == want:
        os.kill(os.getpid(), signal.SIGKILL)
        time.sleep(30)  # unreachable; guards against a swallowed signal


def settlement_journal_path(receipt_dir: Path) -> Path:
    return receipt_dir / "SETTLEMENT.json"


def write_settlement_journal(receipt_dir: Path, payload: dict) -> str:
    """Publish the settlement intent durably, before anything is destroyed."""
    return durable_write(settlement_journal_path(receipt_dir),
                         canonical(payload).encode("utf-8"))


def read_settlement_journal(receipt_dir: Path) -> dict | None:
    p = settlement_journal_path(receipt_dir)
    if not p.is_file():
        return None
    with contextlib.suppress(ValueError, OSError):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema") == SETTLEMENT_SCHEMA:
            return data
    return None


def _reconcile_settled(conn, txn_id: str, receipt_dir: Path, ws: Path) -> dict:
    """Finish the tail of a settlement that crashed after the ledger moved.

    The transition to SETTLED is the commit point. Everything after it -- the
    checkpoint purge and the journal clear -- is idempotent cleanup, so a replay
    completes it without doing any work.
    """
    # Sanitation is retried here, not assumed: a settlement that committed and
    # then failed to remove the workspace leaves residue no other path revisits.
    sanitation = sanitize(ws)
    purged = purge_checkpoints(txn_id)
    jp = settlement_journal_path(receipt_dir)
    had_journal = jp.is_file()
    jp.unlink(missing_ok=True)
    # Cleanup-only: the commit point is already behind this path, so a failed
    # sync is retried and reported rather than refusing a terminal transaction.
    journal_clear_durable = fsync_dir(receipt_dir) or fsync_dir(receipt_dir)

    # A crash between the ledger transition and `lease.release()` strands the
    # dead holder's lease row, and nothing else would ever clear it: the replay
    # path returns before acquiring a lease. The transaction is terminal, so the
    # row is releasable -- but only once the holder is PROVEN dead by the same
    # process-identity test acquisition uses, never merely because we would like
    # the row gone.
    lease_row = conn.execute("SELECT * FROM lease WHERE txn_id=?", (txn_id,)).fetchone()
    lease_cleared, why = False, None
    if lease_row:
        dead, why = Lease(conn, lease_row[0], txn_id)._holder_dead(lease_row)
        if dead:
            conn.execute("DELETE FROM lease WHERE resource_key=? AND txn_id=?",
                         (lease_row[0], txn_id))
            lease_cleared = True
    return {"checkpoints_purged": purged, "settlement_journal_cleared": had_journal,
            "journal_clear_directory_durable": journal_clear_durable,
            "stale_lease_cleared": lease_cleared, "lease_holder_verdict": why,
            "sanitation": sanitation,
            "workspace_absent": sanitation["absent_after"],
            "work_replayed": False, "phases_re_executed": 0}


def _settle(conn, env, txn_id, ws, receipt_dir, phases, terminal, bind, recovery,
            lease, profile, pause, started, crash) -> dict:
    """Begin settlement: publish the journal, then move to SETTLING.

    Settlement used to sanitize the workspace and purge every checkpoint before
    the receipt existed and before the ledger moved. A crash inside that window
    left the transaction RUNNING with PASSed phases whose restore points were
    already gone, and the next invocation could only refuse. The order is now
    inverted: intent is published first and destruction happens last.
    """
    envelope_clean = {k: v for k, v in env.items() if not k.startswith("_")}
    journal = {
        "schema": SETTLEMENT_SCHEMA,
        "transaction_id": txn_id,
        "resource_key": env["resource_key"],
        "envelope_sha256": sha256_bytes(canonical(envelope_clean).encode()),
        "terminal": terminal,
        "phases": phases,
        "binding": bind,
        "recovery": recovery,
        "started": started,
        "fence": lease.fence,
    }
    jsha = write_settlement_journal(receipt_dir, journal)
    conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                 ("SETTLING", now(), txn_id))
    _crash_if("after_settling_journal", crash)
    return _finish_settlement(conn, env, txn_id, ws, receipt_dir, journal, jsha,
                              lease, profile, pause, crash, resumed=False)


def _receipt_matches_settlement(candidate, journal: dict, env: dict,
                                profile: dict, ledger: dict) -> tuple[bool, list[str]]:
    """Is this published receipt the receipt THIS settlement is completing?

    A receipt whose sidecar agrees with it is internally consistent; that says
    nothing about which settlement produced it. Adoption is the right policy for
    a receipt that may already be externally anchored, so the identity has to be
    proved against the settlement journal -- envelope, terminal, phases, source,
    runner profile and ledger intent -- before this settlement inherits it.
    """
    bad: list[str] = []
    if not isinstance(candidate, dict):
        return False, ["receipt_unreadable"]

    def want(label, actual, expected):
        if actual != expected:
            bad.append(label)

    want("schema", candidate.get("schema"), RECEIPT_SCHEMA)
    want("transaction_id", candidate.get("transaction_id"), journal["transaction_id"])
    want("envelope_sha256", candidate.get("envelope_sha256"),
         journal["envelope_sha256"])
    want("terminal", candidate.get("terminal"), journal["terminal"])
    want("phases", canonical(candidate.get("phases")), canonical(journal["phases"]))
    src = candidate.get("source") or {}
    want("source.bundle", src.get("bundle"), env["source_bundle"])
    want("source.bundle_sha256", src.get("bundle_sha256"), env["source_bundle_sha256"])
    want("repository", candidate.get("repository"), env["repository"])
    want("runner_profile.sha256", (candidate.get("runner_profile") or {}).get("sha256"),
         (profile or {}).get("sha256"))
    cl = candidate.get("ledger") or {}
    want("ledger.txn_id", cl.get("txn_id"), ledger["txn_id"])
    want("ledger.resource_key", cl.get("resource_key"), journal["resource_key"])
    want("ledger.expected_state_after_settlement",
         cl.get("expected_state_after_settlement"), "SETTLED")
    want("ledger.lease_fence_granted", cl.get("lease_fence_granted"),
         journal.get("fence"))
    return not bad, bad


def _finish_settlement(conn, env, txn_id, ws, receipt_dir, journal, jsha,
                       lease, profile, pause, crash, resumed: bool) -> dict:
    """Drive SETTLING to SETTLED idempotently, from the journal alone.

    Every step here is safe to repeat: sanitation of an absent workspace, a
    byte-identical envelope write, adoption of an already-published receipt, the
    ledger transition, and a purge that only runs once the transition is
    verified.
    """
    phases = journal["phases"]
    terminal = journal["terminal"]
    bind = journal["binding"]
    recovery = dict(journal.get("recovery") or {})
    started = journal["started"]
    if resumed:
        recovery["settlement_resumed_from_journal"] = True
        recovery["settlement_journal_sha256"] = jsha
    sanitation = sanitize(ws)
    if not sanitation["absent_after"]:
        # The residue claim is part of the receipt. Publishing a terminal row
        # whose own verifier would reject it is worse than staying SETTLING:
        # the journal and the restore points are retained, and the next
        # invocation retries sanitation from the same recorded intent.
        lease.release()
        return {"terminal": TERMINAL_HOLD, "reason": "SANITATION_FAILED",
                "settled": False, "sanitation": sanitation,
                "detail": "workspace survived sanitation; settlement refused",
                "transaction_state": "SETTLING",
                "recovery": "re-run execute; settlement resumes from the journal"}
    _crash_if("after_sanitation", crash)
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

    custody = checkpoint_custody(txn_id)   # counted BEFORE the purge, so it is real
    residue = {
        "property": "ZERO_TRANSACTION_EXECUTION_RESIDUE",
        "expected_lease_rows_after_release": 0,
        "workspace_absent": sanitation["absent_after"],
        "checkpoints_retained_at_settlement": custody["retained_count"],
        "checkpoint_purge_law": "checkpoints are purged only after the verified "
                                "ledger transition to SETTLED, so no crash window "
                                "can strand a PASSed phase without its restore "
                                "point; the receipt is only valid once they are gone",
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
            "extraction": "archive members are validated before extraction; "
                          "hard links, devices, absolute paths, traversal and "
                          "any member under a symlinked ancestor are refused, "
                          "and nothing is written until every member has "
                          "passed. Symbolic links are restored last, after "
                          "every directory and file, so nothing is ever "
                          "written through one",
        },
        "checkpoint_custody": custody,
        "resource_semantics": resource_semantics(),
        "settlement": {
            "law": "SETTLING is published with a durable settlement journal "
                   "BEFORE the workspace is sanitized; the transition to SETTLED "
                   "is the commit point; checkpoints are purged only after it is "
                   "verified. Every pre-SETTLED crash boundary is therefore "
                   "reconstructible from the journal without replaying work.",
            "journal": str(settlement_journal_path(receipt_dir)),
            "journal_sha256": jsha,
            "resumed_from_journal": bool(resumed),
            "admitted_crash_points": list(CRASH_POINTS),
            "admitted_checkpoint_crash_points": list(CHECKPOINT_CRASH_POINTS),
            "crash_hook_admission": "entering any crash window requires "
                                    "qualification mode in the externally "
                                    "anchored runner profile; an unset, unknown "
                                    "or stale variable refuses the run before "
                                    "the transaction is touched",
            "durability": {
                "implemented": "settlement journal, receipt and sidecar are "
                               "written, fsynced, atomically renamed and their "
                               "parent directory fsynced; the ledger runs "
                               "SQLite WAL with synchronous=FULL, so a "
                               "committed SETTLED transition is on disk before "
                               "the commit returns",
                "fails_closed": "every REQUIRED durability operation is checked. "
                                "The parent directory of a journal, receipt, "
                                "sidecar, source-custody manifest or checkpoint "
                                "must be fsyncable before the record is written "
                                "and again after the publishing rename, and the "
                                "file's own fsync must succeed; any failure "
                                "REFUSES the transition rather than reporting a "
                                "record as durably published. Cleanup-only "
                                "deletion syncs are retried and reported, never "
                                "described as durable when they failed.",
                "witnessed": "CONTROLLER_PROCESS_CRASH (SIGKILL at six admitted "
                             "settlement boundaries and two checkpoint "
                             "boundaries, recovered from a cold root)",
                "not_witnessed": "SUDDEN_POWER_LOSS and storage-layer failure. "
                                 "The protocol above is implemented for it and "
                                 "no test in this qualification cuts power, so "
                                 "the product claims process-crash recovery as "
                                 "proven and power-loss durability as "
                                 "implemented-but-unwitnessed.",
            },
        },
        "sanitation": sanitation,
        "residency": residue,
        "private_custody": private_custody_report(),
        "retained_source_custody": retained_source_custody(),
        "test_hooks": {"settlement_pause_seconds": int(pause),
                       "settlement_crash_at": crash},
        "timing": {"started": started, "ended": now(),
                   "seconds": round(now() - started, 3)},
        "controller": {"host": os.uname().nodename, "boot_id": boot_id(),
                       "pid": os.getpid(), "rail_home": str(RAIL_HOME)},
    }
    rpath = receipt_dir / "RECEIPT.json"
    spath = receipt_dir / "RECEIPT.sha256"

    # A receipt an earlier settlement attempt already published is authoritative:
    # it may have been externally anchored, so recovery adopts that exact
    # identity rather than minting a second one for the same terminal.
    adopted = None
    adoption = {"considered": False}
    if resumed and rpath.is_file() and spath.is_file():
        adoption["considered"] = True
        published = sha256_file(rpath)
        adoption["sidecar_agrees"] = (published == spath.read_text().strip())
        if adoption["sidecar_agrees"]:
            candidate = None
            with contextlib.suppress(ValueError, OSError):
                candidate = json.loads(rpath.read_text(encoding="utf-8"))
            ok, mismatches = _receipt_matches_settlement(
                candidate, journal, env, profile, ledger)
            adoption["matches_settlement"] = ok
            adoption["mismatches"] = mismatches
            if ok:
                adopted = candidate
            else:
                # Self-consistent, but not THIS settlement's receipt. It may be
                # externally anchored, so it is not overwritten either: the
                # transaction stays SETTLING and a human decides.
                lease.release()
                return {"terminal": TERMINAL_HOLD, "reason": "FOREIGN_RECEIPT_PRESENT",
                        "settled": False, "receipt_path": str(rpath),
                        "detail": "published receipt does not match the settlement "
                                  "journal; refusing to adopt or overwrite it",
                        "mismatches": mismatches, "transaction_state": "SETTLING"}
    if adopted is not None:
        receipt, digest = adopted, sha256_file(rpath)
    else:
        digest = durable_write(
            rpath, json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8"))
        _crash_if("after_receipt_write", crash)
        durable_write(spath, (digest + "\n").encode("utf-8"))
    _crash_if("after_sidecar_write", crash)

    # still ours immediately before the transition, and verified after it
    lease.assert_still_held()
    _crash_if("before_settled_update", crash)
    conn.execute("UPDATE txn SET state=?, terminal=?, receipt_path=?, updated_at=? "
                 "WHERE txn_id=?", ("SETTLED", terminal, str(rpath), now(), txn_id))
    settled = conn.execute("SELECT state, terminal FROM txn WHERE txn_id=?",
                           (txn_id,)).fetchone()
    if settled != ("SETTLED", terminal):
        lease.release()
        raise SystemExit(f"SETTLEMENT_NOT_VERIFIED {settled}")
    lease.assert_still_held()
    _crash_if("after_settled_update", crash)

    # The commit point is behind us. Only now is it safe to destroy the restore
    # points, and a crash here leaves work that a replay finishes without
    # re-executing anything.
    purged = purge_checkpoints(txn_id)
    settlement_journal_path(receipt_dir).unlink(missing_ok=True)

    # observation window: an external contender must still be refused here
    if pause:
        time.sleep(min(int(pause), MAX_SETTLEMENT_PAUSE))

    lease.release()
    receipt["receipt_sha256"] = digest
    receipt["settlement_completed"] = {
        "checkpoints_purged": purged,
        "settlement_journal_cleared": True,
        "receipt_adopted_from_prior_attempt": adopted is not None,
        "receipt_adoption": adoption,
        "adoption_law": "a published receipt is adopted only after it is proved "
                        "to be this settlement's own receipt against the "
                        "journal; a self-consistent foreign receipt is neither "
                        "adopted nor overwritten",
        "work_replayed": False,
    }
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

    d = path.parent
    actual = sha256_file(path)

    # ---- identity BEFORE any receipt-supplied path is followed -------------
    # A tampered receipt must never be able to make the verifier open, hash or
    # stat an attacker-named file. The anchor is therefore consulted first, and
    # a mismatch returns without reading a single embedded path.
    if anchor is not None:
        if anchor.strip() != actual:
            return {
                "receipt": str(path), "terminal": None, "verdict": "REFUSED",
                "failures": ["external_anchor_matches"],
                "checks": {"external_anchor_matches": {
                    "pass": False,
                    "detail": {"anchor": anchor.strip(), "receipt": actual,
                               "note": "receipt identity refused; no path "
                                       "recorded inside it was followed"}}},
                "followed_receipt_paths": False,
                "reconstructed_in_fresh_process": True,
            }
        rec("external_anchor_matches", True, {"anchor": anchor.strip()})

    data = json.loads(path.read_text(encoding="utf-8"))

    # Every local artifact is DERIVED from the validated transaction id and the
    # controller's own roots. Paths recorded in the receipt are only ever
    # compared against those derivations, never trusted as instructions.
    roots = [p.resolve() for p in (RECEIPT_ROOT, SOURCE_ROOT, WORK_ROOT,
                                   CHECKPOINT_ROOT, OPS_ROOT, REPO_OPS_ROOT,
                                   RAIL_HOME, HERE) if p.exists()]
    escaped: list[dict] = []

    def contained(raw, label) -> Path | None:
        """Refuse any recorded path that is not a regular file inside an
        admitted controller root."""
        if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
            escaped.append({"label": label, "path": str(raw)[:200], "why": "not_absolute"})
            return None
        rp = Path(os.path.realpath(raw))
        for root in roots:
            if rp == root or root in rp.parents:
                if rp.is_file():
                    return rp
                escaped.append({"label": label, "path": str(rp)[:200],
                                "why": "not_a_regular_file"})
                return None
        escaped.append({"label": label, "path": str(rp)[:200],
                        "why": "outside_admitted_controller_roots"})
        return None

    try:
        txn_id = check_ident(data.get("transaction_id"), "transaction_id")
    except Reject as exc:
        return {"receipt": str(path), "terminal": data.get("terminal"),
                "verdict": "REFUSED", "failures": ["transaction_id_wellformed"],
                "checks": {"transaction_id_wellformed": {"pass": False,
                                                         "detail": str(exc)}},
                "followed_receipt_paths": False,
                "reconstructed_in_fresh_process": True}
    rec("transaction_id_wellformed", True, {"transaction_id": txn_id})

    sidecar = d / "RECEIPT.sha256"
    expect = sidecar.read_text().strip() if sidecar.is_file() else None
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

    # Log paths are derived, not followed: the transaction's own log root is
    # computed from the validated id, and a recorded path that resolves anywhere
    # else is refused rather than hashed.
    log_root = (RECEIPT_ROOT / txn_id / "logs").resolve()
    bad_logs = []
    for b in data.get("phase_log_bindings", []):
        lp = contained(b.get("path"), f"phase_log[{b.get('index')}]")
        if lp is None:
            bad_logs.append({"index": b.get("index"), "why": "path_refused"})
        elif log_root not in lp.parents:
            bad_logs.append({"index": b.get("index"),
                             "why": "outside_transaction_log_root"})
        elif sha256_file(lp) != b.get("sha256"):
            bad_logs.append({"index": b.get("index"), "why": "digest_mismatch"})
    rec("phase_logs_rehash", not bad_logs,
        {"bad": bad_logs, "derived_log_root": str(log_root)})

    src = data.get("source", {})
    bundle = None
    try:
        bundle = resolve_under(SOURCE_ROOT, str(src.get("bundle", "")))
    except Reject as exc:
        escaped.append({"label": "source.bundle",
                        "path": str(src.get("bundle"))[:200], "why": str(exc)})
    if bundle is not None and bundle.is_file():
        rec("source_bundle_rehashes", sha256_file(bundle) == src.get("bundle_sha256"),
            {"expected": src.get("bundle_sha256"), "route": "hot_custody"})
    elif str(src.get("bundle_sha256") or ""):
        # The hot copy may have been handed to a successor holder. That is a
        # legitimate custody transition rather than a missing input -- but only
        # if the successor object exists now and rehashes to the digest this
        # receipt names.
        route = source_custody_route(str(src.get("bundle_sha256")))
        rec("source_bundle_rehashes", route["verified"], route)
    else:
        rec("source_bundle_rehashes", False,
            f"bundle absent or refused: {str(src.get('bundle'))[:120]}")

    # Ops, runtimes and the launch chain are re-derived from the controller's
    # own manifest. The receipt supplies digests to compare, never paths to open.
    man = data.get("ops_manifest", {})
    live = ops_manifest()
    drift = []
    for name, sha in (man.get("scripts") or {}).items():
        if live["scripts"].get(name) != sha:
            drift.append(f"script:{name}")
    for rid, info in (man.get("runtimes") or {}).items():
        cur = live["runtimes"].get(rid) or {}
        if cur.get("sha256") != info.get("sha256") or cur.get("path") != info.get("path"):
            drift.append(f"runtime:{rid}")
    for repo, info in (man.get("repository_manifests") or {}).items():
        cur = live["repository_manifests"].get(repo) or {}
        if cur.get("sha256") != info.get("sha256"):
            drift.append(f"repo:{repo}")
    for tool, info in (man.get("launch_chain") or {}).items():
        cur = live["launch_chain"].get(tool) or {}
        if cur.get("sha256") != info.get("sha256"):
            drift.append(f"launch:{tool}")
    rec("ops_and_runtimes_unchanged", not drift, {"drifted": drift})

    prof = data.get("runner_profile") or {}
    pp = contained(prof.get("path"), "runner_profile.path")
    rec("runner_profile_still_matches",
        bool(prof) and pp is not None and sha256_file(pp) == prof.get("sha256"),
        {"profile": prof.get("path"), "expected": prof.get("sha256")})
    rec("runner_profile_externally_pinned", bool(prof.get("externally_pinned")),
        {"externally_pinned": prof.get("externally_pinned"),
         "law": "execution requires an externally supplied profile digest"})

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

    # Residency is checked at DERIVED locations, so a receipt cannot point the
    # verifier at some other directory and claim cleanliness there.
    ws = (WORK_ROOT / txn_id).resolve()
    ckpt_dir = CHECKPOINT_ROOT / txn_id
    journal = settlement_journal_path(RECEIPT_ROOT / txn_id)
    rec("no_execution_residue",
        not ws.exists() and data["residency"]["descendants_remaining"] == 0
        and not ckpt_dir.exists() and not journal.exists(),
        {"derived_workspace": str(ws), "workspace_present": ws.exists(),
         "checkpoints_present": ckpt_dir.exists(),
         "settlement_journal_present": journal.exists()})

    cust = data.get("checkpoint_custody") or {}
    rec("checkpoint_custody_bounded",
        cust.get("mode") == "LATEST_ADMITTED_CHECKPOINT_ONLY"
        and int(cust.get("retained_count", 99)) <= 1
        and int(cust.get("retained_bytes", 1 << 62)) <= int(
            cust.get("quota_bytes", CHECKPOINT_QUOTA_BYTES)),
        {"retained_count": cust.get("retained_count"),
         "retained_bytes": cust.get("retained_bytes"),
         "quota_bytes": cust.get("quota_bytes")})

    settled_law = data.get("settlement") or {}
    rec("settlement_is_recoverable",
        bool(settled_law.get("journal"))
        and list(settled_law.get("admitted_crash_points") or []) == list(CRASH_POINTS),
        {"admitted_crash_points": settled_law.get("admitted_crash_points")})

    agg_ok, agg_bad = True, []
    for p in data.get("phases", []):
        if p.get("replayed"):
            continue
        enf = p.get("enforcement") or {}
        if not enf:
            continue
        if enf.get("preexec_fn_used") is not False:
            agg_ok = False
            agg_bad.append({"index": p.get("index"), "why": "preexec_fn_used"})
        if not ((enf.get("aggregate") or {}).get("entered")):
            agg_ok = False
            agg_bad.append({"index": p.get("index"), "why": "scope_not_entered"})
    rec("aggregate_enforcement_entered_every_phase", agg_ok, {"bad": agg_bad})

    ok_term, term_detail = terminal_is_consistent(data)
    rec("terminal_consistent_with_phases", ok_term, term_detail)

    custody = private_custody_report()
    rec("private_custody_owner_only",
        custody["owner_only"] and data.get("retained_source_custody", {}).get("owner_only", False),
        {"paths": custody["paths"]})

    rec("hosted_minutes_zero", data["hosted_runner_minutes"] == 0)
    rec("provider_calls_zero", data["provider_calls"] == 0)

    rec("receipt_paths_contained", not escaped, {"refused": escaped[:8]})

    if anchor is None:
        checks["external_anchor_matches"] = {
            "pass": None, "detail": "no anchor supplied; local self-consistency only"}

    return {
        "receipt": str(path), "terminal": data["terminal"],
        "verdict": "VERIFIED" if not failures else "REFUSED",
        "evidence_validity": "independent of outcome; PASS, FAIL and HOLD receipts "
                             "are all verifiable evidence",
        "path_law": "receipt identity is established against the external anchor "
                    "before any embedded path is followed; local artifacts are "
                    "derived from the validated transaction id and contained "
                    "under admitted controller roots",
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
    ps = sub.add_parser("purge-source")
    ps.add_argument("--apply", action="store_true",
                    help="actually transfer custody; the default is a dry run")
    ps.add_argument("--successor-custody", default=None,
                    help="successor-custody manifest naming, per bundle digest, "
                         "the holder and path that keeps the bytes verifiable")
    pe2 = sub.add_parser("profile-emit-qualification")
    pe2.add_argument("out")

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
        settling = [r[0] for r in conn.execute(
            "SELECT txn_id FROM txn WHERE state IN ('SETTLING','RUNNING')")]
        print(json.dumps({
            "property": "ZERO_TRANSACTION_EXECUTION_RESIDUE",
            "leases_held": leases, "workspaces_present": works,
            "checkpoints_present": ckpts,
            "unsettled_transactions": settling,
            "checkpoint_custody": {t: checkpoint_custody(t) for t in ckpts},
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
    elif a.cmd == "profile-emit-qualification":
        # The same observed profile, marked as admitting the crash hooks. It is
        # a DIFFERENT profile with a different digest, so a production anchor can
        # never carry qualification mode by accident.
        out = Path(a.out)
        prof = observed_profile()
        prof["_qualification_mode"] = True
        out.write_text(json.dumps(prof, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(json.dumps({"emitted": str(out), "sha256": sha256_file(out),
                          "qualification_mode": True}, indent=2))
    elif a.cmd == "profile-check":
        try:
            print(json.dumps(enforce_profile(a.runner_profile, a.runner_profile_sha256),
                             indent=2, sort_keys=True))
        except ProfileMismatch as exc:
            print(json.dumps({"verdict": "REFUSED", "detail": str(exc)}, indent=2))
            sys.exit(3)
    elif a.cmd == "custody":
        print(json.dumps(private_custody_report(), indent=2, sort_keys=True))
    elif a.cmd == "purge-source":
        try:
            print(json.dumps(purge_source(conn, dry_run=not a.apply,
                                          manifest=a.successor_custody),
                             indent=2, sort_keys=True))
        except Reject as exc:
            print(json.dumps({"verdict": "REFUSED", "detail": str(exc)}, indent=2))
            sys.exit(3)


if __name__ == "__main__":
    main()
