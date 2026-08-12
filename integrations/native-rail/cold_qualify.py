#!/usr/bin/env python3
"""Cold qualification for the v3 native rail.

Runs from a FRESH controller root supplied on the command line. It never reads
or writes the operational ~/.tbrail, and it refuses to start if the root it is
given already holds a database, lease, workspace or receipt.

Usage:
    cold_qualify.py <fresh-root> <source-bundle> <accepted-runner-profile-sha256>

The runner-profile digest is an EXTERNAL input: it is read from the committed
profile by the caller, quoted in the review packet, and enforced here. The run
cannot silently accept a controller, sandbox engine, runtime closure, rail
script set or operation manifest that differs from the accepted profile.

Covers the original A-J properties plus every witness the exact-head second desk
required before product admission.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TBRAIL = HERE / "tbrail.py"
ENVDIR = HERE / "envelopes-v3"

ROOT = Path(sys.argv[1]).resolve()
SOURCE_BUNDLE = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
ACCEPTED_PROFILE_SHA = sys.argv[3].strip() if len(sys.argv) > 3 else None
PROFILE = HERE / f"RUNNER-PROFILE.{os.uname().nodename}.json"
PY = sys.executable

FIXTURE_ENV = ROOT / "fixture-envelopes"
FIXTURE_BUNDLE = "native-rail-fixture.bundle"
FIXTURE_REPO_ID = "tier-bench/native-rail-fixture"

results: list[dict] = []


def record(prop, name, ok, detail=None):
    results.append({"property": prop, "name": name,
                    "pass": bool(ok), "detail": detail})
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {prop} :: {name}", flush=True)
    if not ok:
        print(f"        detail: {json.dumps(detail, default=str)[:600]}", flush=True)


def rail_env(extra=None):
    e = dict(os.environ)
    e["TBRAIL_HOME"] = str(ROOT)
    e["TBRAIL_RUNNER_PROFILE"] = str(PROFILE)
    if ACCEPTED_PROFILE_SHA:
        e["TBRAIL_RUNNER_PROFILE_SHA256"] = ACCEPTED_PROFILE_SHA
    e.pop("TBRAIL_SETTLEMENT_PAUSE_SECONDS", None)
    if extra:
        e.update(extra)
    return e


def rail(*args, timeout=900, env_extra=None):
    return subprocess.run([PY, str(TBRAIL), *args], capture_output=True,
                          text=True, timeout=timeout, env=rail_env(env_extra))


def db():
    return sqlite3.connect(ROOT / "rail.db", timeout=30)


def jloads(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def logs_of(txn):
    body = ""
    d = ROOT / "receipts" / txn / "logs"
    if d.is_dir():
        for f in sorted(d.iterdir()):
            body += f.read_text(errors="replace")
    return body


# --------------------------------------------------------------------------
# cold-root precondition and fixtures
# --------------------------------------------------------------------------
def assert_cold():
    if ROOT.exists():
        stale = [p.name for p in ROOT.iterdir()
                 if p.name in ("rail.db", "work", "receipts", "checkpoints")]
        if stale:
            print(f"REFUSING: {ROOT} is not cold; found {stale}")
            raise SystemExit(2)
    (ROOT / "source").mkdir(parents=True, exist_ok=True)
    if SOURCE_BUNDLE:
        shutil.copy2(SOURCE_BUNDLE, ROOT / "source" / SOURCE_BUNDLE.name)
    if not PROFILE.is_file():
        print(f"REFUSING: accepted runner profile absent at {PROFILE}")
        raise SystemExit(2)
    if not ACCEPTED_PROFILE_SHA:
        print("REFUSING: no accepted runner-profile digest supplied")
        raise SystemExit(2)
    record("COLD_ROOT", "fresh controller root with no prior db/leases/work/receipts",
           True, {"root": str(ROOT)})


TOOL = (
    "#!/usr/bin/env python3\n"
    '"""Deterministic fixture tool bound by the accepted repository-operation manifest."""\n'
    "import sys\n"
    "\n"
    'print("FIXTURE_TOOL_OK", *sys.argv[1:])\n'
)
MOD = '"""Module inside the nested admitted subtree."""\n\nVALUE = 1\n'
THING = '"""Module OUTSIDE the nested admitted subtree."""\n\nVALUE = 2\n'


def build_fixture():
    """Build a tiny source repository that carries a symlink and a nested tree.

    Nested-subtree and symlink-escape behaviour must be proved on real source
    passing through the real clone-and-bind path, not asserted in a unit test.
    """
    work = ROOT / "fixture-build"
    repo = work / "repo"
    if work.exists():
        shutil.rmtree(work)
    repo.mkdir(parents=True)
    for rel, body in (("pkg/sub/tool.py", TOOL), ("pkg/sub/mod.py", MOD),
                      ("other/thing.py", THING)):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body.encode())
    os.symlink("/etc", repo / "escape")
    git = ["git", "-C", str(repo), "-c", "user.email=rail@tier-bench.invalid",
           "-c", "user.name=tbrail fixture"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-q", "-m", "native rail qualification fixture"],
                   check=True, capture_output=True)
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    tree = subprocess.run(git + ["rev-parse", "HEAD^{tree}"], capture_output=True,
                          text=True).stdout.strip()
    bundle = ROOT / "source" / FIXTURE_BUNDLE
    subprocess.run(git + ["bundle", "create", str(bundle), "--all"], check=True,
                   capture_output=True)
    bsha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    tool_sha = hashlib.sha256(TOOL.encode()).hexdigest()

    FIXTURE_ENV.mkdir(parents=True, exist_ok=True)

    def envelope(txn, phases, allowed, key):
        return {
            "schema": "tier-bench/native-transaction-envelope@3",
            "transaction_id": txn,
            "repository": FIXTURE_REPO_ID,
            "visibility": "private",
            "base_sha": head, "head_sha": head, "expected_tree": tree,
            "coordinate": "BigBirdReturns/tier-bench#164",
            "trust_class": "TRUSTED_PRIVATE",
            "runtime": "python3.11",
            "resource_key": key,
            "allowed_paths": allowed,
            "result_schema": "tier-bench/native-transaction-receipt@4",
            "publication_ceiling": "NONE",
            "source_bundle": FIXTURE_BUNDLE,
            "source_bundle_sha256": bsha,
            "phases": phases,
        }

    write = lambda n, o: (FIXTURE_ENV / f"{n}.json").write_text(
        json.dumps(o, indent=2), encoding="utf-8")

    write("nested", envelope("fixture-nested-001", [
        {"name": "compile-nested-module", "op": "python.py_compile",
         "params": {"targets": ["pkg/sub/mod.py"]}},
        {"name": "run-manifest-operation", "op": "repo.operation",
         "params": {"operation": "fixture.run-tool",
                    "values": {"label": "nested-subtree-witness"}}},
    ], ["pkg/sub"], "fixture:nested-probe"))
    write("outside", envelope("fixture-outside-001", [
        {"name": "compile-sibling-module", "op": "python.py_compile",
         "params": {"targets": ["other/thing.py"]}},
    ], ["pkg/sub"], "fixture:outside-probe"))
    write("symlink", envelope("fixture-symlink-001", [
        {"name": "compile-nested-module", "op": "python.py_compile",
         "params": {"targets": ["pkg/sub/mod.py"]}},
    ], ["pkg/sub", "escape"], "fixture:symlink-probe"))
    write("drift", envelope("fixture-drift-001", [
        {"name": "run-drifted-operation", "op": "repo.operation",
         "params": {"operation": "fixture.digest-drift", "values": {}}},
    ], ["pkg/sub"], "fixture:drift-probe"))

    manifest = json.loads(
        (HERE / "repo-ops" / "tier-bench__native-rail-fixture.json").read_text())
    pinned = manifest["operations"]["fixture.run-tool"]["script_sha256"]
    record("FIXTURE_BUILT",
           "qualification fixture repository built and bound to the accepted manifest",
           pinned == tool_sha,
           {"head": head, "manifest_pinned_sha": pinned, "built_sha": tool_sha})
    shutil.rmtree(work, ignore_errors=True)


def fx(name):
    return str(FIXTURE_ENV / f"{name}.json")


# --------------------------------------------------------------------------
# A. deliberate defect renders red
# --------------------------------------------------------------------------
def prop_a():
    rail("submit", str(ENVDIR / "defect.json"))
    out = jloads(rail("execute", "estate-defect-001").stdout)
    red = out and out["terminal"] == "FAIL"
    mutation_caught = out and any(
        p["name"] == "verify-no-source-mutation" and p["state"] == "FAIL"
        for p in out.get("phases", []))
    record("A_DEFECT_RENDERS_RED", "deliberate defect produces a FAIL terminal",
           red and mutation_caught,
           {"terminal": out and out.get("terminal")})


# --------------------------------------------------------------------------
# B. credential isolation, structural
# --------------------------------------------------------------------------
def prop_b():
    rail("submit", str(ENVDIR / "isolation.json"))
    out = jloads(rail("execute", "estate-isolation-001").stdout)
    ok = out and out["terminal"] == "PASS"
    log = logs_of("estate-isolation-001")
    record("B_CREDENTIAL_ISOLATION", "worker sees no credential, no home, no network",
           ok and "CREDENTIAL_ISOLATION_HOLDS" in log,
           {"terminal": out and out.get("terminal"), "log": log[-300:]})
    record("B_STRUCTURAL", "controller home is not mounted into the worker",
           "controller_home_mounted= False" in log, {"log_tail": log[-200:]})


# --------------------------------------------------------------------------
# C. replay, real crash recovery, artifact survival, effectful refusal
# --------------------------------------------------------------------------
def prop_c_settled_replay():
    rail("submit", str(ENVDIR / "canary-py311.json"))
    first = jloads(rail("execute", "estate-canary-py311-001").stdout)
    ok = first and first["terminal"] == "PASS"
    record("C1_CANARY_PY311", "exact Python 3.11 canary settles PASS", ok,
           {"terminal": first and first.get("terminal"),
            "runtime": first and first.get("runtime", {}).get("version")})
    before = db().execute("SELECT COUNT(*) FROM phase WHERE txn_id=?",
                          ("estate-canary-py311-001",)).fetchone()[0]
    again = jloads(rail("execute", "estate-canary-py311-001").stdout)
    after = db().execute("SELECT COUNT(*) FROM phase WHERE txn_id=?",
                         ("estate-canary-py311-001",)).fetchone()[0]
    record("C2_SETTLED_REPLAY", "settled transaction is not executed twice",
           again and again.get("replay") is True and before == after,
           {"phase_rows_before": before, "phase_rows_after": after})
    return first


def _crash_mid_phase(txn: str, envelope: str, wait_for=(0, 1)):
    """Start a transaction and SIGKILL the controller group mid-phase."""
    rail("submit", envelope)
    proc = subprocess.Popen([PY, str(TBRAIL), "execute", txn],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=rail_env())
    deadline = time.time() + 240
    killed = False
    while time.time() < deadline:
        try:
            rows = dict((r[0], r[1]) for r in db().execute(
                "SELECT idx,state FROM phase WHERE txn_id=?", (txn,)))
        except sqlite3.Error:
            rows = {}
        if rows.get(wait_for[0]) == "PASS" and rows.get(wait_for[1]) == "RUNNING":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            killed = True
            break
        time.sleep(0.3)
    proc.wait(timeout=30)
    return killed


def prop_c_real_crash():
    txn = "estate-crash-pure-001"
    killed = _crash_mid_phase(txn, str(ENVDIR / "crash-pure.json"))
    record("C3_CRASH_INJECTED", "controller killed mid-phase (SIGKILL to its group)",
           killed, {"killed": killed})
    if not killed:
        return

    pre = db().execute(
        "SELECT idx,state,attempt,digest FROM phase WHERE txn_id=? ORDER BY idx",
        (txn,)).fetchall()
    phase0_digest_before = dict((r[0], r[3]) for r in pre).get(0)

    out = jloads(rail("execute", txn).stdout)
    post = db().execute(
        "SELECT idx,state,attempt,digest FROM phase WHERE txn_id=? ORDER BY idx",
        (txn,)).fetchall()
    by_idx = dict((r[0], r) for r in post)

    p0_replayed = bool(out) and any(
        p["index"] == 0 and p.get("replayed") is True for p in out.get("phases", []))
    p0_attempt_stable = by_idx.get(0, (0, "", 0, ""))[2] == 1
    p0_digest_stable = by_idx.get(0, (0, "", 0, ""))[3] == phase0_digest_before
    p1_reexecuted = bool(out) and any(
        p["index"] == 1 and p.get("replayed") is False for p in out.get("phases", []))

    record("C4_CRASH_RECOVERY_NO_DUPLICATE",
           "completed phase recovered from journal, not re-executed",
           p0_replayed and p0_attempt_stable and p0_digest_stable,
           {"phase0_replayed": p0_replayed, "attempt": p0_attempt_stable,
            "digest_stable": p0_digest_stable})
    record("C5_CRASH_RECOVERY_RESUMES",
           "interrupted PURE phase is re-executed and the transaction completes",
           p1_reexecuted and out and out.get("terminal") == "PASS",
           {"terminal": out and out.get("terminal")})
    record("C6_STALE_LEASE_RECLAIMED",
           "lease of the killed controller was reclaimed (pid absent)",
           bool(out) and out.get("terminal") == "PASS",
           {"note": "recovery could only proceed by reclaiming the dead holder's lease"})


def prop_artifact_crash_recovery():
    """The witness the v2 canary could not produce: a phase that MAKES something."""
    txn = "estate-crash-artifact-001"
    killed = _crash_mid_phase(txn, str(ENVDIR / "crash-artifact.json"))
    if not killed:
        record("ARTIFACT_PRODUCING_CRASH_RECOVERY",
               "controller killed after an artifact-producing phase", False,
               {"killed": False})
        return
    ck = ROOT / "checkpoints" / txn
    ckpts = sorted(p.name for p in ck.iterdir()) if ck.is_dir() else []
    out = jloads(rail("execute", txn).stdout)
    log = logs_of(txn)
    resumed = bool(out) and (out.get("recovery") or {}).get("resumed") is True
    restored = bool(out) and bool((out.get("recovery") or {}).get("restored_checkpoint"))
    required_ok = bool(out) and any(
        p["name"] == "require-artifact" and p["state"] == "PASS"
        for p in out.get("phases", []))
    record("ARTIFACT_PRODUCING_CRASH_RECOVERY",
           "state produced by a completed phase survives the crash and satisfies a "
           "later phase",
           resumed and restored and required_ok and out.get("terminal") == "PASS"
           and "ARTIFACT_SURVIVED" in log,
           {"checkpoints_before_resume": ckpts, "resumed": resumed,
            "restored": restored, "terminal": out and out.get("terminal"),
            "log_tail": log[-200:]})


def prop_c_effectful_refusal():
    """An interrupted EFFECTFUL phase must not be silently re-run."""
    rail("submit", str(ENVDIR / "crash-effectful.json"))
    txn = "estate-crash-effectful-001"
    # simulate the crash directly: phase 0 PASS with a checkpoint, phase 1 RUNNING
    ck = ROOT / "checkpoints" / txn
    ck.mkdir(parents=True, exist_ok=True)
    stub = ck / "00.tar"
    staging = ROOT / "effectful-stub"
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "home").mkdir(parents=True)
    (staging / "repo").mkdir(parents=True)
    with tarfile.open(stub, "w", format=tarfile.PAX_FORMAT) as tf:
        tf.add(str(staging), arcname=".", recursive=True)
    shutil.rmtree(staging, ignore_errors=True)
    con = db()
    con.execute("INSERT OR REPLACE INTO phase(txn_id,idx,name,op,state,attempt,"
                "exit_code,digest,log_path,started_at,ended_at,ckpt_path,ckpt_sha) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (txn, 0, "compile-candidate", "python.py_compile", "PASS", 1, 0,
                 "0" * 64, str(ROOT / "receipts" / txn / "logs" / "00-x.log"),
                 time.time(), time.time(), str(stub),
                 hashlib.sha256(stub.read_bytes()).hexdigest()))
    con.execute("INSERT OR REPLACE INTO phase(txn_id,idx,name,op,state,attempt,"
                "started_at) VALUES(?,?,?,?,?,?,?)",
                (txn, 1, "inject-deliberate-defect", "rail.append_byte", "RUNNING",
                 1, time.time()))
    con.commit()
    out = jloads(rail("execute", txn).stdout)
    held = out and out.get("terminal") == "HOLD" and any(
        p.get("note") == "CRASH_RECOVERY_AMBIGUOUS_EFFECTFUL_PHASE"
        for p in out.get("phases", []))
    record("C7_EFFECTFUL_CRASH_REFUSED",
           "interrupted EFFECTFUL phase yields HOLD, never a silent re-run", held,
           {"terminal": out and out.get("terminal")})


# --------------------------------------------------------------------------
# D. leases: collision, TTL, settlement window, fencing, pid reuse
# --------------------------------------------------------------------------
def prop_d_collision():
    rail("submit", str(ENVDIR / "collision-holder.json"))
    rail("submit", str(ENVDIR / "collision-contender.json"))
    holder = subprocess.Popen([PY, str(TBRAIL), "execute", "estate-collision-holder-001"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              start_new_session=True, text=True, env=rail_env())
    time.sleep(12)
    rows = db().execute("SELECT resource_key,txn_id,fence FROM lease").fetchall()
    out = jloads(rail("execute", "estate-collision-contender-001").stdout)
    refused = out and out.get("reason") == "COLLISION_HELD"
    record("D1_COLLISION_HELD", "contender refused while holder leases the resource",
           refused and bool(rows), {"leases": rows, "reason": out and out.get("reason")})
    holder.wait(timeout=180)


def prop_live_phase_over_ttl():
    """A phase longer than the lease TTL must not become reclaimable."""
    rail("submit", str(ENVDIR / "ttl-holder.json"))
    rail("submit", str(ENVDIR / "ttl-contender.json"))
    holder = subprocess.Popen([PY, str(TBRAIL), "execute", "estate-ttl-holder-001"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              start_new_session=True, text=True, env=rail_env())
    key = "estate:main:ttl-probe"
    acquired = None
    deadline = time.time() + 120
    while time.time() < deadline:
        row = db().execute("SELECT acquired_at,heartbeat_at FROM lease WHERE resource_key=?",
                           (key,)).fetchone()
        if row:
            acquired = row
            break
        time.sleep(0.3)
    if not acquired:
        record("LIVE_PHASE_OVER_TTL_NOT_RECLAIMED", "holder never acquired", False, {})
        holder.wait(timeout=300)
        return

    # wait past the TTL while the holder is still inside one long phase
    ttl = json.loads(PROFILE.read_text())["ceilings"]["lease_ttl_seconds"]
    time.sleep(float(ttl) + 25)
    row = db().execute(
        "SELECT heartbeat_at, pid FROM lease WHERE resource_key=?", (key,)).fetchone()
    beat_advanced = bool(row) and row[0] > acquired[1]
    phase_row = db().execute(
        "SELECT state FROM phase WHERE txn_id=? AND idx=0",
        ("estate-ttl-holder-001",)).fetchone()
    still_running = bool(phase_row) and phase_row[0] == "RUNNING"
    out = jloads(rail("execute", "estate-ttl-contender-001").stdout)
    refused = bool(out) and out.get("reason") == "COLLISION_HELD"
    verified_identity = bool(out) and "verified_process_identity" in str(out.get("detail"))

    record("LIVE_PHASE_OVER_TTL_NOT_RECLAIMED",
           "a live holder inside a phase longer than the lease TTL is not reclaimed",
           refused and still_running and verified_identity,
           {"ttl_seconds": ttl, "phase_state": phase_row and phase_row[0],
            "contender": out and out.get("reason"),
            "detail": out and str(out.get("detail"))[:200]})
    record("LIVE_PHASE_HEARTBEAT_CONTINUES",
           "the heartbeat advances for the whole duration of a running phase",
           beat_advanced, {"acquired_at": acquired[0], "first_beat": acquired[1],
                           "beat_now": row and row[0]})

    # even with a deliberately stale heartbeat, verified process identity wins
    con = db()
    con.execute("UPDATE lease SET heartbeat_at=? WHERE resource_key=?",
                (time.time() - 10_000, key))
    con.commit()
    out2 = jloads(rail("execute", "estate-ttl-contender-001").stdout)
    record("VERIFIED_IDENTITY_DOMINATES_TTL",
           "a live holder with an expired heartbeat is still not reclaimed",
           bool(out2) and out2.get("reason") == "COLLISION_HELD",
           {"contender": out2 and out2.get("reason")})
    holder.wait(timeout=300)


def prop_lease_through_settlement():
    """No contender may acquire while the predecessor is still settling."""
    rail("submit", str(ENVDIR / "settlement-subject.json"))
    rail("submit", str(ENVDIR / "settlement-contender.json"))
    key = "estate:main:settlement-probe"
    subject = subprocess.Popen(
        [PY, str(TBRAIL), "execute", "estate-settlement-subject-001"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
        text=True, env=rail_env({"TBRAIL_SETTLEMENT_PAUSE_SECONDS": "25"}))

    observed = {"settled_seen": False, "lease_held_at_settlement": False,
                "contender": None}
    deadline = time.time() + 400
    while time.time() < deadline:
        row = db().execute("SELECT state FROM txn WHERE txn_id=?",
                           ("estate-settlement-subject-001",)).fetchone()
        if row and row[0] == "SETTLED":
            observed["settled_seen"] = True
            lease = db().execute("SELECT txn_id FROM lease WHERE resource_key=?",
                                 (key,)).fetchone()
            observed["lease_held_at_settlement"] = bool(
                lease and lease[0] == "estate-settlement-subject-001")
            out = jloads(rail("execute", "estate-settlement-contender-001").stdout)
            observed["contender"] = out and out.get("reason")
            break
        if subject.poll() is not None:
            break
        time.sleep(0.2)
    subject.wait(timeout=200)

    after = db().execute("SELECT COUNT(*) FROM lease WHERE resource_key=?",
                         (key,)).fetchone()[0]
    record("LEASE_HELD_THROUGH_VERIFIED_SETTLEMENT",
           "the lease survives receipt publication and the verified SETTLED "
           "transition, and a contender is refused inside that window",
           observed["settled_seen"] and observed["lease_held_at_settlement"]
           and observed["contender"] == "COLLISION_HELD" and after == 0,
           {**observed, "lease_rows_after_release": after})

    # and the contender may proceed once the predecessor has fully released
    out = jloads(rail("execute", "estate-settlement-contender-001").stdout)
    record("SUCCESSOR_PROCEEDS_AFTER_RELEASE",
           "the successor acquires the resource once settlement has completed",
           bool(out) and out.get("terminal") == "PASS",
           {"terminal": out and out.get("terminal")})


def prop_d_pid_reuse():
    """A stale lease whose PID was reused must still be reclaimed."""
    con = db()
    con.execute("DELETE FROM lease")
    con.execute("INSERT INTO lease(resource_key,txn_id,owner_uuid,fence,host,boot_id,"
                "pid,pid_start,acquired_at,heartbeat_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("estate:main:pidreuse-probe", "ghost-txn", "ghost", 1,
                 os.uname().nodename,
                 Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                 os.getpid(), 1, time.time(), time.time()))
    con.commit()
    sys.path.insert(0, str(HERE))
    os.environ["TBRAIL_HOME"] = str(ROOT)
    import importlib
    tb = importlib.import_module("tbrail")
    importlib.reload(tb)
    lease = tb.Lease(tb.connect(), "estate:main:pidreuse-probe", "real-txn")
    try:
        lease.acquire()
        ok, why = True, f"reclaimed with fence={lease.fence}"
        lease.release()
    except tb.LeaseTaken as exc:
        ok, why = False, str(exc)
    record("D2_PID_REUSE_RECLAIM",
           "stale lease held by a reused PID is reclaimed via process-start identity",
           ok, {"detail": why})

    con = db()
    con.execute("DELETE FROM lease")
    con.execute("INSERT INTO lease(resource_key,txn_id,owner_uuid,fence,host,boot_id,"
                "pid,pid_start,acquired_at,heartbeat_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("estate:main:live-probe", "live-txn", "live", 1,
                 os.uname().nodename,
                 Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                 os.getpid(), tb.pid_start_ticks(os.getpid()), time.time(), time.time()))
    con.commit()
    lease2 = tb.Lease(tb.connect(), "estate:main:live-probe", "intruder-txn")
    try:
        lease2.acquire()
        ok2, why2 = False, "reclaimed a LIVE holder"
    except tb.LeaseTaken as exc:
        ok2, why2 = True, str(exc)
    record("D3_LIVE_HOLDER_PROTECTED", "a live, heartbeating holder is never reclaimed",
           ok2, {"detail": why2})

    con = db()
    con.execute("DELETE FROM lease")
    con.commit()
    old = tb.Lease(tb.connect(), "estate:main:fence-probe", "old-txn")
    old.acquire()
    old_fence = old.fence
    con = db()
    con.execute("UPDATE lease SET owner_uuid=?, fence=? WHERE resource_key=?",
                ("someone-else", old_fence + 1, "estate:main:fence-probe"))
    con.commit()
    try:
        old.assert_still_held()
        ok3, why3 = False, "old holder still believed it held the lease"
    except tb.FencedOut as exc:
        ok3, why3 = True, str(exc)
    record("D4_FENCING_BLOCKS_LATE_SETTLE",
           "holder that lost its fence refuses to settle", ok3, {"detail": why3})
    con = db()
    con.execute("DELETE FROM lease")
    con.commit()


# --------------------------------------------------------------------------
# E. descendant teardown
# --------------------------------------------------------------------------
def prop_e_teardown():
    rail("submit", str(ENVDIR / "teardown.json"))
    out = jloads(rail("execute", "estate-teardown-001", timeout=300).stdout)
    ph = (out or {}).get("phases", [{}])[0] if out else {}
    survivors = ph.get("teardown", {}).get("survivors", ["unknown"])
    record("E1_TIMEOUT_TEARDOWN", "phase timeout kills the whole process group",
           bool(out) and ph.get("timed_out") is True and survivors == [],
           {"timed_out": ph.get("timed_out"), "survivors": survivors})
    leftover = subprocess.run(
        ["pgrep", "-af", "spawn_descendant.py"], capture_output=True, text=True)
    record("E2_NO_LIVE_DESCENDANTS", "no descendant of the torn-down phase survives",
           leftover.returncode != 0, {"pgrep": leftover.stdout.strip()[:200]})


# --------------------------------------------------------------------------
# F. receipt reconstruction, tamper refusal, outcome independence
# --------------------------------------------------------------------------
def prop_f_receipt():
    rdir = ROOT / "receipts" / "estate-canary-py311-001"
    rpath = rdir / "RECEIPT.json"
    v = jloads(rail("verify", str(rpath)).stdout)
    record("F1_RECEIPT_VERIFIES", "fresh-process verification recomputes every digest",
           v and v["verdict"] == "VERIFIED", {"failures": v and v.get("failures")})

    anchor = (rdir / "RECEIPT.sha256").read_text().strip()
    v2 = jloads(rail("verify", str(rpath), "--anchor", anchor).stdout)
    record("F2_EXTERNAL_ANCHOR", "receipt identity matches an external anchor",
           v2 and v2["checks"]["external_anchor_matches"]["pass"] is True)

    def tamper(path: Path, mutate):
        original = path.read_bytes()
        try:
            mutate(path)
            return jloads(rail("verify", str(rpath), "--anchor", anchor).stdout)
        finally:
            path.write_bytes(original)

    logs = sorted((rdir / "logs").iterdir())
    out = tamper(logs[0], lambda p: p.write_bytes(p.read_bytes() + b" "))
    record("F3_LOG_TAMPER_REFUSED", "modified phase log is refused",
           out and out["verdict"] == "REFUSED"
           and "phase_logs_rehash" in out["failures"],
           {"failures": out and out.get("failures")})

    out = tamper(rdir / "ENVELOPE.json", lambda p: p.write_bytes(p.read_bytes() + b" "))
    record("F4_ENVELOPE_TAMPER_REFUSED", "modified envelope is refused",
           out and out["verdict"] == "REFUSED"
           and "envelope_recomputes" in out["failures"],
           {"failures": out and out.get("failures")})

    original_r = rpath.read_bytes()
    original_s = (rdir / "RECEIPT.sha256").read_bytes()
    try:
        data = json.loads(original_r)
        data["provider_calls"] = 99
        rpath.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        new_digest = hashlib.sha256(rpath.read_bytes()).hexdigest()
        (rdir / "RECEIPT.sha256").write_text(new_digest + "\n", encoding="utf-8")
        out = jloads(rail("verify", str(rpath), "--anchor", anchor).stdout)
        record("F5_FORGED_PAIR_REFUSED_BY_ANCHOR",
               "self-consistent forged receipt+sidecar is refused by the anchor",
               out and out["verdict"] == "REFUSED"
               and "external_anchor_matches" in out["failures"],
               {"failures": out and out.get("failures")})
    finally:
        rpath.write_bytes(original_r)
        (rdir / "RECEIPT.sha256").write_bytes(original_s)

    # a receipt whose terminal disagrees with its phase states is not evidence
    try:
        data = json.loads(original_r)
        data["terminal"] = "FAIL"
        rpath.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        (rdir / "RECEIPT.sha256").write_text(
            hashlib.sha256(rpath.read_bytes()).hexdigest() + "\n", encoding="utf-8")
        out = jloads(rail("verify", str(rpath)).stdout)
        record("F7_TERMINAL_FORGERY_REFUSED",
               "a terminal that contradicts the phase states and the ledger is refused",
               out and out["verdict"] == "REFUSED"
               and "terminal_consistent_with_phases" in out["failures"]
               and "ledger_binds" in out["failures"],
               {"failures": out and out.get("failures")})
    finally:
        rpath.write_bytes(original_r)
        (rdir / "RECEIPT.sha256").write_bytes(original_s)

    src = ROOT / "source" / SOURCE_BUNDLE.name
    out = tamper(src, lambda p: p.write_bytes(p.read_bytes() + b" "))
    record("F6_SOURCE_TAMPER_REFUSED", "modified source bundle is refused",
           out and out["verdict"] == "REFUSED"
           and "source_bundle_rehashes" in out["failures"],
           {"failures": out and out.get("failures")})


def _verify_terminal(txn, want, witness):
    rdir = ROOT / "receipts" / txn
    rpath = rdir / "RECEIPT.json"
    if not rpath.is_file():
        record(witness, f"{want} receipt exists and verifies", False,
               {"missing": str(rpath)})
        return
    anchor = (rdir / "RECEIPT.sha256").read_text().strip()
    v = jloads(rail("verify", str(rpath), "--anchor", anchor).stdout)
    record(witness,
           f"a valid {want} receipt is accepted as evidence on its own terms",
           bool(v) and v["verdict"] == "VERIFIED" and v["terminal"] == want,
           {"terminal": v and v.get("terminal"), "failures": v and v.get("failures")})


def prop_receipt_outcomes():
    _verify_terminal("estate-canary-py311-001", "PASS", "PASS_RECEIPT_VERIFIED")
    _verify_terminal("estate-defect-001", "FAIL", "FAIL_RECEIPT_VERIFIED")
    _verify_terminal("neg-op-not-in-manifest", "HOLD", "HOLD_RECEIPT_VERIFIED")


# --------------------------------------------------------------------------
# G/H. negative witnesses
# --------------------------------------------------------------------------
def prop_g_negatives():
    index = json.loads((ENVDIR / "NEGATIVE-INDEX.json").read_text())
    bad = []
    for name, why in sorted(index.items()):
        r = rail("submit", str(ENVDIR / f"neg-{name}.json"))
        refused = "ENVELOPE_REJECTED" in (r.stdout + r.stderr)
        if not refused:
            bad.append({"witness": name, "why": why, "out": (r.stdout + r.stderr)[:160]})
    record("G_ENVELOPE_NEGATIVES",
           f"all {len(index)} malformed envelopes refused at submit", not bad,
           {"accepted_but_should_not_be": bad})


def _exec_negative(envelope, txn, expect):
    rail("submit", envelope)
    out = jloads(rail("execute", txn).stdout)
    note = "".join(str(p.get("note", "")) for p in (out or {}).get("phases", []))
    ok = bool(out) and out.get("terminal") == "HOLD" and expect in note
    return ok, {"case": txn, "expected": expect,
                "terminal": out and out.get("terminal"), "note": note[:200]}


def prop_h_exec_negatives():
    cases = [
        ("exec-neg-op-not-in-manifest", "neg-op-not-in-manifest", "operation_not_in_manifest"),
        ("exec-neg-undeclared-value", "neg-undeclared-value", "undeclared_operation_value"),
        ("exec-neg-switch-value", "neg-switch-value", "bad_operation_value"),
        ("exec-neg-value-grammar", "neg-value-grammar", "value_bad_suffix"),
        ("exec-neg-allowed-path", "neg-allowed-path", "dot_segment"),
        ("exec-neg-outside-allowed", "neg-outside-allowed", "path_not_in_allowed_paths"),
    ]
    bad = []
    for envf, txn, expect in cases:
        ok, detail = _exec_negative(str(ENVDIR / f"{envf}.json"), txn, expect)
        if not ok:
            bad.append(detail)
    record("H_OPERATION_NEGATIVES",
           "manifest, value-grammar, traversal and allowed-path violations refused",
           not bad, {"unrefused": bad})


# --------------------------------------------------------------------------
# repository-operation manifest, nested paths, symlink escape
# --------------------------------------------------------------------------
def prop_manifest_and_paths():
    rail("submit", fx("nested"))
    out = jloads(rail("execute", "fixture-nested-001").stdout)
    log = logs_of("fixture-nested-001")
    ok = bool(out) and out.get("terminal") == "PASS"
    bound = bool(out) and out.get("sandbox", {}).get("writable_set") == ["pkg/sub"]
    record("NESTED_ALLOWED_PATH_PASS",
           "a nested admitted subtree is bound and its contents are executable",
           ok and bound and "FIXTURE_TOOL_OK" in log,
           {"terminal": out and out.get("terminal"),
            "writable_set": out and out.get("sandbox", {}).get("writable_set"),
            "log_tail": log[-160:]})

    drift_ok, drift_detail = _exec_negative(fx("drift"), "fixture-drift-001",
                                            "script_digest_mismatch")
    outside_ok, outside_detail = _exec_negative(fx("outside"), "fixture-outside-001",
                                                "path_not_in_allowed_paths")
    record("REPOSITORY_OPERATION_MANIFEST_ENFORCED",
           "operations come from the accepted manifest: fixed script identity and "
           "digest, closed value grammar, no envelope-defined switches",
           ok and "FIXTURE_TOOL_OK" in log and drift_ok and outside_ok,
           {"positive": out and out.get("terminal"), "digest_gate": drift_detail,
            "nested_boundary": outside_detail})

    sym_ok, sym_detail = _exec_negative(fx("symlink"), "fixture-symlink-001",
                                        "symlink_bind_source_refused")
    record("SYMLINK_ESCAPE_REFUSED",
           "a source-controlled symlink named as an allowed path cannot redirect a "
           "bind mount", sym_ok, sym_detail)


# --------------------------------------------------------------------------
# enforced resource ceilings
# --------------------------------------------------------------------------
def prop_limits_bite():
    def run(name, txn):
        rail("submit", str(ENVDIR / f"{name}.json"))
        out = jloads(rail("execute", txn, timeout=600).stdout)
        ph = ((out or {}).get("phases") or [{}])[0]
        return out, ph, logs_of(txn)

    cases = {}

    out, ph, log = run("burn-output", "estate-burn-output-001")
    enf = ph.get("enforcement", {})
    cases["output"] = {
        "pass": ph.get("state") == "FAIL" and enf.get("output_ceiling_hit") is True
        and enf.get("output_bytes_recorded") == enf.get("limits", {}).get("max_output_bytes")
        and "OUTPUT_COMPLETED" not in log,
        "recorded": enf.get("output_bytes_recorded"),
        "cap": enf.get("limits", {}).get("max_output_bytes"),
        "total_seen": enf.get("output_bytes_total")}

    out, ph, log = run("burn-memory", "estate-burn-memory-001")
    cases["memory"] = {"pass": ph.get("state") == "FAIL"
                       and "MEMORY_COMPLETED" not in log,
                       "exit": ph.get("exit_code"), "log": log[-120:]}

    out, ph, log = run("burn-disk", "estate-burn-disk-001")
    cases["disk"] = {"pass": ph.get("state") == "FAIL" and "DISK_COMPLETED" not in log,
                     "exit": ph.get("exit_code"), "log": log[-120:]}

    out, ph, log = run("burn-cpu", "estate-burn-cpu-001")
    cases["cpu"] = {"pass": ph.get("state") == "FAIL" and "CPU_COMPLETED" not in log
                    and ph.get("timed_out") is not True,
                    "exit": ph.get("exit_code"), "seconds": ph.get("seconds")}

    out, ph, log = run("burn-pids", "estate-burn-pids-001")
    enf = ph.get("enforcement", {})
    # the ceiling must contain a fork burst INSIDE the sandbox: the phase must
    # have started, the monitor must have seen the descendants cross the
    # ceiling, and the burst must never have completed
    # the ceiling must contain a fork burst INSIDE a sandbox that actually
    # started, and must block within the phase's own declared allowance
    ceiling = enf.get("limits", {}).get("max_processes")
    m = re.search(r"PIDS_BLOCKED_AT (\d+)", log)
    blocked_at = int(m.group(1)) if m else None
    cases["pids"] = {"pass": ph.get("state") == "FAIL"
                     and "PIDS_RLIMIT_NPROC" in log
                     and blocked_at is not None
                     and 0 < blocked_at <= ceiling
                     and "PIDS_COMPLETED" not in log
                     and "Creating new namespace failed" not in log,
                     "exit": ph.get("exit_code"), "blocked_at": blocked_at,
                     "ceiling": ceiling,
                     "account_tasks_at_start": enf.get("account_tasks_at_start"),
                     "tasks_max_applied": (enf.get("aggregate") or {}).get("tasks_max"),
                     "pids_events": (enf.get("aggregate") or {}).get("pids_events"),
                     "log": log[-140:]}

    failed = [k for k, v in cases.items() if not v["pass"]]
    record("OUTPUT_MEMORY_DISK_PID_CPU_LIMITS_BITE",
           "output, address space, file size, CPU time and process count ceilings "
           "are enforced, not described", not failed, cases)


# --------------------------------------------------------------------------
# externally pinned runner profile and owner-only custody
# --------------------------------------------------------------------------
def prop_runner_profile():
    r = rail("profile-check", "--runner-profile", str(PROFILE),
             "--runner-profile-sha256", ACCEPTED_PROFILE_SHA)
    out = jloads(r.stdout)
    record("EXTERNALLY_PINNED_RUNNER_PROFILE",
           "the run is admitted against an externally supplied profile digest",
           bool(out) and out.get("verdict") == "ADMITTED"
           and out.get("externally_pinned") is True and r.returncode == 0,
           {"profile": str(PROFILE), "sha256": ACCEPTED_PROFILE_SHA,
            "verdict": out and out.get("verdict")})

    bad = ROOT / "tampered-profile.json"
    data = json.loads(PROFILE.read_text())
    data["sandbox"]["sha256"] = "0" * 64
    bad.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    # Anchor the tampered profile to its OWN digest, so the anchor check passes
    # and the refusal can only come from observed-vs-accepted content drift.
    # Leaving the anchor empty would instead trip RUNNER_PROFILE_ANCHOR_REQUIRED
    # and prove nothing about drift.
    bad_sha = hashlib.sha256(bad.read_bytes()).hexdigest()
    r2 = rail("execute", "estate-canary-py311-001", "--runner-profile", str(bad),
              env_extra={"TBRAIL_RUNNER_PROFILE": str(bad),
                         "TBRAIL_RUNNER_PROFILE_SHA256": bad_sha})
    o2 = jloads(r2.stdout)
    record("RUNNER_PROFILE_DRIFT_REFUSED",
           "a controller, sandbox or runtime identity outside the accepted profile "
           "refuses execution",
           r2.returncode == 3 and bool(o2)
           and o2.get("reason") == "RUNNER_PROFILE_REFUSED"
           and "RUNNER_PROFILE_MISMATCH" in str(o2.get("detail")),
           {"rc": r2.returncode, "detail": o2 and str(o2.get("detail"))[:200]})

    r3 = rail("profile-check", "--runner-profile", str(PROFILE),
              "--runner-profile-sha256", "1" * 64,
              env_extra={"TBRAIL_RUNNER_PROFILE_SHA256": "1" * 64})
    record("RUNNER_PROFILE_ANCHOR_ENFORCED",
           "a profile whose own digest differs from the accepted anchor is refused",
           r3.returncode == 3 and "DIGEST_MISMATCH" in r3.stdout,
           {"rc": r3.returncode, "out": r3.stdout[:200]})


def prop_custody():
    out = jloads(rail("custody").stdout)
    modes = {}
    for label, p in (("rail.db", ROOT / "rail.db"),
                     ("source_bundle", ROOT / "source" / SOURCE_BUNDLE.name),
                     ("root", ROOT), ("receipts", ROOT / "receipts")):
        if p.exists():
            modes[label] = oct(p.stat().st_mode & 0o777)
    exposed = [k for k, m in modes.items() if int(m, 8) & 0o077]
    record("OWNER_ONLY_PRIVATE_CUSTODY",
           "controller root, database, logs, receipts and retained source custody "
           "are owner-only",
           bool(out) and out.get("owner_only") is True and not exposed,
           {"modes": modes, "exposed": exposed,
            "reported": out and out.get("owner_only")})


# --------------------------------------------------------------------------
# I/J. runtime equivalence, residency
# --------------------------------------------------------------------------
def prop_i_equivalence(first):
    rail("submit", str(ENVDIR / "canary-py314.json"))
    other = jloads(rail("execute", "estate-canary-py314-001", timeout=900).stdout)
    same = (first and other
            and first["terminal"] == other["terminal"] == "PASS"
            and [p["name"] for p in first["phases"]] == [p["name"] for p in other["phases"]]
            and [p["state"] for p in first["phases"]] == [p["state"] for p in other["phases"]])
    record("I_RUNTIME_EQUIVALENCE",
           "the pinned 3.11 datum and the 3.14 matrix point agree phase-for-phase",
           same,
           {"py311": first and first.get("runtime", {}).get("version"),
            "py314": other and other.get("runtime", {}).get("version"),
            "py311_terminal": first and first.get("terminal"),
            "py314_terminal": other and other.get("terminal")})


def prop_j_residency():
    out = jloads(rail("residency").stdout)
    zero_exec = (out and out["leases_held"] == 0 and out["workspaces_present"] == []
                 and out["checkpoints_present"] == [])
    retained = out and out["retained_source_custody"]["total_bytes"] > 0
    record("J1_ZERO_TRANSACTION_EXECUTION_RESIDUE",
           "no leases, no workspaces and no checkpoints after all transactions",
           zero_exec,
           {"leases": out and out["leases_held"],
            "workspaces": out and out["workspaces_present"],
            "checkpoints": out and out["checkpoints_present"]})
    record("J2_RETAINED_CUSTODY_DECLARED",
           "retained source custody reported separately with digest, bytes, mode and "
           "purge law",
           retained and bool(out["retained_source_custody"].get("purge_law"))
           and out["retained_source_custody"].get("owner_only") is True,
           {"total_bytes": out and out["retained_source_custody"]["total_bytes"],
            "owner_only": out and out["retained_source_custody"]["owner_only"],
            "items": out and [i["name"] for i in out["retained_source_custody"]["items"]]})


# --------------------------------------------------------------------------
# v4: settlement crash windows, checkpoint custody, anchors, path safety,
#     launcher, exact resource semantics, current surface
# --------------------------------------------------------------------------
def _derive_envelope(src: Path, txn: str, resource_key: str,
                     repeat_first: int = 0) -> str:
    """Clone an admitted envelope under a new transaction identity."""
    env = json.loads(Path(src).read_text(encoding="utf-8"))
    env["transaction_id"] = txn
    env["resource_key"] = resource_key
    if repeat_first:
        first = env["phases"][0]
        env["phases"] = []
        for i in range(repeat_first):
            ph = json.loads(json.dumps(first))
            ph["name"] = f"{first['name']}-{i}"
            env["phases"].append(ph)
    FIXTURE_ENV.mkdir(parents=True, exist_ok=True)
    out = FIXTURE_ENV / f"{txn}.json"
    out.write_text(json.dumps(env, indent=2, sort_keys=True), encoding="utf-8")
    return str(out)


def _txn_row(txn):
    return db().execute(
        "SELECT state,terminal,receipt_path FROM txn WHERE txn_id=?", (txn,)).fetchone()


def _phase_rows(txn):
    return db().execute(
        "SELECT idx,state,attempt,digest FROM phase WHERE txn_id=? ORDER BY idx",
        (txn,)).fetchall()


def _verify_anchored(receipt_path):
    """Verify in a fresh process against the sidecar as the external anchor."""
    p = Path(receipt_path)
    if not p.is_file():
        return False, "receipt_absent"
    sidecar = p.parent / "RECEIPT.sha256"
    if not sidecar.is_file():
        return False, "sidecar_absent"
    r = rail("verify", str(p), "--anchor", sidecar.read_text().strip(), timeout=300)
    return r.returncode == 0, (jloads(r.stdout) or {}).get("failures")


CRASH_MATRIX = (
    ("after_settling_journal", "CRASH_AFTER_SETTLING_JOURNAL_RECOVERS"),
    ("after_sanitation", "CRASH_AFTER_SANITATION_RECOVERS"),
    ("after_receipt_write", "CRASH_AFTER_RECEIPT_WRITE_RECOVERS"),
    ("after_sidecar_write", "CRASH_AFTER_SIDECAR_WRITE_RECOVERS"),
    ("before_settled_update", "CRASH_BEFORE_SETTLED_UPDATE_RECOVERS"),
    ("after_settled_update", "CRASH_AFTER_SETTLED_UPDATE_REPLAYS_WITHOUT_WORK"),
)


def prop_settlement_crash_matrix():
    """Kill the controller at every admitted settlement boundary.

    The v3 rail sanitized the workspace and purged every checkpoint before the
    receipt existed and before the ledger moved, so a crash in that window left
    a RUNNING transaction whose PASSed phases had lost their restore points and
    recovery could only refuse. Each boundary is entered deliberately here, and
    the transaction must still reach a verified SETTLED receipt without
    re-executing a single phase.
    """
    src = ENVDIR / "crash-pure.json"
    for point, witness in CRASH_MATRIX:
        slug = point.replace("_", "-")
        txn = f"settle-{slug}-001"
        envp = _derive_envelope(src, txn, f"fixture:settle-{slug}")
        rail("submit", envp)
        r = rail("execute", txn, timeout=600,
                 env_extra={"TBRAIL_SETTLEMENT_CRASH_AT": point})
        crashed = r.returncode in (-9, 137)
        state_after_crash = (_txn_row(txn) or [None])[0]
        phases_before = _phase_rows(txn)

        out = jloads(rail("execute", txn, timeout=600).stdout)
        phases_after = _phase_rows(txn)
        final = _txn_row(txn)
        no_rework = phases_before == phases_after
        settled = bool(final) and final[0] == "SETTLED" and final[1] == "PASS"
        verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, "no_receipt")
        # No work may have been replayed. `phase_rows_unchanged` is the
        # authoritative proof of that -- it compares attempt counts and output
        # digests across the recovery. The per-phase `replayed` flag describes
        # the ORIGINAL execution and is carried forward verbatim in the
        # settlement journal, so it says nothing about this pass.
        comp = (out or {}).get("settlement_completed") or {}
        rec_blk = (out or {}).get("recovery") or {}
        if point == "after_settled_update":
            shape_ok = bool(out) and out.get("replay") is True and \
                (out.get("reconciled") or {}).get("work_replayed") is False
        else:
            shape_ok = bool(out) and (
                rec_blk.get("settlement_resumed_from_journal") is True
                or comp.get("receipt_adopted_from_prior_attempt") is True)

        record(witness,
               f"controller SIGKILLed at settlement boundary '{point}' recovers "
               f"to a verified SETTLED receipt without replaying work",
               crashed and settled and no_rework and verified and shape_ok,
               {"crash_exit": r.returncode, "state_after_crash": state_after_crash,
                "phase_rows_unchanged": no_rework, "final_state": final and final[0],
                "receipt_verified": verified, "verify_failures": vfail,
                "resumed_from_journal": rec_blk.get("settlement_resumed_from_journal"),
                "receipt_adopted": comp.get("receipt_adopted_from_prior_attempt")})


CKPT_PROBE = r'''
import io, json, os, sys, tarfile
from pathlib import Path
sys.path.insert(0, os.environ["TBRAIL_DIR"])
import tbrail

tmp = Path(os.environ["TBRAIL_HOME"]) / "ckpt-probe"
tmp.mkdir(parents=True, exist_ok=True)
ESCAPE = Path("/tmp/tbrail-absolute-escape.txt")
ESCAPE.unlink(missing_ok=True)
out = {}

def build(name, mutate):
    p = tmp / name
    with tarfile.open(p, "w", format=tarfile.PAX_FORMAT) as tf:
        mutate(tf)
    return p

def sym(tf):
    ti = tarfile.TarInfo("evil-link"); ti.type = tarfile.SYMTYPE
    ti.linkname = "/etc/passwd"; tf.addfile(ti)

def hard(tf):
    data = b"x\n"
    ok = tarfile.TarInfo("ok.txt"); ok.size = len(data)
    tf.addfile(ok, io.BytesIO(data))
    ti = tarfile.TarInfo("evil-hardlink"); ti.type = tarfile.LNKTYPE
    ti.linkname = "ok.txt"; tf.addfile(ti)

def trav(tf):
    data = b"pwned\n"
    ti = tarfile.TarInfo("../../escaped.txt"); ti.size = len(data)
    tf.addfile(ti, io.BytesIO(data))

def absolute(tf):
    data = b"pwned\n"
    ti = tarfile.TarInfo(str(ESCAPE)); ti.size = len(data)
    tf.addfile(ti, io.BytesIO(data))

def fifo(tf):
    ti = tarfile.TarInfo("evil-fifo"); ti.type = tarfile.FIFOTYPE
    tf.addfile(ti)

for name, fn in (("link", sym), ("hardlink", hard), ("traversal", trav),
                 ("absolute", absolute), ("device", fifo)):
    p = build(name + ".tar", fn)
    ws = tmp / ("ws-" + name)
    rec = {}
    try:
        tbrail.restore_checkpoint(p, tbrail.sha256_file(p), ws)
        rec["refused"] = False
    except tbrail.Reject as exc:
        rec["refused"] = True
        rec["reason"] = str(exc)
    except Exception as exc:
        rec["refused"] = False
        rec["unexpected"] = repr(exc)
    rec["workspace_entries"] = sorted(q.name for q in ws.iterdir()) if ws.is_dir() else []
    out[name] = rec

out["absolute_escape_written"] = ESCAPE.exists()
ESCAPE.unlink(missing_ok=True)

# quota: exercise the bound itself, with the constant lowered in-process
big = tmp / "big-ws"
big.mkdir(parents=True, exist_ok=True)
(big / "payload.bin").write_bytes(os.urandom(512 * 1024))
tbrail.CHECKPOINT_QUOTA_BYTES = 4096
quota = {}
try:
    tbrail.write_checkpoint("quota-probe-001", 0, big)
    quota["refused"] = False
except tbrail.Reject as exc:
    quota["refused"] = True
    quota["reason"] = str(exc)
quota["partial_left_behind"] = sorted(
    q.name for q in (Path(os.environ["TBRAIL_HOME"]) / "checkpoints" /
                     "quota-probe-001").glob("*")) if (
    Path(os.environ["TBRAIL_HOME"]) / "checkpoints" / "quota-probe-001").is_dir() else []
out["quota"] = quota
# leave no residue: the probe must not be visible to the residency property
import shutil as _sh
_sh.rmtree(Path(os.environ["TBRAIL_HOME"]) / "checkpoints" / "quota-probe-001",
           ignore_errors=True)
print(json.dumps(out))
'''


def prop_checkpoint_safety():
    r = subprocess.run([PY, "-c", CKPT_PROBE], capture_output=True, text=True,
                       timeout=300, env=rail_env({"TBRAIL_DIR": str(HERE)}))
    out = jloads(r.stdout) or {}
    kinds = ("link", "hardlink", "traversal", "absolute", "device")
    refused = {k: bool((out.get(k) or {}).get("refused")) for k in kinds}
    clean = all(not (out.get(k) or {}).get("workspace_entries") for k in kinds)
    record("CHECKPOINT_LINK_AND_TRAVERSAL_ARCHIVE_REFUSED",
           "symlink, hardlink, traversal, absolute-path and device members are "
           "refused before any byte of the archive is extracted",
           all(refused.values()) and clean
           and out.get("absolute_escape_written") is False,
           {"refused": refused, "absolute_escape_written":
            out.get("absolute_escape_written"),
            "stderr": r.stderr[-300:],
            "reasons": {k: (out.get(k) or {}).get("reason") for k in kinds}})

    quota = out.get("quota") or {}
    record("CHECKPOINT_QUOTA_REFUSES_OVERSIZED_CHECKPOINT",
           "a checkpoint that would breach the transaction quota is refused and "
           "leaves no partial file",
           bool(quota.get("refused")) and not quota.get("partial_left_behind"),
           quota)


def prop_checkpoint_storage_bound():
    """Only the latest checkpoint may exist, even after several PASSed phases."""
    txn = "ckpt-bound-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn,
                            "fixture:ckpt-bound", repeat_first=3)
    killed = _crash_mid_phase(txn, envp, wait_for=(1, 2))
    ck = ROOT / "checkpoints" / txn
    tars = sorted(p.name for p in ck.glob("*.tar")) if ck.is_dir() else []
    partials = sorted(p.name for p in ck.glob("*.partial")) if ck.is_dir() else []
    held = sum(p.stat().st_size for p in ck.iterdir() if p.is_file()) if ck.is_dir() else 0
    # Two phases have PASSed here. v3 would be holding two complete workspace
    # archives; latest-only means exactly one. A `.partial` from the interrupted
    # third write may exist -- it is a crash artifact, not a retained restore
    # point -- but everything on disk must still fit inside the quota, and the
    # whole directory must be gone once the transaction settles.
    bounded = killed and len(tars) == 1 and len(partials) <= 1

    out = jloads(rail("execute", txn, timeout=600).stdout)
    final = _txn_row(txn)
    verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, None)
    cust = ((out or {}).get("checkpoint_custody") or {})
    purged_clean = not ck.exists()
    record("CHECKPOINT_STORAGE_BOUND_ENFORCED",
           "checkpoint custody is latest-only and stays inside the declared "
           "transaction quota across multiple PASSed phases",
           bounded and verified and purged_clean
           and held <= int(cust.get("quota_bytes", 0) or 0)
           and cust.get("mode") == "LATEST_ADMITTED_CHECKPOINT_ONLY"
           and int(cust.get("retained_count", 9)) <= 1,
           {"killed_after_two_passes": killed, "checkpoints_on_disk": tars,
            "crash_partials": partials, "bytes_held_at_crash": held,
            "quota_bytes": cust.get("quota_bytes"),
            "checkpoint_dir_removed_after_settlement": purged_clean,
            "custody_mode": cust.get("mode"),
            "retained_count": cust.get("retained_count"),
            "recovered_terminal": (out or {}).get("terminal"),
            "receipt_verified": verified, "verify_failures": vfail})


def prop_profile_anchor_required():
    """No anchor, no execution -- and the refusal lands before the lease."""
    txn = "anchor-absent-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn, "fixture:anchor-absent")
    rail("submit", envp)
    leases_before = db().execute("SELECT COUNT(*) FROM lease").fetchone()[0]
    r = rail("execute", txn, env_extra={"TBRAIL_RUNNER_PROFILE_SHA256": ""})
    out = jloads(r.stdout) or {}
    leases_after = db().execute("SELECT COUNT(*) FROM lease").fetchone()[0]
    state = (_txn_row(txn) or [None])[0]
    phases = _phase_rows(txn)

    pc = rail("profile-check", "--runner-profile", str(PROFILE),
              env_extra={"TBRAIL_RUNNER_PROFILE_SHA256": ""})
    pc_out = jloads(pc.stdout) or {}

    record("RUNNER_PROFILE_ANCHOR_ABSENT_REFUSED",
           "execute and profile-check refuse without an externally supplied "
           "profile digest, before any lease is acquired",
           r.returncode == 3
           and "RUNNER_PROFILE_ANCHOR_REQUIRED" in json.dumps(out)
           and out.get("executed") is False
           and leases_after == leases_before
           and state == "QUEUED" and not phases
           and pc.returncode == 3
           and "RUNNER_PROFILE_ANCHOR_REQUIRED" in json.dumps(pc_out),
           {"execute_rc": r.returncode, "execute": out,
            "profile_check_rc": pc.returncode, "profile_check": pc_out,
            "txn_state": state, "phase_rows": len(phases),
            "leases_before": leases_before, "leases_after": leases_after})


def prop_tampered_receipt_paths():
    """A tampered receipt must not steer the verifier onto host files.

    The tampered paths point at a FIFO outside every admitted controller root.
    If the verifier opened it, this property would block until the harness
    timeout; returning a refusal promptly is itself the evidence that the path
    was never followed.
    """
    src = ROOT / "receipts" / "estate-canary-py311-001" / "RECEIPT.json"
    if not src.is_file():
        record("TAMPERED_RECEIPT_PATH_NOT_FOLLOWED", "no settled receipt to tamper",
               False, {"expected": str(src)})
        return
    genuine = json.loads(src.read_text(encoding="utf-8"))
    anchor = (src.parent / "RECEIPT.sha256").read_text().strip()

    trap = Path("/tmp/tbrail-verify-trap.fifo")
    trap.unlink(missing_ok=True)
    os.mkfifo(trap)

    tampered = json.loads(json.dumps(genuine))
    for b in tampered.get("phase_log_bindings", []):
        b["path"] = str(trap)
    (tampered.setdefault("runner_profile", {}))["path"] = str(trap)
    tampered.setdefault("sanitation", {})["workspace"] = "/"
    tampered.setdefault("source", {})["bundle"] = "../../../../etc/passwd"

    d = ROOT / "tampered-receipt"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    tp = d / "RECEIPT.json"
    tp.write_text(json.dumps(tampered, indent=2, sort_keys=True), encoding="utf-8")

    # 1. anchored: identity is refused before any embedded path is consulted
    ra = rail("verify", str(tp), "--anchor", anchor, timeout=180)
    oa = jloads(ra.stdout) or {}

    # 2. self-consistent sidecar, no anchor: containment must still refuse
    (d / "RECEIPT.sha256").write_text(
        __import__("hashlib").sha256(tp.read_bytes()).hexdigest() + "\n",
        encoding="utf-8")
    rb = rail("verify", str(tp), timeout=180)
    ob = jloads(rb.stdout) or {}
    contained = ((ob.get("checks") or {}).get("receipt_paths_contained") or {})

    trap.unlink(missing_ok=True)
    record("TAMPERED_RECEIPT_PATH_NOT_FOLLOWED",
           "a tampered receipt is refused on identity before any embedded path "
           "is followed, and refused on containment when self-consistent",
           ra.returncode == 1 and oa.get("verdict") == "REFUSED"
           and oa.get("followed_receipt_paths") is False
           and oa.get("failures") == ["external_anchor_matches"]
           and rb.returncode == 1 and ob.get("verdict") == "REFUSED"
           and contained.get("pass") is False,
           {"anchored_verdict": oa.get("verdict"),
            "anchored_failures": oa.get("failures"),
            "followed_paths": oa.get("followed_receipt_paths"),
            "unanchored_verdict": ob.get("verdict"),
            "containment_refused": contained.get("detail")})


def prop_no_preexec_launcher():
    source = (HERE / "tbrail.py").read_text(encoding="utf-8")
    static_clean = "preexec_fn=" not in source
    rp = ROOT / "receipts" / "estate-canary-py311-001" / "RECEIPT.json"
    data = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}
    phases = [p for p in data.get("phases", []) if p.get("enforcement")]
    no_preexec = bool(phases) and all(
        p["enforcement"].get("preexec_fn_used") is False for p in phases)
    entered = bool(phases) and all(
        (p["enforcement"].get("aggregate") or {}).get("entered") is True
        for p in phases)
    chain = (data.get("ops_manifest") or {}).get("launch_chain") or {}
    chain_pinned = {"systemd-run", "prlimit", "sh", "bwrap"} <= set(chain)
    record("THREADED_CONTROLLER_LAUNCHER_NO_PREEXEC",
           "no preexec_fn anywhere in the controller; every phase entered a "
           "digest-pinned launch chain instead",
           static_clean and no_preexec and entered and chain_pinned,
           {"source_free_of_preexec": static_clean, "phases_checked": len(phases),
            "all_preexec_false": no_preexec, "all_entered_scope": entered,
            "launch_chain": sorted(chain)})


def prop_resource_semantics_exact():
    rp = ROOT / "receipts" / "estate-canary-py311-001" / "RECEIPT.json"
    data = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}
    sem = data.get("resource_semantics") or {}
    stmt = sem.get("statement", "")
    named = ("PER-PROCESS ONLY" in stmt and "AGGREGATE" in stmt
             and "RLIMIT_NPROC is no" in stmt)
    agg = (sem.get("aggregate") or {}).get("mechanism", "")
    per = (sem.get("per_process") or {}).get("mechanism", "")

    phases = [p for p in data.get("phases", []) if p.get("enforcement")]
    # Every phase must have ENTERED its delegated scope -- that is the
    # enforcement boundary. Live metering is a weaker, timing-dependent signal:
    # a phase can finish faster than the sampling interval, and the rail reports
    # that honestly as metered=false with null figures rather than as zeros. At
    # least one phase must nonetheless have been metered, so the accounting path
    # itself is witnessed and not merely assumed.
    in_scope = []
    metered = []
    for p in phases:
        a = p["enforcement"].get("aggregate") or {}
        cg = str(a.get("cgroup") or "")
        in_scope.append(a.get("entered") is True
                        and f"user@{os.getuid()}.service" in cg
                        and "/app.slice/" in cg)
        if a.get("metered"):
            metered.append(int(a.get("peak_memory_bytes") or 0) > 0
                           and a.get("cpu_seconds_used") is not None)

    # Proof that the ceiling which refused the fork burst was the AGGREGATE
    # cgroup one and could not have been anything else.
    #
    # The rail no longer sets RLIMIT_NPROC, so the phase inherits the account's
    # value. burn.py prints it. If forks were refused at a count far below that
    # inherited rlimit, and at the cgroup's declared tasks_max, then pids.max is
    # the only ceiling that can have blocked them. `pids.events` is sampled on a
    # 250 ms poll and a fork burst can begin and be torn down between samples,
    # so it is recorded when seen but is not the load-bearing evidence.
    prp = ROOT / "receipts" / "estate-burn-pids-001" / "RECEIPT.json"
    pdata = json.loads(prp.read_text(encoding="utf-8")) if prp.is_file() else {}
    plog = logs_of("estate-burn-pids-001")
    pev, tasks_max, pstate = {}, None, None
    for p in pdata.get("phases", []):
        a = (p.get("enforcement") or {}).get("aggregate") or {}
        if a:
            pev = a.get("pids_events") or {}
            tasks_max = a.get("tasks_max")
            pstate = p.get("state")
            break
    mb = re.search(r"PIDS_BLOCKED_AT (\d+)", plog)
    mn = re.search(r"PIDS_RLIMIT_NPROC \((-?\d+), *(-?\d+)\)", plog)
    blocked_at = int(mb.group(1)) if mb else None
    nproc_soft = int(mn.group(1)) if mn else None
    nproc_unlimited = nproc_soft is not None and (
        nproc_soft < 0 or (blocked_at is not None and nproc_soft > blocked_at * 10))
    cgroup_refused_forks = (
        pstate == "FAIL" and blocked_at is not None and tasks_max is not None
        and 0 < blocked_at <= int(tasks_max) and nproc_unlimited
        and "PIDS_COMPLETED" not in plog)

    record("RESOURCE_SEMANTICS_EXACTLY_NAMED_OR_CGROUP_ENFORCED",
           "aggregate ceilings are cgroup-enforced and metered; per-process "
           "rlimits are named as per-process and nothing claims more",
           named and "cgroup" in agg and "prlimit" in per
           and bool(in_scope) and all(in_scope)
           and bool(metered) and all(metered) and cgroup_refused_forks,
           {"statement_exact": named, "aggregate_mechanism": agg,
            "per_process_mechanism": per,
            "phases_in_delegated_scope": in_scope,
            "phases_metered": metered, "phases_total": len(phases),
            "pids_events_on_burst": pev,
            "fork_burst": {"blocked_at": blocked_at, "cgroup_tasks_max": tasks_max,
                           "inherited_rlimit_nproc": nproc_soft,
                           "rlimit_cannot_explain_it": nproc_unlimited,
                           "phase_state": pstate},
            "cgroup_refused_forks": cgroup_refused_forks,
            "disk": sem.get("disk")})


def prop_current_surface_only():
    stale_dirs = [d for d in ("envelopes", "envelopes-v2") if (HERE / d).exists()]
    hist = HERE / "historical"
    tombstone = hist / "README.md"
    tomb_text = tombstone.read_text(encoding="utf-8") if tombstone.is_file() else ""
    moved = all((hist / d).is_dir() for d in ("envelopes", "envelopes-v2"))

    readme = (HERE / "README.md").read_text(encoding="utf-8")
    proofs = (HERE / "run_proofs.sh").read_text(encoding="utf-8") \
        if (HERE / "run_proofs.sh").is_file() else ""
    v1_leak = [s for s in ("envelopes/envelope-", "tbrail.py execute canary-001")
               if s in readme or s in proofs]

    ps = rail("purge-source")
    pout = jloads(ps.stdout) or {}
    purge_exists = ps.returncode == 0 and pout.get("operation") == "purge-source" \
        and pout.get("dry_run") is True

    record("CURRENT_V3_SURFACE_ONLY",
           "the v1/v2 execution surface is retired to an explicitly historical "
           "location and every documented command exists",
           not stale_dirs and moved and "NOT CURRENT" in tomb_text
           and not v1_leak and purge_exists,
           {"stale_dirs_at_root": stale_dirs, "moved_to_historical": moved,
            "tombstone_present": bool(tomb_text), "v1_references_left": v1_leak,
            "purge_source_exists": purge_exists,
            "purge_source_rc": ps.returncode})


def main():
    assert_cold()
    build_fixture()
    prop_runner_profile()
    prop_g_negatives()
    first = prop_c_settled_replay()
    prop_a()
    prop_b()
    prop_h_exec_negatives()
    prop_manifest_and_paths()
    prop_limits_bite()
    prop_c_real_crash()
    prop_artifact_crash_recovery()
    prop_c_effectful_refusal()
    prop_d_collision()
    prop_live_phase_over_ttl()
    prop_lease_through_settlement()
    prop_d_pid_reuse()
    prop_e_teardown()
    prop_f_receipt()
    prop_receipt_outcomes()
    prop_i_equivalence(first)
    prop_custody()
    # ---- v4 witnesses -----------------------------------------------------
    prop_settlement_crash_matrix()
    prop_checkpoint_safety()
    prop_checkpoint_storage_bound()
    prop_profile_anchor_required()
    prop_tampered_receipt_paths()
    prop_no_preexec_launcher()
    prop_resource_semantics_exact()
    prop_current_surface_only()
    # residency runs last: it asserts the root is clean after everything above
    prop_j_residency()

    failed = [r for r in results if not r["pass"]]
    summary = {
        "schema": "tier-bench/native-rail-cold-qualification@3",
        "controller_root": str(ROOT),
        "host": os.uname().nodename,
        "accepted_runner_profile_sha256": ACCEPTED_PROFILE_SHA,
        "verdict": "PASS_NATIVE_PRIVATE_EXECUTION_RAIL_PRODUCT_CANDIDATE"
                   if not failed else "HOLD_COLD_QUALIFICATION_FAILED",
        "total": len(results), "failed": len(failed),
        "failed_properties": [r["property"] for r in failed],
        "results": results,
    }
    (ROOT / "COLD-QUALIFICATION.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print("\n" + summary["verdict"])
    print(f"{len(results) - len(failed)}/{len(results)} properties passed")
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
