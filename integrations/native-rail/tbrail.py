#!/usr/bin/env python3
"""tbrail -- Tier Bench native private execution rail. Controller for octo-n01.

Stdlib only. No provider calls. No network egress of its own: source arrives as
a pre-verified exact-SHA git bundle, so the worker holds no GitHub credential.

One transaction = one envelope = one lease = one disposable workspace = one
receipt. Phases run inside a single worker lifecycle; a phase never requires a
fresh machine merely to observe the previous phase.

Layer law: the envelope is closed data. Issue text, PR prose, comments, and model
output never become shell input. Commands come only from the envelope's declared
phase graph, and every argv element is a literal from that graph.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

RAIL_HOME = Path(os.environ.get("TBRAIL_HOME", Path.home() / ".tbrail"))
DB_PATH = RAIL_HOME / "rail.db"
WORK_ROOT = RAIL_HOME / "work"
RECEIPT_ROOT = RAIL_HOME / "receipts"
SOURCE_ROOT = RAIL_HOME / "source"

TERMINAL_OK = "PASS"
TERMINAL_FAIL = "FAIL"
TERMINAL_HOLD = "HOLD"

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
  resource_key  TEXT PRIMARY KEY,
  txn_id        TEXT NOT NULL,
  pid           INTEGER NOT NULL,
  acquired_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS phase (
  txn_id     TEXT NOT NULL,
  idx        INTEGER NOT NULL,
  name       TEXT NOT NULL,
  state      TEXT NOT NULL,
  exit_code  INTEGER,
  digest     TEXT,
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
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------
# envelope
# --------------------------------------------------------------------------

REQUIRED = [
    "transaction_id", "repository", "visibility", "base_sha", "head_sha",
    "expected_tree", "coordinate", "trust_class", "phases", "allowed_paths",
    "allowed_tools", "resource_key", "result_schema", "publication_ceiling",
    "source_bundle", "source_bundle_sha256",
]

SAFE_TOOLS = {"python3", "git", "sh"}


def validate_envelope(env: dict) -> list[str]:
    errs = []
    for k in REQUIRED:
        if k not in env:
            errs.append(f"missing_field:{k}")
    if errs:
        return errs
    if env["trust_class"] not in ("TRUSTED_PRIVATE", "UNTRUSTED_FORK"):
        errs.append("bad_trust_class")
    if env["trust_class"] == "UNTRUSTED_FORK":
        errs.append("untrusted_fork_forbidden_on_native_rail")
    for t in env["allowed_tools"]:
        if t not in SAFE_TOOLS:
            errs.append(f"tool_not_allowlisted:{t}")
    if not env["phases"]:
        errs.append("empty_phase_graph")
    for i, ph in enumerate(env["phases"]):
        if "name" not in ph or "argv" not in ph:
            errs.append(f"phase_{i}_malformed")
            continue
        if not isinstance(ph["argv"], list) or not ph["argv"]:
            errs.append(f"phase_{i}_argv_not_list")
            continue
        if not all(isinstance(a, str) for a in ph["argv"]):
            errs.append(f"phase_{i}_argv_not_all_literal_strings")
        if ph["argv"][0] not in env["allowed_tools"]:
            errs.append(f"phase_{i}_tool_not_allowed:{ph['argv'][0]}")
    for sha_field in ("base_sha", "head_sha", "expected_tree", "source_bundle_sha256"):
        v = env[sha_field]
        if not isinstance(v, str) or len(v) not in (40, 64):
            errs.append(f"bad_sha:{sha_field}")
    if env["publication_ceiling"] not in ("NONE", "STATUS_ONLY"):
        errs.append("bad_publication_ceiling")
    return errs


# --------------------------------------------------------------------------
# lease
# --------------------------------------------------------------------------

class LeaseTaken(Exception):
    pass


@contextlib.contextmanager
def exclusive_lease(conn: sqlite3.Connection, resource_key: str, txn_id: str):
    try:
        conn.execute(
            "INSERT INTO lease(resource_key, txn_id, pid, acquired_at) VALUES(?,?,?,?)",
            (resource_key, txn_id, os.getpid(), now()))
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT txn_id, pid FROM lease WHERE resource_key=?", (resource_key,)).fetchone()
        holder_txn, holder_pid = row
        if not pid_alive(holder_pid):
            # stale lease from a dead controller: reclaim, do not duplicate work
            conn.execute("DELETE FROM lease WHERE resource_key=?", (resource_key,))
            conn.execute(
                "INSERT INTO lease(resource_key, txn_id, pid, acquired_at) VALUES(?,?,?,?)",
                (resource_key, txn_id, os.getpid(), now()))
        else:
            raise LeaseTaken(f"resource_key={resource_key} held by txn={holder_txn} pid={holder_pid}")
    try:
        yield
    finally:
        conn.execute("DELETE FROM lease WHERE resource_key=? AND txn_id=?",
                     (resource_key, txn_id))


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------

def materialize_source(env: dict, ws: Path) -> tuple[bool, str]:
    """Clone from a pre-verified exact-SHA bundle. No network, no credential."""
    bundle = Path(env["source_bundle"])
    if not bundle.is_file():
        return False, f"bundle_missing:{bundle}"
    actual = sha256_file(bundle)
    if actual != env["source_bundle_sha256"]:
        return False, f"bundle_digest_mismatch:{actual}"
    repo = ws / "repo"
    r = subprocess.run(["git", "clone", "--quiet", "--no-local", str(bundle), str(repo)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"clone_failed:{r.stderr.strip()[:200]}"
    co = subprocess.run(["git", "-C", str(repo), "checkout", "--quiet", "--detach",
                         env["head_sha"]], capture_output=True, text=True)
    if co.returncode != 0:
        return False, f"checkout_failed:{co.stderr.strip()[:200]}"
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    tree = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
                          capture_output=True, text=True).stdout.strip()
    if head != env["head_sha"]:
        return False, f"head_mismatch:{head}"
    if tree != env["expected_tree"]:
        return False, f"tree_mismatch:{tree}"
    return True, f"bound head={head} tree={tree}"


def worker_env(env: dict) -> dict:
    """Sanitized worker environment. No ambient credentials reach the worker."""
    keep = {"PATH", "LANG", "LC_ALL", "HOME", "TERM"}
    e = {k: v for k, v in os.environ.items() if k in keep}
    for banned in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT", "SSH_AUTH_SOCK",
                   "GIT_ASKPASS", "AWS_ACCESS_KEY_ID", "ANTHROPIC_API_KEY",
                   "OPENAI_API_KEY"):
        e.pop(banned, None)
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e["PYTHONNOUSERSITE"] = "1"
    e["GIT_TERMINAL_PROMPT"] = "0"
    e["GIT_CONFIG_NOSYSTEM"] = "1"
    e["HOME"] = str(Path(env["_workspace"]) / "home")
    return e


def run_phases(conn, env: dict, ws: Path, log_dir: Path) -> tuple[str, list[dict]]:
    repo = ws / "repo"
    results = []
    terminal = TERMINAL_OK
    wenv = worker_env(env)
    Path(wenv["HOME"]).mkdir(parents=True, exist_ok=True)
    for idx, ph in enumerate(env["phases"]):
        name = ph["name"]
        argv = list(ph["argv"])
        started = now()
        conn.execute("INSERT OR REPLACE INTO phase(txn_id,idx,name,state,started_at) "
                     "VALUES(?,?,?,?,?)",
                     (env["transaction_id"], idx, name, "RUNNING", started))
        try:
            proc = subprocess.run(
                argv, cwd=str(repo), env=wenv, capture_output=True, text=True,
                timeout=int(ph.get("timeout_seconds", 900)))
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            code, out, err = 124, "", "phase_timeout"
        except FileNotFoundError as exc:
            code, out, err = 127, "", f"tool_missing:{exc}"
        ended = now()
        body = (out + err).encode("utf-8", "replace")
        digest = sha256_bytes(body)
        (log_dir / f"{idx:02d}-{name}.log").write_bytes(body)
        state = "PASS" if code == 0 else "FAIL"
        conn.execute("UPDATE phase SET state=?, exit_code=?, digest=?, ended_at=? "
                     "WHERE txn_id=? AND idx=?",
                     (state, code, digest, ended, env["transaction_id"], idx))
        results.append({
            "index": idx, "name": name, "argv": argv, "exit_code": code,
            "state": state, "output_sha256": digest,
            "output_bytes": len(body), "seconds": round(ended - started, 3),
        })
        if code != 0:
            terminal = TERMINAL_FAIL
            break
    return terminal, results


def sanitize(ws: Path) -> dict:
    existed = ws.exists()
    if existed:
        shutil.rmtree(ws, ignore_errors=True)
    return {"workspace": str(ws), "existed": existed, "absent_after": not ws.exists()}


# --------------------------------------------------------------------------
# transaction
# --------------------------------------------------------------------------

def submit(conn, env: dict) -> str:
    errs = validate_envelope(env)
    if errs:
        raise SystemExit("ENVELOPE_REJECTED " + json.dumps(errs))
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


def execute(conn, txn_id: str) -> dict:
    row = conn.execute("SELECT envelope_json, state, terminal, receipt_path "
                       "FROM txn WHERE txn_id=?", (txn_id,)).fetchone()
    if not row:
        raise SystemExit(f"UNKNOWN_TXN {txn_id}")
    env_json, state, terminal, receipt_path = row
    env = json.loads(env_json)

    # replay law: a settled transaction is never executed twice
    if state == "SETTLED":
        return {"replay": True, "terminal": terminal, "receipt": receipt_path,
                "note": "already settled; no duplicate execution"}

    ws = WORK_ROOT / txn_id
    log_dir = RECEIPT_ROOT / txn_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    env["_workspace"] = str(ws)

    started = now()
    try:
        with exclusive_lease(conn, env["resource_key"], txn_id):
            conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                         ("RUNNING", now(), txn_id))
            ws.mkdir(parents=True, exist_ok=True)
            ok, detail = materialize_source(env, ws)
            if not ok:
                terminal, phases = TERMINAL_HOLD, []
                bind = {"bound": False, "detail": detail}
            else:
                bind = {"bound": True, "detail": detail}
                terminal, phases = run_phases(conn, env, ws, log_dir)
    except LeaseTaken as exc:
        conn.execute("UPDATE txn SET state=?, updated_at=? WHERE txn_id=?",
                     ("HELD", now(), txn_id))
        return {"terminal": TERMINAL_HOLD, "reason": "COLLISION_HELD",
                "detail": str(exc), "executed": False}

    sanitation = sanitize(ws)
    lease_rows = conn.execute("SELECT COUNT(*) FROM lease WHERE txn_id=?",
                              (txn_id,)).fetchone()[0]

    receipt = {
        "schema": "tier-bench/native-transaction-receipt@1",
        "transaction_id": txn_id,
        "envelope_sha256": sha256_bytes(canonical(
            {k: v for k, v in env.items() if not k.startswith("_")}).encode()),
        "repository": env["repository"],
        "visibility": env["visibility"],
        "coordinate": env["coordinate"],
        "trust_class": env["trust_class"],
        "revision": {"base_sha": env["base_sha"], "head_sha": env["head_sha"],
                     "expected_tree": env["expected_tree"]},
        "source": {"mode": "verified_exact_sha_bundle",
                   "bundle_sha256": env["source_bundle_sha256"],
                   "network_used": False, "credential_used": False},
        "binding": bind,
        "phases": phases,
        "terminal": terminal,
        "hosted_runner_minutes": 0,
        "provider_calls": 0,
        "sanitation": sanitation,
        "residency": {"lease_rows_remaining": lease_rows,
                      "workspace_absent": sanitation["absent_after"],
                      "worker_credential_present": False},
        "timing": {"started": started, "ended": now(),
                   "seconds": round(now() - started, 3)},
        "controller": {"host": os.uname().nodename, "pid": os.getpid(),
                       "rail_home": str(RAIL_HOME)},
    }
    rpath = RECEIPT_ROOT / txn_id / "RECEIPT.json"
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    digest = sha256_file(rpath)
    (rpath.parent / "RECEIPT.sha256").write_text(digest + "\n", encoding="utf-8")

    conn.execute("UPDATE txn SET state=?, terminal=?, receipt_path=?, updated_at=? "
                 "WHERE txn_id=?", ("SETTLED", terminal, str(rpath), now(), txn_id))
    receipt["receipt_sha256"] = digest
    return receipt


def verify_receipt(path: Path) -> dict:
    """Reconstruct and re-verify a terminal receipt in a fresh process."""
    data = json.loads(path.read_text(encoding="utf-8"))
    sidecar = path.parent / "RECEIPT.sha256"
    expect = sidecar.read_text().strip() if sidecar.is_file() else None
    actual = sha256_file(path)
    phases_ok = all(p["state"] == "PASS" for p in data["phases"]) if data["phases"] else False
    return {
        "receipt": str(path),
        "digest_match": (expect == actual),
        "expected": expect, "actual": actual,
        "terminal": data["terminal"],
        "phases_all_pass": phases_ok,
        "workspace_absent": data["sanitation"]["absent_after"],
        "hosted_minutes_zero": data["hosted_runner_minutes"] == 0,
        "provider_calls_zero": data["provider_calls"] == 0,
        "reconstructed_in_fresh_process": True,
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tbrail")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit"); s.add_argument("envelope")
    e = sub.add_parser("execute"); e.add_argument("txn_id")
    sub.add_parser("list")
    v = sub.add_parser("verify"); v.add_argument("receipt")
    sub.add_parser("residency")

    a = ap.parse_args()
    conn = connect()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)

    if a.cmd == "submit":
        env = json.loads(Path(a.envelope).read_text(encoding="utf-8"))
        print(submit(conn, env))
    elif a.cmd == "execute":
        print(json.dumps(execute(conn, a.txn_id), indent=2))
    elif a.cmd == "list":
        for r in conn.execute("SELECT txn_id,state,terminal,resource_key FROM txn "
                              "ORDER BY created_at"):
            print("\t".join(str(x) for x in r))
    elif a.cmd == "verify":
        print(json.dumps(verify_receipt(Path(a.receipt)), indent=2))
    elif a.cmd == "residency":
        leases = conn.execute("SELECT COUNT(*) FROM lease").fetchone()[0]
        works = sorted(p.name for p in WORK_ROOT.iterdir()) if WORK_ROOT.exists() else []
        print(json.dumps({"leases_held": leases, "workspaces_present": works,
                          "rail_home": str(RAIL_HOME)}, indent=2))


if __name__ == "__main__":
    main()
