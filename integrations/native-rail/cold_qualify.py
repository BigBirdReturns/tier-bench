#!/usr/bin/env python3
"""Cold qualification for the current (v5) native rail.

Runs from a FRESH controller root supplied on the command line. It never reads
or writes the operational ~/.tbrail, and it refuses to start if the root it is
given already holds a database, lease, workspace or receipt.

Usage:
    cold_qualify.py <fresh-root> <source-bundle> <accepted-runner-profile-sha256>
                    [accepted-runner-profile-path]

The runner-profile digest is an EXTERNAL input: it is read from the accepted
profile by the caller, quoted in the review packet, and enforced here. The run
cannot silently accept a controller, interpreter, sandbox engine, runtime
closure, rail script set or operation manifest that differs from the accepted
profile.

Two profiles are used. The ACCEPTED profile is the production admission and does
not admit the crash hooks. The QUALIFICATION profile is derived from it by
adding exactly one key, `_qualification_mode`, and is what admits the deliberate
crash windows -- so no production anchor can ever carry that permission and a
stale environment variable cannot kill a real transaction.

Covers the original A-J properties, the v4 witnesses, and the final
product-admission controls required by the exact-head second desk.
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
PROFILE = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else (
    HERE / f"RUNNER-PROFILE.{os.uname().nodename}.json")
QPROFILE = ROOT / "RUNNER-PROFILE.qualification.json"
QPROFILE_SHA: str | None = None
PY = sys.executable

# Controller-side material the launch chain must not pass on. The VALUES carry
# the marker the admitted credential probe scans for, so the witness proves the
# environment is closed rather than proving the controller happened to be empty.
SENTINEL = "TBRAIL-SENTINEL-"
SENTINEL_ENV = {
    "GH_TOKEN": SENTINEL + "gh-token",
    "GITHUB_TOKEN": SENTINEL + "github-token",
    "ANTHROPIC_API_KEY": SENTINEL + "anthropic-key",
    "AWS_SECRET_ACCESS_KEY": SENTINEL + "aws-secret",
    "SSH_AUTH_SOCK": "/run/user/0/" + SENTINEL + "agent.sock",
    "TBRAIL_UNRELATED_SECRET": SENTINEL + "generic",
}

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


def rail_env(extra=None, production_profile=False, sentinels=True):
    """Environment for a controller invocation.

    Every controller this qualification starts is deliberately loaded with
    credential-shaped variables. The rail's own closure is what must keep them
    out of the worker; a qualification run on a conveniently empty controller
    would prove nothing about a controller that holds a publication token.
    """
    e = dict(os.environ)
    if sentinels:
        e.update(SENTINEL_ENV)
    e["TBRAIL_HOME"] = str(ROOT)
    if production_profile or not QPROFILE_SHA:
        e["TBRAIL_RUNNER_PROFILE"] = str(PROFILE)
        if ACCEPTED_PROFILE_SHA:
            e["TBRAIL_RUNNER_PROFILE_SHA256"] = ACCEPTED_PROFILE_SHA
    else:
        e["TBRAIL_RUNNER_PROFILE"] = str(QPROFILE)
        e["TBRAIL_RUNNER_PROFILE_SHA256"] = QPROFILE_SHA
    e.pop("TBRAIL_SETTLEMENT_PAUSE_SECONDS", None)
    e.pop("TBRAIL_SETTLEMENT_CRASH_AT", None)
    e.pop("TBRAIL_CHECKPOINT_CRASH_AT", None)
    if extra:
        e.update(extra)
    return e


def rail_prod(*args, timeout=900, env_extra=None):
    """Run the controller under the ACCEPTED production profile."""
    return subprocess.run([PY, str(TBRAIL), *args], capture_output=True,
                          text=True, timeout=timeout,
                          env=rail_env(env_extra, production_profile=True))


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
    derive_qualification_profile()


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def derive_qualification_profile():
    """Derive the crash-admitting profile from the accepted one, and prove it.

    The derivation is a single documented key. Anything else -- a different
    controller digest, a different interpreter, a different runtime closure --
    would make this a different runner, and the diff below is what says it is
    not.
    """
    global QPROFILE_SHA
    accepted_sha = sha256_of(PROFILE)
    accepted = json.loads(PROFILE.read_text(encoding="utf-8"))
    if accepted_sha != ACCEPTED_PROFILE_SHA:
        print(f"REFUSING: accepted profile digest mismatch {accepted_sha}")
        raise SystemExit(2)
    derived = dict(accepted)
    derived["_qualification_mode"] = True
    QPROFILE.parent.mkdir(parents=True, exist_ok=True)
    QPROFILE.write_text(json.dumps(derived, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    QPROFILE_SHA = sha256_of(QPROFILE)
    delta = sorted(set(derived) ^ set(accepted)) + \
        sorted(k for k in set(derived) & set(accepted) if derived[k] != accepted[k])
    record("QUALIFICATION_PROFILE_DERIVED_FROM_ACCEPTED_PROFILE",
           "the crash-admitting profile differs from the externally accepted "
           "profile by exactly one documented key",
           delta == ["_qualification_mode"] and QPROFILE_SHA != accepted_sha,
           {"accepted_sha256": accepted_sha, "qualification_sha256": QPROFILE_SHA,
            "delta": delta})

    # The interpreter running this qualifier must BE the pinned interpreter.
    pinned = accepted.get("interpreter") or {}
    live = str(Path(os.path.realpath(sys.executable)))
    same = (pinned.get("path") == live
            and pinned.get("sha256") == (sha256_of(Path(live)) if Path(live).is_file() else None)
            and pinned.get("version") == "%d.%d.%d" % sys.version_info[:3])
    record("CONTROLLER_INTERPRETER_PROFILE_PINNED",
           "the accepted runner profile names the absolute path, version and "
           "digest of the interpreter, and this qualification runs under it",
           bool(pinned.get("path")) and bool(pinned.get("sha256")) and same,
           {"pinned": pinned, "qualifier_interpreter": live,
            "qualifier_version": "%d.%d.%d" % sys.version_info[:3]})


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
           "host_homes_mounted= []" in log and "credential_paths_visible= []" in log,
           {"log_tail": log[-200:]})


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

def under_symlink(tf):
    # the classic archive escape: a link, then a member written THROUGH it
    ti = tarfile.TarInfo("outdir"); ti.type = tarfile.SYMTYPE
    ti.linkname = "/tmp"; tf.addfile(ti)
    data = b"pwned\n"
    fi = tarfile.TarInfo("outdir/tbrail-absolute-escape.txt"); fi.size = len(data)
    tf.addfile(fi, io.BytesIO(data))

for name, fn in (("hardlink", hard), ("traversal", trav),
                 ("absolute", absolute), ("device", fifo),
                 ("under_symlink", under_symlink)):
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

# a plain symlink member is ADMITTED and materialized as a link, because a
# repository contains links and a restore point must round-trip its source
p = build("link.tar", sym)
ws = tmp / "ws-link"
rec = {}
try:
    tbrail.restore_checkpoint(p, tbrail.sha256_file(p), ws)
    rec["restored"] = True
    rec["is_symlink"] = (ws / "evil-link").is_symlink()
    rec["target"] = os.readlink(ws / "evil-link")
    rec["nothing_written_through_it"] = not (ws / "evil-link").is_dir()
except tbrail.Reject as exc:
    rec = {"restored": False, "reason": str(exc)}
out["symlink_admitted"] = rec

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
    kinds = ("hardlink", "traversal", "absolute", "device", "under_symlink")
    refused = {k: bool((out.get(k) or {}).get("refused")) for k in kinds}
    clean = all(not (out.get(k) or {}).get("workspace_entries") for k in kinds)
    record("CHECKPOINT_LINK_AND_TRAVERSAL_ARCHIVE_REFUSED",
           "hardlink, traversal, absolute-path, device and write-through-a-link "
           "members are refused before any byte of the archive is extracted",
           all(refused.values()) and clean
           and out.get("absolute_escape_written") is False,
           {"refused": refused, "absolute_escape_written":
            out.get("absolute_escape_written"),
            "stderr": r.stderr[-300:],
            "reasons": {k: (out.get(k) or {}).get("reason") for k in kinds}})

    adm = out.get("symlink_admitted") or {}
    record("CHECKPOINT_SYMLINK_MEMBER_ROUND_TRIPS_SAFELY",
           "a symbolic link is restored as a link, verbatim, and nothing is "
           "written through it",
           adm.get("restored") is True and adm.get("is_symlink") is True
           and adm.get("nothing_written_through_it") is True,
           adm)

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

    record("CURRENT_SURFACE_ONLY",
           "the v1/v2 execution surface is retired to an explicitly historical "
           "location and every documented command exists",
           not stale_dirs and moved and "NOT CURRENT" in tomb_text
           and not v1_leak and purge_exists,
           {"stale_dirs_at_root": stale_dirs, "moved_to_historical": moved,
            "tombstone_present": bool(tomb_text), "v1_references_left": v1_leak,
            "purge_source_exists": purge_exists,
            "purge_source_rc": ps.returncode})


# --------------------------------------------------------------------------
# final product-admission controls
# --------------------------------------------------------------------------
def _envelope_with_phases(src: Path, txn: str, resource_key: str,
                          phases: list) -> str:
    env = json.loads(Path(src).read_text(encoding="utf-8"))
    env["transaction_id"] = txn
    env["resource_key"] = resource_key
    env["phases"] = phases
    FIXTURE_ENV.mkdir(parents=True, exist_ok=True)
    out = FIXTURE_ENV / f"{txn}.json"
    out.write_text(json.dumps(env, indent=2, sort_keys=True), encoding="utf-8")
    return str(out)


def _receipt_of(txn):
    row = _txn_row(txn)
    if not row or not row[2] or not Path(row[2]).is_file():
        return None
    return jloads(Path(row[2]).read_text(encoding="utf-8"))


def prop_worker_environment_closed():
    """Sentinel secrets on the controller must not reach the operation."""
    txn = "env-closure-001"
    envp = _derive_envelope(ENVDIR / "isolation.json", txn, "fixture:env-closure")
    rail("submit", envp)
    out = jloads(rail("execute", txn, timeout=600).stdout)
    body = logs_of(txn)

    def field(name):
        for line in body.splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
        return None

    receipt = _receipt_of(txn) or {}
    envblocks = [ (p.get("enforcement") or {}).get("environment") or {}
                  for p in receipt.get("phases", []) if p.get("enforcement") ]
    cleared = bool(envblocks) and all(b.get("sandbox_clearenv") is True
                                      and b.get("controller_environment_inherited_by_launch") is False
                                      for b in envblocks)
    verified, vfail = _verify_anchored((_txn_row(txn) or [None, None, None])[2])
    ok = (field("undeclared_env_keys") == "[]"
          and field("secretish_env_keys") == "[]"
          and field("sentinel_env_keys") == "[]"
          and field("proc_environ_sentinel_present") == "False"
          and field("host_homes_mounted") == "[]"
          and field("credential_paths_visible") == "[]"
          and "CREDENTIAL_ISOLATION_HOLDS" in body
          and cleared and verified
          and (out or {}).get("terminal") == "PASS")
    record("CONTROLLER_SECRET_ENVIRONMENT_NOT_VISIBLE_TO_WORKER",
           "GitHub, provider, SSH-agent and generic secret variables injected "
           "into the controller are absent from the worker's environment and "
           "from its /proc/self/environ bytes",
           ok,
           {"injected_controller_keys": sorted(SENTINEL_ENV),
            "worker_env_keys": field("env_keys"),
            "undeclared": field("undeclared_env_keys"),
            "secretish": field("secretish_env_keys"),
            "sentinel_env_keys": field("sentinel_env_keys"),
            "proc_environ_sentinel_present": field("proc_environ_sentinel_present"),
            "sandbox_clearenv_recorded": cleared,
            "receipt_verified": verified, "verify_failures": vfail})


CKPT_V5_PROBE = r'''
import json, os, sys, tarfile
from pathlib import Path
sys.path.insert(0, os.environ["TBRAIL_DIR"])
import tbrail

home = Path(os.environ["TBRAIL_HOME"])
lab = home / "ckpt-v5"
out = {}

def fresh(name):
    d = lab / name
    if d.exists():
        import shutil; shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    return d

def ckpt_dir(txn):
    return tbrail.CHECKPOINT_ROOT / txn

# ---- 1. payload larger than the quota is refused before any byte is written
ws = fresh("oversize")
for i in range(64):
    (ws / f"f{i}.bin").write_bytes(b"z" * 8192)
tbrail.CHECKPOINT_QUOTA_BYTES = 64 * 1024
try:
    tbrail.write_checkpoint("probe-oversize", 0, ws)
    out["oversize"] = {"refused": False}
except tbrail.Reject as exc:
    d = ckpt_dir("probe-oversize")
    files = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
    out["oversize"] = {"refused": True, "reason": str(exc),
                       "files_left": files,
                       "bytes_held": sum((d / f).stat().st_size for f in files)}

# ---- 2. the quota binds WHILE streaming, not after a larger archive exists
# tiny payload, large tar overhead: the pre-flight passes and the streaming
# guard is what must stop it.
ws = fresh("stream")
for i in range(400):
    (ws / f"t{i}.txt").write_bytes(b"x")
tbrail.CHECKPOINT_QUOTA_BYTES = 64 * 1024
peak = {"bytes": 0}
try:
    tbrail.write_checkpoint("probe-stream", 0, ws)
    out["stream"] = {"refused": False}
except tbrail.Reject as exc:
    d = ckpt_dir("probe-stream")
    files = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
    out["stream"] = {"refused": True, "reason": str(exc),
                     "files_left": files,
                     "quota": tbrail.CHECKPOINT_QUOTA_BYTES,
                     "payload_bytes": 400,
                     # v6 moved the streaming bound from a post-member `tell()`
                     # audit to a writer that refuses BEFORE the underlying
                     # write. Same law, strictly earlier; the refusal identity
                     # is what changed, so this names the current one.
                     "streaming_guard": "quota_refused_before_write" in str(exc),
                     "refusal_evidence": getattr(exc, "evidence", None)}

# ---- 3. a symlink-bearing workspace is refused at CREATION
tbrail.CHECKPOINT_QUOTA_BYTES = 2 << 30
ws = fresh("symlinked")
(ws / "real.txt").write_text("real\n")
(ws / "link.txt").symlink_to("real.txt")
(ws / "escape").symlink_to("/etc")          # a link that leaves the workspace
d = ckpt_dir("probe-symlink")
d.mkdir(parents=True, exist_ok=True)
(d / "00.tar").write_bytes(b"PRIOR-RESTORE-POINT")
path, digest, restorable = tbrail.write_checkpoint("probe-symlink", 1, ws)
left = sorted(p.name for p in d.iterdir())
target = fresh("symlink-restored")
tbrail.restore_checkpoint(Path(path), digest, target)
out["symlink"] = {
    "installed": "01.tar" in left,
    "prior_retained_until_caller_retires_it": "00.tar" in left,
    "partials": [n for n in left if n.endswith(".partial")],
    "restorable_at_install": restorable,
    "internal_link_restored": (target / "link.txt").is_symlink(),
    "internal_link_target": os.readlink(target / "link.txt"),
    "escaping_link_restored": (target / "escape").is_symlink(),
    "escaping_link_target": os.readlink(target / "escape"),
    "payload_intact": (target / "real.txt").read_text().strip(),
}
tbrail.retire_superseded_checkpoints("probe-symlink", Path(path))
out["symlink"]["retired_after_commit"] = sorted(p.name for p in d.iterdir())

# ---- 4. hard link and device members are refused at creation too
ws = fresh("hardlinked")
(ws / "a.txt").write_text("a\n")
os.link(ws / "a.txt", ws / "b.txt")
try:
    tbrail.write_checkpoint("probe-hardlink", 0, ws)
    out["hardlink"] = {"refused": False}
except tbrail.Reject as exc:
    out["hardlink"] = {"refused": True, "reason": str(exc)}

# ---- 5. every installed checkpoint round-trips through the restoration law
ws = fresh("roundtrip")
(ws / "home").mkdir()
(ws / "repo").mkdir()
(ws / "repo" / "file.txt").write_text("payload\n")
path, digest, restorable = tbrail.write_checkpoint("probe-roundtrip", 0, ws)
target = fresh("restored")
tbrail.restore_checkpoint(Path(path), digest, target)
out["roundtrip"] = {
    "installed": Path(path).is_file(),
    "restorable_at_install": restorable,
    "restored_payload": (target / "repo" / "file.txt").read_text().strip(),
    "digest": digest,
}

# ---- 6. sanitation reports failure instead of claiming an absent workspace
ws = tbrail.WORK_ROOT / "probe-sanitation"
if ws.exists():
    os.chmod(ws / "locked", 0o700) if (ws / "locked").exists() else None
    import shutil; shutil.rmtree(ws, ignore_errors=True)
(ws / "locked").mkdir(parents=True)
(ws / "locked" / "held.txt").write_text("held\n")
os.chmod(ws / "locked", 0o500)
first = tbrail.sanitize(ws)
os.chmod(ws / "locked", 0o700)
second = tbrail.sanitize(ws)
out["sanitation"] = {"failed_report": first, "after_repair": second}

# the probe must leave no residue: the residency property inspects this root
import shutil as _sh
for name in ("probe-oversize", "probe-stream", "probe-symlink", "probe-hardlink",
             "probe-roundtrip"):
    _sh.rmtree(tbrail.CHECKPOINT_ROOT / name, ignore_errors=True)
_sh.rmtree(lab, ignore_errors=True)
_sh.rmtree(tbrail.WORK_ROOT / "probe-sanitation", ignore_errors=True)
out["residue"] = {
    "checkpoint_dirs": sorted(p.name for p in tbrail.CHECKPOINT_ROOT.iterdir())
                       if tbrail.CHECKPOINT_ROOT.is_dir() else [],
    "lab_removed": not lab.exists(),
}

print(json.dumps(out))
'''


def prop_checkpoint_protocol_v5():
    r = subprocess.run([PY, "-c", CKPT_V5_PROBE], capture_output=True, text=True,
                       timeout=600, env=rail_env({"TBRAIL_DIR": str(HERE)}))
    out = jloads(r.stdout) or {}
    over = out.get("oversize") or {}
    stream = out.get("stream") or {}
    record("CHECKPOINT_PARTIAL_NEVER_EXCEEDS_QUOTA",
           "an oversized workspace is refused before its bytes are taken into "
           "custody, and the quota also binds while the archive streams",
           bool(over.get("refused")) and not over.get("files_left")
           and bool(stream.get("refused")) and not stream.get("files_left")
           and bool(stream.get("streaming_guard")),
           {"oversize": over, "streaming": stream, "stderr": r.stderr[-300:]})

    sym = out.get("symlink") or {}
    hard = out.get("hardlink") or {}
    record("SYMLINK_BEARING_REPOSITORY_CHECKPOINT_LAW_EXPLICIT",
           "a symlink-bearing repository -- including a link that points "
           "outside the workspace -- is captured and restored verbatim, while a "
           "hard link is refused at creation; the prior restore point survives "
           "until the caller retires it",
           sym.get("installed") is True
           and sym.get("prior_retained_until_caller_retires_it") is True
           and not sym.get("partials")
           and sym.get("internal_link_restored") is True
           and sym.get("escaping_link_restored") is True
           and sym.get("escaping_link_target") == "/etc"
           and sym.get("payload_intact") == "real"
           and sym.get("retired_after_commit") == ["01.tar"]
           and bool(hard.get("refused")),
           {"symlink": sym, "hardlink": hard})

    rt = out.get("roundtrip") or {}
    record("EVERY_INSTALLED_CHECKPOINT_IS_IMMEDIATELY_RESTORABLE",
           "an installed checkpoint is validated under the extraction law at "
           "install time and restores its payload byte-for-byte",
           bool(rt.get("installed"))
           and ((rt.get("restorable_at_install") or {}).get("verified") is True)
           and rt.get("restored_payload") == "payload",
           rt)

    san = out.get("sanitation") or {}
    first, after = san.get("failed_report") or {}, san.get("after_repair") or {}
    record("SANITATION_FAILURE_IS_REPORTED_NOT_ASSUMED",
           "a workspace that cannot be removed is reported as surviving, with "
           "the failures, rather than described as absent",
           first.get("absent_after") is False and bool(first.get("errors"))
           and after.get("absent_after") is True,
           {"failed": first, "after_repair": after})


def prop_checkpoint_install_crash():
    """Crash between installing a checkpoint and committing its phase row."""
    src = ENVDIR / "crash-pure.json"
    for point, witness in (("after_checkpoint_install",
                            "CHECKPOINT_INSTALL_AND_PHASE_COMMIT_CRASH_RECOVERS"),
                           ("after_phase_commit",
                            "CHECKPOINT_RETIREMENT_AFTER_COMMIT_CRASH_RECOVERS")):
        slug = point.replace("_", "-")
        txn = f"ckpt-{slug}-001"
        envp = _derive_envelope(src, txn, f"fixture:ckpt-{slug}", repeat_first=3)
        rail("submit", envp)
        r = rail("execute", txn, timeout=600,
                 env_extra={"TBRAIL_CHECKPOINT_CRASH_AT": point})
        crashed = r.returncode in (-9, 137)
        ck = ROOT / "checkpoints" / txn
        tars = sorted(p.name for p in ck.glob("*.tar")) if ck.is_dir() else []
        rows = db().execute(
            "SELECT idx,state,ckpt_path FROM phase WHERE txn_id=? ORDER BY idx",
            (txn,)).fetchall()
        states = {idx: state for idx, state, _c in rows}
        # The property under test is that no COMMITTED PASS row can point at a
        # checkpoint that has already been deleted, and that a crash on either
        # side of the commit still leaves a restore point on disk.
        committed_pass = [(idx, c) for idx, state, c in rows if state == "PASS"]
        every_committed_checkpoint_present = all(
            c and Path(c).is_file() for _idx, c in committed_pass)
        crashed_idx = max(states) if states else None
        expected = "RUNNING" if point == "after_checkpoint_install" else "PASS"
        row_ok = states.get(crashed_idx) == expected
        retained_restore_point = len(tars) >= 1

        out = jloads(rail("execute", txn, timeout=900).stdout)
        final = _txn_row(txn)
        settled = bool(final) and final[0] == "SETTLED" and final[1] == "PASS"
        verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, "no_receipt")
        purged = not ck.exists()
        record(witness,
               f"controller SIGKILLed at '{point}' recovers to a verified "
               f"SETTLED receipt with a restore point intact",
               crashed and row_ok and retained_restore_point
               and every_committed_checkpoint_present
               and settled and verified and purged,
               {"crash_exit": r.returncode, "checkpoints_at_crash": tars,
                "phase_states_at_crash": states,
                "crashed_phase": crashed_idx,
                "committed_pass_rows": committed_pass,
                "every_committed_checkpoint_present":
                    every_committed_checkpoint_present,
                "final_state": final and final[0],
                "receipt_verified": verified, "verify_failures": vfail,
                "checkpoint_dir_removed_after_settlement": purged,
                "terminal": (out or {}).get("terminal")})


def prop_symlink_transaction_disposition():
    """A repository that grows a symlink mid-transaction is held, not settled."""
    txn = "ws-symlink-001"
    envp = _envelope_with_phases(
        ENVDIR / "crash-pure.json", txn, "fixture:ws-symlink",
        [{"name": "make-symlink", "op": "rail.workspace_shape",
          "params": {"shape": "symlink", "target": "tbrail-link.txt"}}])
    rail("submit", envp)
    out = jloads(rail("execute", txn, timeout=600).stdout) or {}
    final = _txn_row(txn)
    phases = out.get("phases") or []
    ckpt = (phases[0].get("checkpoint") or {}) if phases else {}
    restorable = ckpt.get("restorable") or {}
    verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, "no_receipt")
    body = logs_of(txn)
    receipt = _receipt_of(txn) or {}
    law = (receipt.get("checkpoint_custody") or {}).get("symlink_law")
    record("SYMLINK_BEARING_REPOSITORY_TRANSACTION_SETTLES",
           "a phase that leaves a symlink in the repository still produces an "
           "installed, restorable checkpoint and a verified settled receipt, "
           "and the receipt states the symlink law it followed",
           out.get("terminal") == "PASS"
           and "WORKSPACE_SYMLINK_CREATED" in body
           and restorable.get("verified") is True
           and int(restorable.get("symlink_members") or 0) >= 1
           and verified and bool(law),
           {"terminal": out.get("terminal"), "checkpoint": ckpt,
            "receipt_verified": verified, "verify_failures": vfail,
            "symlink_law_stated": bool(law), "txn_state": final and final[0]})


def prop_sanitation_blocks_settlement():
    """Settlement refuses to commit while the workspace survives."""
    txn = "ws-lock-001"
    envp = _envelope_with_phases(
        ENVDIR / "crash-pure.json", txn, "fixture:ws-lock",
        [{"name": "lock-directory", "op": "rail.workspace_shape",
          "params": {"shape": "lock", "target": "tbrail-locked"}}])
    rail("submit", envp)
    out = jloads(rail("execute", txn, timeout=600).stdout) or {}
    row = _txn_row(txn)
    ws = ROOT / "work" / txn
    refused = (out.get("reason") == "SANITATION_FAILED"
               and out.get("terminal") == "HOLD"
               and (row or [None])[0] == "SETTLING"
               and not (row and row[2]))
    journal_kept = (ROOT / "receipts" / txn / "SETTLEMENT.json").is_file()

    # repair the condition the way an operator would, then let recovery finish
    locked = ws / "repo" / "tbrail-locked"
    if locked.is_dir():
        os.chmod(locked, 0o700)
    out2 = jloads(rail("execute", txn, timeout=600).stdout) or {}
    final = _txn_row(txn)
    settled = bool(final) and final[0] == "SETTLED"
    verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, "no_receipt")
    receipt = _receipt_of(txn) or {}
    residue = (receipt.get("residency") or {}).get("workspace_absent")
    record("SANITATION_FAILURE_CANNOT_COMMIT_SETTLED",
           "a workspace that survives sanitation blocks the transition to "
           "SETTLED, keeps the settlement journal, and settles only once the "
           "workspace is actually gone",
           refused and journal_kept and settled and verified and residue is True,
           {"first_pass": {"terminal": out.get("terminal"), "reason": out.get("reason"),
                           "sanitation": out.get("sanitation")},
            "journal_retained": journal_kept,
            "second_pass_terminal": out2.get("terminal"),
            "final_state": final and final[0], "receipt_verified": verified,
            "verify_failures": vfail, "receipt_workspace_absent": residue})


def prop_settled_replay_retries_sanitation():
    """A settled transaction whose workspace reappears is cleaned by replay."""
    txn = "replay-sanitation-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn, "fixture:replay-sanitation")
    rail("submit", envp)
    rail("execute", txn, timeout=600)
    row = _txn_row(txn)
    ws = ROOT / "work" / txn
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "residue.txt").write_text("left behind\n")
    out = jloads(rail("execute", txn, timeout=300).stdout) or {}
    rec_blk = out.get("reconciled") or {}
    record("SETTLED_REPLAY_RETRIES_AND_PROVES_SANITATION",
           "replaying a settled transaction retries sanitation and proves the "
           "workspace is absent rather than assuming it",
           (row or [None])[0] == "SETTLED" and out.get("replay") is True
           and rec_blk.get("workspace_absent") is True and not ws.exists()
           and rec_blk.get("phases_re_executed") == 0,
           {"reconciled": rec_blk, "workspace_exists_after": ws.exists()})


def prop_receipt_adoption_identity():
    """Adoption requires the receipt to BE this settlement's receipt."""
    # 1. a genuine interrupted settlement: the published receipt is adopted
    txn = "adopt-own-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn, "fixture:adopt-own")
    rail("submit", envp)
    rail("execute", txn, timeout=600, env_extra={"TBRAIL_SETTLEMENT_CRASH_AT":
                                                 "after_sidecar_write"})
    rpath = ROOT / "receipts" / txn / "RECEIPT.json"
    before = sha256_of(rpath) if rpath.is_file() else None
    out = jloads(rail("execute", txn, timeout=600).stdout) or {}
    comp = out.get("settlement_completed") or {}
    adoption = comp.get("receipt_adoption") or {}
    after = sha256_of(rpath) if rpath.is_file() else None
    final = _txn_row(txn)
    verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, "no_receipt")
    record("ADOPTED_RECEIPT_MATCHES_SETTLEMENT_JOURNAL",
           "an interrupted settlement adopts its own published receipt only "
           "after proving it matches the journal, and preserves its identity",
           comp.get("receipt_adopted_from_prior_attempt") is True
           and adoption.get("matches_settlement") is True
           and before == after and before is not None and verified,
           {"receipt_sha_before": before, "receipt_sha_after": after,
            "adoption": adoption, "receipt_verified": verified,
            "verify_failures": vfail})

    # 2. a foreign but self-consistent receipt is neither adopted nor destroyed
    txn2 = "adopt-foreign-001"
    envp2 = _derive_envelope(ENVDIR / "crash-pure.json", txn2, "fixture:adopt-foreign")
    rail("submit", envp2)
    rail("execute", txn2, timeout=600, env_extra={"TBRAIL_SETTLEMENT_CRASH_AT":
                                                  "after_settling_journal"})
    d = ROOT / "receipts" / txn2
    foreign = json.loads(rpath.read_text(encoding="utf-8"))   # a REAL receipt,
    foreign["transaction_id"] = "some-other-transaction"      # from elsewhere
    body = json.dumps(foreign, indent=2, sort_keys=True)
    (d / "RECEIPT.json").write_text(body, encoding="utf-8")
    planted = sha256_of(d / "RECEIPT.json")
    (d / "RECEIPT.sha256").write_text(planted + "\n", encoding="utf-8")
    out2 = jloads(rail("execute", txn2, timeout=600).stdout) or {}
    still = sha256_of(d / "RECEIPT.json")
    row2 = _txn_row(txn2)
    record("SELF_CONSISTENT_FOREIGN_RECEIPT_IS_NOT_ADOPTED",
           "a receipt whose sidecar agrees with it but whose contents do not "
           "match the settlement journal is refused, not adopted, and not "
           "overwritten",
           out2.get("reason") == "FOREIGN_RECEIPT_PRESENT"
           and out2.get("terminal") == "HOLD"
           and still == planted and (row2 or [None])[0] == "SETTLING"
           and "transaction_id" in str(out2.get("mismatches")),
           {"reason": out2.get("reason"), "mismatches": out2.get("mismatches"),
            "planted_sha": planted, "receipt_sha_after": still,
            "txn_state": row2 and row2[0]})

    # and once the foreign pair is removed, the transaction settles normally
    (d / "RECEIPT.json").unlink(missing_ok=True)
    (d / "RECEIPT.sha256").unlink(missing_ok=True)
    out3 = jloads(rail("execute", txn2, timeout=600).stdout) or {}
    final2 = _txn_row(txn2)
    v2, f2 = _verify_anchored(final2[2]) if final2 and final2[2] else (False, "no_receipt")
    record("SETTLEMENT_COMPLETES_AFTER_FOREIGN_RECEIPT_IS_REMOVED",
           "the held transaction settles from its journal once the foreign "
           "receipt is out of the way",
           (final2 or [None])[0] == "SETTLED" and v2,
           {"terminal": out3.get("terminal"), "verified": v2, "failures": f2})


def _purge(*args, apply=False, manifest=None):
    argv = ["purge-source"]
    if apply:
        argv.append("--apply")
    if manifest:
        argv += ["--successor-custody", manifest]
    return jloads(rail(*argv, *args, timeout=600).stdout) or {}


def prop_purge_source_custody():
    """purge-source is a custody transition with three refusals."""
    bundle_name = SOURCE_BUNDLE.name
    hot = ROOT / "source" / bundle_name
    digest = sha256_of(hot)

    # 1. an unresolved transaction protects its bundle -- including FENCED_OUT
    con = sqlite3.connect(ROOT / "rail.db", timeout=30)
    fenced = [r[0] for r in con.execute(
        "SELECT txn_id FROM txn WHERE state='FENCED_OUT'")]
    constructed = False
    if not fenced:
        row = con.execute("SELECT txn_id, envelope_json FROM txn WHERE state='SETTLED' "
                          "LIMIT 1").fetchone()
        con.execute("INSERT INTO txn(txn_id,envelope_json,envelope_sha,resource_key,"
                    "state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    ("fenced-out-probe", row[1], "0" * 64, "fixture:fenced-probe",
                     "FENCED_OUT", time.time(), time.time()))
        con.commit()
        fenced = ["fenced-out-probe"]
        constructed = True
    con.close()

    dry = _purge()
    protected_states = " ".join(sum(dry.get("protected_digests", {}).values(), []))
    retained_names = [i["name"] for i in dry.get("retained", [])]
    record("FENCED_OUT_SOURCE_REMAINS_PROTECTED",
           "a FENCED_OUT transaction protects its source bundle from purge, as "
           "does every other unresolved state",
           "FENCED_OUT" in protected_states and bundle_name in retained_names,
           {"protected": dry.get("protected_digests"),
            "retained": retained_names,
            "fenced_out_row_constructed": constructed})

    # The remaining steps need a bundle that NO unresolved transaction
    # references, and this root deliberately ends with several -- held,
    # settling, queued, fenced. So they run in an isolated custody lab: a second
    # real controller root, one real transaction, settled, and then the custody
    # transition exercised end to end against its own retained receipt.
    lab = ROOT / "purge-lab"
    (lab / "source").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "source" / FIXTURE_BUNDLE, lab / "source" / FIXTURE_BUNDLE)

    # The profile a receipt names must live inside the controller root that
    # receipt belongs to: the verifier refuses receipt-supplied paths outside
    # the admitted roots, and it is right to. The lab therefore gets its own
    # byte-identical copy of the qualification profile.
    lab_profile = lab / "RUNNER-PROFILE.qualification.json"
    shutil.copy2(QPROFILE, lab_profile)

    def lab_rail(*args, timeout=600):
        return subprocess.run([PY, str(TBRAIL), *args], capture_output=True,
                              text=True, timeout=timeout,
                              env=rail_env({
                                  "TBRAIL_HOME": str(lab),
                                  "TBRAIL_RUNNER_PROFILE": str(lab_profile),
                                  "TBRAIL_RUNNER_PROFILE_SHA256": QPROFILE_SHA}))

    def lab_purge(apply=False, manifest=None):
        argv = ["purge-source"]
        if apply:
            argv.append("--apply")
        if manifest:
            argv += ["--successor-custody", manifest]
        return jloads(lab_rail(*argv).stdout) or {}

    lab_txn = "purge-lab-001"
    lab_envp = _derive_envelope(Path(fx("nested")), lab_txn, "fixture:purge-lab")
    lab_rail("submit", lab_envp)
    lab_out = jloads(lab_rail("execute", lab_txn).stdout) or {}
    lab_receipt = lab / "receipts" / lab_txn / "RECEIPT.json"
    hot = lab / "source" / FIXTURE_BUNDLE
    digest = sha256_of(hot)
    record("PURGE_LAB_TRANSACTION_SETTLED",
           "the custody lab holds one settled transaction whose retained receipt "
           "needs its source bundle",
           lab_out.get("terminal") == "PASS" and lab_receipt.is_file(),
           {"terminal": lab_out.get("terminal"), "receipt": str(lab_receipt)})

    # 2. a retained receipt protects the bytes even with nothing unresolved
    no_custody = lab_purge(apply=True)
    still_hot = hot.is_file()
    record("PURGE_SOURCE_REQUIRES_VERIFIED_SUCCESSOR_CUSTODY",
           "--apply refuses to remove bytes retained receipts still need until "
           "an independently verified successor holds them",
           still_hot and any(i["sha256"] == digest for i in no_custody.get("retained", []))
           and no_custody.get("no_verification_regressions") is True,
           {"hot_copy_present": still_hot,
            "retained_reason": [i.get("why") for i in no_custody.get("retained", [])],
            "regressions": no_custody.get("verification_regressions")})

    # 3. an UNVERIFIABLE successor claim is refused just as firmly
    bad_dir = lab / "successor-bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    bad_obj = bad_dir / "not-the-bundle.bin"
    bad_obj.write_bytes(b"these are not the bytes\n")
    bad_manifest = lab / "successor-bad.json"
    bad_manifest.write_text(json.dumps({
        "schema": "tier-bench/native-source-custody@1",
        "entries": {digest: {"holder": "unverified-claim",
                             "successor_path": str(bad_obj),
                             "successor_sha256": digest}}}, indent=2), encoding="utf-8")
    bad = lab_purge(apply=True, manifest=str(bad_manifest))
    record("UNVERIFIED_SUCCESSOR_CUSTODY_CLAIM_IS_REFUSED",
           "a successor-custody entry whose object does not rehash to the "
           "digest the receipts name does not release the hot copy",
           hot.is_file()
           and any(i["sha256"] == digest for i in bad.get("retained", []))
           and bad.get("successor_custody_routes", {}).get(digest, {}).get("verified") is False,
           {"route": bad.get("successor_custody_routes", {}).get(digest),
            "hot_copy_present": hot.is_file()})

    # 4. a real custody transfer: the bytes move, every receipt still verifies
    holder = lab / "successor-holder"
    holder.mkdir(parents=True, exist_ok=True)
    successor = holder / FIXTURE_BUNDLE
    shutil.copy2(hot, successor)
    good_manifest = lab / "successor-good.json"
    good_manifest.write_text(json.dumps({
        "schema": "tier-bench/native-source-custody@1",
        "entries": {digest: {"holder": "qualification successor holder",
                             "successor_path": str(successor),
                             "successor_sha256": digest}}}, indent=2), encoding="utf-8")
    good = lab_purge(apply=True, manifest=str(good_manifest))
    gone = not hot.is_file()
    verified_after = good.get("retained_receipts_verified_after") or []
    # the receipts that actually needed these bytes must be among the ones that
    # still verify, through the successor route rather than the hot copy
    purged_items = good.get("purged") or good.get("purgeable") or []
    needed = set(sum([i.get("receipts_requiring_bytes", [])
                      for i in purged_items if i.get("sha256") == digest], []))
    still_ok = {r["receipt"] for r in verified_after if r["ok"]}
    covered = needed and needed.issubset(still_ok)
    record("PURGE_SOURCE_PRESERVES_VERIFIABILITY_OF_ALL_RETAINED_RECEIPTS",
           "after a verified custody transition the hot copy is gone, no receipt "
           "that verified before it fails after it, and the receipts that needed "
           "those bytes verify through the successor route",
           gone and good.get("no_verification_regressions") is True
           and bool(covered)
           and good.get("successor_custody_routes", {}).get(digest, {}).get("verified") is True,
           {"hot_copy_removed": gone,
            "receipts_checked": good.get("receipts_checked"),
            "receipts_needing_these_bytes": len(needed),
            "all_of_them_verify_after": bool(covered),
            "regressions": good.get("verification_regressions"),
            "route": good.get("successor_custody_routes", {}).get(digest)})

    # restore the hot copy so later properties are unaffected
    shutil.copy2(successor, hot)


def prop_interpreter_drift_refused():
    """The controller may not run under an unpinned interpreter."""
    accepted = json.loads(PROFILE.read_text(encoding="utf-8"))
    txn = "interp-drift-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn, "fixture:interp-drift")
    rail("submit", envp)

    drifted = dict(accepted)
    drifted["interpreter"] = dict(accepted.get("interpreter") or {})
    drifted["interpreter"]["sha256"] = "0" * 64
    dp = ROOT / "profile-drifted-interpreter.json"
    dp.write_text(json.dumps(drifted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    r1 = rail("execute", txn, timeout=300, env_extra={
        "TBRAIL_RUNNER_PROFILE": str(dp),
        "TBRAIL_RUNNER_PROFILE_SHA256": sha256_of(dp)})

    stripped = {k: v for k, v in accepted.items() if k != "interpreter"}
    sp = ROOT / "profile-no-interpreter.json"
    sp.write_text(json.dumps(stripped, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    r2 = rail("execute", txn, timeout=300, env_extra={
        "TBRAIL_RUNNER_PROFILE": str(sp),
        "TBRAIL_RUNNER_PROFILE_SHA256": sha256_of(sp)})

    row = _txn_row(txn)
    record("CONTROLLER_INTERPRETER_DRIFT_REFUSED",
           "a profile naming a different interpreter, or naming none at all, "
           "refuses the run before any work happens",
           "CONTROLLER_INTERPRETER_DRIFT" in (r1.stdout + r1.stderr)
           and "CONTROLLER_INTERPRETER_NOT_PINNED" in (r2.stdout + r2.stderr)
           and r1.returncode != 0 and r2.returncode != 0
           and (row or [None])[0] == "QUEUED",
           {"drift_rc": r1.returncode, "drift_out": (r1.stdout + r1.stderr)[-200:],
            "unpinned_rc": r2.returncode,
            "unpinned_out": (r2.stdout + r2.stderr)[-200:],
            "txn_state": row and row[0]})


def prop_pids_kernel_witness():
    """The task ceiling is witnessed by the kernel, not inferred from an errno."""
    txn = "burn-pids-witness-001"
    envp = _derive_envelope(ENVDIR / "burn-pids.json", txn, "fixture:pids-witness")
    rail("submit", envp)
    rail("execute", txn, timeout=900)
    receipt = _receipt_of(txn) or {}
    phases = receipt.get("phases") or []
    agg = {}
    for p in phases:
        agg = ((p.get("enforcement") or {}).get("aggregate") or {})
        if agg.get("pids_kernel_witness"):
            break
    w = agg.get("pids_kernel_witness") or {}
    events = {**(w.get("pids_events") or {}), **(w.get("pids_events_local") or {})}
    fired = max([int(v) for k, v in events.items() if k == "max"] or [0])
    tasks_max = agg.get("tasks_max")
    body = logs_of(txn)
    record("CGROUP_PIDS_MAX_DIRECT_KERNEL_WITNESS",
           "pids.max, pids.current and a non-zero pids.events max are read from "
           "the exact cgroup that refused the fork burst, while it is alive",
           bool(w) and fired >= 1
           and str(w.get("pids_max")) == str(tasks_max)
           and isinstance(w.get("pids_current"), int)
           and "PIDS_BLOCKED_AT" in body,
           {"witness": w, "tasks_max": tasks_max, "events_max": fired,
            "blocked_line": next((l for l in body.splitlines()
                                  if "PIDS_BLOCKED_AT" in l), None)})


def prop_crash_hook_gated():
    """The crash hook may not be reachable outside qualification mode."""
    txn = "hook-gate-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn, "fixture:hook-gate")
    rail("submit", envp)

    # production profile + a valid crash point: refused before execution
    r1 = rail_prod("execute", txn, timeout=300,
                   env_extra={"TBRAIL_SETTLEMENT_CRASH_AT": "after_sanitation"})
    state1 = (_txn_row(txn) or [None])[0]
    # production profile + a stale/garbage value: refused the same way
    r2 = rail_prod("execute", txn, timeout=300,
                   env_extra={"TBRAIL_SETTLEMENT_CRASH_AT": "left-over-from-2026"})
    r3 = rail_prod("execute", txn, timeout=300,
                   env_extra={"TBRAIL_CHECKPOINT_CRASH_AT": "after_phase_commit"})
    state2 = (_txn_row(txn) or [None])[0]
    receipts = list((ROOT / "receipts" / txn).glob("RECEIPT.json"))

    refused = all("CRASH_HOOK_NOT_ADMITTED" in (r.stdout + r.stderr) and r.returncode != 0
                  for r in (r1, r2, r3))
    record("QUALIFICATION_CRASH_HOOK_REFUSED_OUTSIDE_QUALIFICATION_MODE",
           "with a production runner profile the crash hooks refuse the run "
           "before the transaction is touched",
           refused and state1 == "QUEUED" and state2 == "QUEUED" and not receipts,
           {"settlement_hook_rc": r1.returncode,
            "stale_value_rc": r2.returncode, "checkpoint_hook_rc": r3.returncode,
            "detail": (r1.stdout + r1.stderr)[-200:],
            "state_after": state2, "receipts": [str(p) for p in receipts]})

    # an unknown point under qualification mode is refused too, and the
    # transaction still settles normally afterwards
    r4 = rail("execute", txn, timeout=300,
              env_extra={"TBRAIL_SETTLEMENT_CRASH_AT": "after_everything"})
    state3 = (_txn_row(txn) or [None])[0]
    out = jloads(rail("execute", txn, timeout=600).stdout) or {}
    final = _txn_row(txn)
    verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, "no_receipt")
    record("UNKNOWN_OR_STALE_CRASH_HOOK_CANNOT_KILL_PRODUCTION_TRANSACTION",
           "an unknown crash point refuses the run rather than aborting inside "
           "settlement, and the same transaction then settles normally",
           "UNKNOWN_CRASH_POINT" in (r4.stdout + r4.stderr) and r4.returncode != 0
           and state3 == "QUEUED" and (final or [None])[0] == "SETTLED" and verified,
           {"unknown_rc": r4.returncode, "detail": (r4.stdout + r4.stderr)[-200:],
            "state_after_refusal": state3, "final_terminal": out.get("terminal"),
            "receipt_verified": verified, "verify_failures": vfail})


def prop_durability_scope_exact():
    """The durability claim names what is proven and what is only implemented."""
    txn = "durability-scope-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn, "fixture:durability")
    rail("submit", envp)
    rail("execute", txn, timeout=600)
    receipt = _receipt_of(txn) or {}
    dur = ((receipt.get("settlement") or {}).get("durability") or {})
    con = sqlite3.connect(ROOT / "rail.db", timeout=30)
    sync = con.execute("PRAGMA synchronous").fetchone()[0]
    con.close()
    record("SETTLEMENT_DURABILITY_SCOPE_EXACT",
           "the receipt states process-crash recovery as witnessed and "
           "power-loss durability as implemented-but-unwitnessed, and the "
           "ledger is actually running synchronous=FULL",
           "CONTROLLER_PROCESS_CRASH" in str(dur.get("witnessed"))
           and "SUDDEN_POWER_LOSS" in str(dur.get("not_witnessed"))
           and "fsync" in str(dur.get("implemented"))
           and int(sync) == 2,
           {"durability": dur, "pragma_synchronous": sync})


# --------------------------------------------------------------------------
# final checkpoint-integrity delta (exact-head second desk, comment 5272104498)
# --------------------------------------------------------------------------

PEAK_PROBE = r'''
import json, os, resource, shutil, signal, sys
from pathlib import Path
sys.path.insert(0, os.environ["TBRAIL_DIR"])
import tbrail

home = Path(os.environ["TBRAIL_HOME"])
lab = home / "ckpt-peak"
QUOTA = 64 * 1024
out = {}


def fresh(name):
    d = lab / name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    return d


def ckpt_dir(txn):
    return tbrail.CHECKPOINT_ROOT / txn


def parse_streaming_peak(reason):
    """The pre-repair controller reports its post-member `tell()` in the reason.

    That number IS the peak the partial reached before anything refused it, so
    a controller without a bounded writer still yields a comparable peak here
    instead of an unmeasured one.
    """
    marker = "checkpoint_quota_exceeded_while_streaming:"
    if marker in reason:
        try:
            return int(reason.split(marker, 1)[1].split(">", 1)[0])
        except ValueError:
            return None
    return None


def case(name, build, fsize_limit=None):
    ws = fresh(name)
    build(ws)
    txn = "probe-peak-" + name
    shutil.rmtree(ckpt_dir(txn), ignore_errors=True)
    tbrail.CHECKPOINT_QUOTA_BYTES = QUOTA
    rec = {"quota_bytes": QUOTA, "rlimit_fsize": fsize_limit}
    prior = resource.getrlimit(resource.RLIMIT_FSIZE)
    if fsize_limit is not None:
        # Soft limit only: lowering the HARD limit is irreversible for a
        # non-root process, and this probe has to hand the interpreter back.
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_limit, prior[1]))
    try:
        path, digest, install = tbrail.write_checkpoint(txn, 0, ws)
        rec["outcome"] = "INSTALLED"
        rec["install"] = install
        rec["installed_bytes"] = Path(path).stat().st_size
    except tbrail.Reject as exc:
        rec["outcome"] = "REFUSED"
        rec["reason"] = str(exc)[:300]
        rec["refusal_evidence"] = getattr(exc, "evidence", None)
        rec["streaming_peak_from_reason"] = parse_streaming_peak(str(exc))
    except BaseException as exc:                        # noqa: BLE001
        rec["outcome"] = "ERROR"
        rec["error_class"] = exc.__class__.__name__
        rec["errno"] = getattr(exc, "errno", None)
        rec["reason"] = str(exc)[:300]
    finally:
        if fsize_limit is not None:
            resource.setrlimit(resource.RLIMIT_FSIZE, prior)
    d = ckpt_dir(txn)
    files = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
    rec["files_left"] = files
    rec["bytes_left"] = sum((d / f).stat().st_size for f in files)
    rec["partials_left"] = [f for f in files if f.endswith(".partial")]
    shutil.rmtree(d, ignore_errors=True)
    return rec


def metadata_heavy(ws):
    # 400 one-byte files: the payload preflight (400 bytes) passes easily and
    # only per-member headers and padding carry the partial over the ceiling.
    for i in range(400):
        (ws / ("t%03d.txt" % i)).write_bytes(b"x")


def large_next_member(ws):
    # 50 tiny members consume most of the allowance, then one member whose first
    # 16 KiB body block alone would cross what is left. Payload total is 20050
    # bytes, so the preflight passes and only the writer can stop it.
    for i in range(50):
        (ws / ("s%02d.txt" % i)).write_bytes(b"x")
    (ws / "big.bin").write_bytes(b"z" * 20000)


def small(ws):
    (ws / "repo").mkdir()
    (ws / "repo" / "file.txt").write_text("payload\n")


out["metadata_heavy"] = case("metadata-heavy", metadata_heavy)
out["large_next_member"] = case("large-next-member", large_next_member)
# The same metadata-heavy case under a KERNEL ceiling equal to the quota. A
# controller that refuses before the write never reaches it; a controller that
# writes first and audits afterwards is stopped by the kernel with EFBIG, which
# is an artifact that the bytes really did cross the ceiling on disk.
out["kernel_ceiling"] = case("kernel-ceiling", metadata_heavy, fsize_limit=QUOTA)
out["happy_path"] = case("happy-path", small)

shutil.rmtree(lab, ignore_errors=True)
out["residue"] = {
    "checkpoint_dirs": sorted(p.name for p in tbrail.CHECKPOINT_ROOT.iterdir())
                       if tbrail.CHECKPOINT_ROOT.is_dir() else [],
    "lab_removed": not lab.exists(),
}
print(json.dumps(out))
'''


def _peak_case_ok(rec, quota):
    """A refusal that happened AT the boundary, with the boundary measured."""
    if not rec or rec.get("outcome") != "REFUSED":
        return False, "not_refused"
    ev = rec.get("refusal_evidence")
    if not isinstance(ev, dict):
        return False, "no_boundary_artifact"
    on_disk = ev.get("bytes_on_disk_before_refusal")
    measured = ev.get("measured_file_size_at_refusal")
    refused = ev.get("refused_write_bytes")
    if not all(isinstance(v, int) for v in (on_disk, measured, refused)):
        return False, "artifact_incomplete"
    if measured != on_disk:
        return False, f"counter_disagrees_with_filesystem:{on_disk}!={measured}"
    if measured > quota:
        return False, f"peak_exceeded_quota:{measured}>{quota}"
    if on_disk + refused <= quota:
        return False, "refusal_was_not_at_the_boundary"
    if rec.get("files_left"):
        return False, f"residue:{rec['files_left']}"
    return True, f"refused at {measured}/{quota}, next write {refused} bytes"


def prop_checkpoint_partial_peak_bytes():
    """The PEAK size of the partial, not its final size, is what the quota binds."""
    r = subprocess.run([PY, "-c", PEAK_PROBE], capture_output=True, text=True,
                       timeout=600, env=rail_env({"TBRAIL_DIR": str(HERE)}))
    out = jloads(r.stdout) or {}
    quota = 64 * 1024
    verdicts = {}
    for key in ("metadata_heavy", "large_next_member", "kernel_ceiling"):
        ok, why = _peak_case_ok(out.get(key), quota)
        verdicts[key] = {"ok": ok, "why": why}
    happy = out.get("happy_path") or {}
    install = happy.get("install") or {}
    happy_ok = (happy.get("outcome") == "INSTALLED"
                and isinstance(install.get("peak_partial_bytes"), int)
                and install["peak_partial_bytes"] <= quota
                and install["peak_partial_bytes"] == happy.get("installed_bytes")
                and install.get("verified") is True)
    record("CHECKPOINT_PARTIAL_PEAK_BYTES_NEVER_EXCEED_QUOTA",
           "the checkpoint partial is written through a bounded writer that "
           "refuses BEFORE any write that would carry the file past the quota; "
           "peak partial bytes are measured at the refusal from the filesystem, "
           "never exceed the quota, and no partial or checkpoint survives -- "
           "proved for metadata-heavy tiny members, for a large next member "
           "that would cross the remaining allowance in one tar write, and "
           "under a kernel file-size ceiling equal to the quota",
           all(v["ok"] for v in verdicts.values()) and happy_ok
           and not (out.get("residue") or {}).get("checkpoint_dirs"),
           {"quota_bytes": quota, "verdicts": verdicts,
            "cases": {k: out.get(k) for k in
                      ("metadata_heavy", "large_next_member", "kernel_ceiling",
                       "happy_path")},
            "happy_path_ok": happy_ok,
            "residue": out.get("residue"), "stderr": r.stderr[-400:]})


def prop_later_phase_commit_crash_retires_superseded():
    """A crash after a LATER phase row commits, with an older restore point live.

    The v5 checkpoint crash hook fires on the first checkpoint, so no prior
    accepted restore point exists when it kills the controller. This enters the
    state that matters by crashing TWICE at the same admitted boundary: the
    first crash commits phase 0 and leaves its restore point unretired, and the
    second crash -- taken on the recovery run, which skips phase 0 entirely --
    commits phase 1 to a NEW checkpoint and dies before the superseded one is
    retired. Both crashes are real SIGKILLs at an admitted point; no new crash
    site is introduced.
    """
    txn = "ckpt-later-phase-commit-001"
    envp = _derive_envelope(ENVDIR / "crash-pure.json", txn,
                            "fixture:ckpt-later-phase", repeat_first=2)
    rail("submit", envp)
    ck = ROOT / "checkpoints" / txn

    def tars():
        return sorted(p.name for p in ck.glob("*.tar")) if ck.is_dir() else []

    r1 = rail("execute", txn, timeout=600,
              env_extra={"TBRAIL_CHECKPOINT_CRASH_AT": "after_phase_commit"})
    after_first = tars()
    r2 = rail("execute", txn, timeout=600,
              env_extra={"TBRAIL_CHECKPOINT_CRASH_AT": "after_phase_commit"})
    at_crash = tars()
    rows_at_crash = db().execute(
        "SELECT idx,state,attempt,digest,ckpt_path FROM phase WHERE txn_id=? "
        "ORDER BY idx", (txn,)).fetchall()
    by_idx = {r[0]: r for r in rows_at_crash}
    both_crashed = r1.returncode in (-9, 137) and r2.returncode in (-9, 137)
    two_restore_points = at_crash == ["00.tar", "01.tar"]
    db_names_newer = (
        by_idx.get(1) is not None and by_idx[1][1] == "PASS"
        and str(by_idx[1][4] or "").endswith("01.tar")
        and by_idx.get(0) is not None and by_idx[0][1] == "PASS"
        and str(by_idx[0][4] or "").endswith("00.tar"))

    out = jloads(rail("execute", txn, timeout=900).stdout) or {}
    rows_after = {r[0]: r for r in db().execute(
        "SELECT idx,state,attempt,digest,ckpt_path FROM phase WHERE txn_id=? "
        "ORDER BY idx", (txn,)).fetchall()}
    not_re_executed = (
        bool(by_idx) and all(
            rows_after.get(i) is not None
            and rows_after[i][2] == by_idx[i][2]      # attempt unchanged
            and rows_after[i][3] == by_idx[i][3]      # output digest unchanged
            for i in by_idx))

    receipt = _receipt_of(txn) or {}
    norm = ((receipt.get("recovery") or {}).get("checkpoint_normalization") or {})
    cust = receipt.get("checkpoint_custody") or {}
    final = _txn_row(txn)
    settled = bool(final) and final[0] == "SETTLED" and final[1] == "PASS"
    verified, vfail = _verify_anchored(final[2]) if final and final[2] else (False, "no_receipt")
    normalized = (norm.get("normalized") is True
                  and norm.get("observed_at_recovery") == ["00.tar", "01.tar"]
                  and norm.get("checkpoint_named_by_last_committed_pass") == "01.tar"
                  and norm.get("retired_superseded") == ["00.tar"]
                  and norm.get("retained_after") == ["01.tar"])
    one_retained = int(cust.get("retained_count", 99)) == 1
    purged = not ck.exists()

    record("LATER_PHASE_COMMIT_CRASH_RETIRES_SUPERSEDED_CHECKPOINT",
           "an older accepted restore point plus a committed later phase row "
           "naming a newer one: recovery normalizes checkpoint custody to the "
           "checkpoint the last committed PASS row names, retires the "
           "superseded one, re-executes nothing, and settles to an "
           "independently verified receipt holding exactly one restore point",
           both_crashed and after_first == ["00.tar"] and two_restore_points
           and db_names_newer and not_re_executed and normalized
           and one_retained and settled and verified and purged,
           {"crash_exits": [r1.returncode, r2.returncode],
            "checkpoints_after_first_crash": after_first,
            "checkpoints_at_crash": at_crash,
            "phase_rows_at_crash": [list(r) for r in rows_at_crash],
            "phase_rows_after_recovery": [list(rows_after[i]) for i in sorted(rows_after)],
            "no_phase_re_executed": not_re_executed,
            "normalization": norm,
            "receipt_checkpoint_custody": {
                "retained": cust.get("retained"),
                "retained_count": cust.get("retained_count")},
            "terminal": out.get("terminal"),
            "final_state": final and final[0],
            "receipt_verified": verified, "verify_failures": vfail,
            "checkpoint_dir_removed_after_settlement": purged})


DURABILITY_PROBE = r'''
import errno, json, os, shutil, stat, sys
from pathlib import Path
sys.path.insert(0, os.environ["TBRAIL_DIR"])
import tbrail

home = Path(os.environ["TBRAIL_HOME"])
lab = home / "durability-probe"
shutil.rmtree(lab, ignore_errors=True)
lab.mkdir(parents=True)
out = {}

real_fsync_dir = tbrail.fsync_dir
real_fsync = os.fsync


def attempt(fn):
    try:
        return {"outcome": "COMPLETED", "value": str(fn())[:120]}
    except tbrail.Reject as exc:
        return {"outcome": "REFUSED", "reason": str(exc)[:200]}
    except BaseException as exc:                        # noqa: BLE001
        return {"outcome": "ERROR", "error_class": exc.__class__.__name__,
                "reason": str(exc)[:200]}


# ---- 1. a healthy directory publishes normally (the control's control)
good = lab / "good.json"
out["healthy_publication"] = attempt(lambda: tbrail.durable_write(good, b'{"ok":1}'))
out["healthy_publication"]["published"] = good.is_file()

# ---- 2. the required directory entry cannot be fsynced
tbrail.fsync_dir = lambda d: False
target = lab / "record.json"
out["record"] = attempt(lambda: tbrail.durable_write(target, b'{"record":1}'))
out["record"]["published"] = target.is_file()
out["record"]["residue"] = sorted(p.name for p in lab.iterdir())

ws = lab / "ws"
ws.mkdir()
(ws / "file.txt").write_text("payload\n")
txn = "probe-durability"
shutil.rmtree(tbrail.CHECKPOINT_ROOT / txn, ignore_errors=True)
out["checkpoint"] = attempt(lambda: tbrail.write_checkpoint(txn, 0, ws))
d = tbrail.CHECKPOINT_ROOT / txn
out["checkpoint"]["files_left"] = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
tbrail.fsync_dir = real_fsync_dir

# ---- 3. the file's own fsync fails (directories still sync, so the refusal
#         must name the FILE and not be masked by the directory check)
def picky(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        return real_fsync(fd)
    raise OSError(errno.EIO, "injected file fsync failure")

os.fsync = picky
ftarget = lab / "file-sync.json"
out["file_sync"] = attempt(lambda: tbrail.durable_write(ftarget, b'{"f":1}'))
os.fsync = real_fsync
out["file_sync"]["published"] = ftarget.is_file()

shutil.rmtree(d, ignore_errors=True)
shutil.rmtree(lab, ignore_errors=True)
out["residue"] = {
    "checkpoint_dirs": sorted(p.name for p in tbrail.CHECKPOINT_ROOT.iterdir())
                       if tbrail.CHECKPOINT_ROOT.is_dir() else [],
    "lab_removed": not lab.exists(),
}
print(json.dumps(out))
'''

REQUIRED_DURABLE_SITES = {
    "settlement_journal": "return durable_write(settlement_journal_path(receipt_dir)",
    "receipt": "digest = durable_write(",
    "receipt_sidecar": "durable_write(spath, (digest",
    "source_custody_manifest": "durable_write(SOURCE_CUSTODY_PATH,",
    "checkpoint_publication": 'require_dir_durable(path.parent, "checkpoint_publication:"',
}


def prop_directory_fsync_failure_refuses():
    """A durable transition is REFUSED when its directory entry cannot be synced."""
    r = subprocess.run([PY, "-c", DURABILITY_PROBE], capture_output=True, text=True,
                       timeout=600, env=rail_env({"TBRAIL_DIR": str(HERE)}))
    out = jloads(r.stdout) or {}
    healthy = out.get("healthy_publication") or {}
    rec = out.get("record") or {}
    ckpt = out.get("checkpoint") or {}
    fsy = out.get("file_sync") or {}
    healthy_ok = healthy.get("outcome") == "COMPLETED" and healthy.get("published") is True
    record_ok = (rec.get("outcome") == "REFUSED"
                 and "directory_durability_unavailable" in str(rec.get("reason"))
                 and rec.get("published") is False
                 and not [n for n in (rec.get("residue") or []) if n.endswith(".partial")])
    ckpt_ok = (ckpt.get("outcome") == "REFUSED"
               and "directory_durability_unavailable" in str(ckpt.get("reason"))
               and not ckpt.get("files_left"))
    file_ok = (fsy.get("outcome") == "REFUSED"
               and "file_durability_unavailable" in str(fsy.get("reason"))
               and fsy.get("published") is False)
    src = TBRAIL.read_text(encoding="utf-8", errors="replace")
    sites = {k: (v in src) for k, v in REQUIRED_DURABLE_SITES.items()}
    record("DIRECTORY_FSYNC_FAILURE_REFUSES_DURABLE_TRANSITION",
           "every required durability operation fails CLOSED: a record whose "
           "parent directory entry cannot be fsynced, and a record whose own "
           "body cannot be fsynced, are both REFUSED rather than reported as "
           "durably published -- for controller records and for checkpoint "
           "publication alike -- while a healthy directory still publishes",
           healthy_ok and record_ok and ckpt_ok and file_ok and all(sites.values()),
           {"healthy_publication": healthy, "record": rec, "checkpoint": ckpt,
            "file_sync": fsy, "required_publication_sites": sites,
            "residue": out.get("residue"), "stderr": r.stderr[-400:]})


PRIVATE_MARKERS_NOTE = (
    "the public product tree may not carry the deployment's host name, account "
    "home or absolute controller paths"
)


def prop_public_artifacts_have_no_private_coordinates():
    """The committed product tree carries no deployment coordinates."""
    host = os.uname().nodename
    home = str(Path.home())
    markers = {"host": host, "home": home, "rail_home": str(Path.home() / ".tbrail")}
    hits = {}
    # The deployment's own accepted profile is private BY DESIGN and is not part
    # of the public product; everything else that ships must be clean.
    private_by_design = {f"RUNNER-PROFILE.{host}.json"}
    scanned = 0
    for p in sorted(HERE.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(HERE)).replace("\\", "/")
        if p.name in private_by_design or "__pycache__" in rel:
            continue
        try:
            body = p.read_text(errors="replace")
        except OSError:
            continue
        scanned += 1
        for label, marker in markers.items():
            if marker and marker in body:
                hits.setdefault(label, []).append(rel)
    record("PUBLIC_PRODUCT_ARTIFACTS_CONTAIN_NO_PRIVATE_DEPLOYMENT_COORDINATES",
           PRIVATE_MARKERS_NOTE,
           not hits and scanned > 0,
           {"files_scanned": scanned, "hits": hits,
            "private_by_design_excluded": sorted(private_by_design),
            "markers_checked": sorted(markers)})


DELTA_CONTROLS = (
    prop_checkpoint_partial_peak_bytes,
    prop_later_phase_commit_crash_retires_superseded,
    prop_directory_fsync_failure_refuses,
)


def main_delta():
    """The focused cold delta: only the three final checkpoint-integrity controls.

    Same cold-root precondition, same externally anchored profiles, same
    fixture. It exists so the three controls can be run against the PRE-repair
    controller as well, which is the only way a control proves anything: one
    that passes before the repair is not evidence.
    """
    assert_cold()
    build_fixture()
    for control in DELTA_CONTROLS:
        try:
            control()
        except BaseException as exc:                    # noqa: BLE001
            record(control.__name__.upper(), "control raised", False,
                   {"error_class": exc.__class__.__name__, "error": str(exc)[:400]})
    failed = [r for r in results if not r["pass"]]
    summary = {
        "schema": "tier-bench/native-rail-cold-delta@1",
        "controller_root": str(ROOT),
        "controller": {"path": str(TBRAIL), "sha256": sha256_of(TBRAIL)},
        "host": os.uname().nodename,
        "accepted_runner_profile_sha256": ACCEPTED_PROFILE_SHA,
        "qualification_runner_profile_sha256": QPROFILE_SHA,
        "controls": [c.__name__ for c in DELTA_CONTROLS],
        "verdict": "PASS_CHECKPOINT_INTEGRITY_DELTA" if not failed
                   else "FAIL_CHECKPOINT_INTEGRITY_DELTA",
        "total": len(results), "failed": len(failed),
        "failed_properties": [r["property"] for r in failed],
        "results": results,
    }
    (ROOT / "COLD-DELTA.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print("\n" + summary["verdict"])
    print(f"{len(results) - len(failed)}/{len(results)} properties passed")
    raise SystemExit(0 if not failed else 1)


def main():
    if os.environ.get("TBRAIL_QUALIFY_MODE") == "delta":
        return main_delta()
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
    # ---- final product-admission controls ---------------------------------
    prop_worker_environment_closed()
    prop_checkpoint_protocol_v5()
    prop_checkpoint_install_crash()
    prop_symlink_transaction_disposition()
    prop_sanitation_blocks_settlement()
    prop_settled_replay_retries_sanitation()
    prop_receipt_adoption_identity()
    prop_interpreter_drift_refused()
    prop_pids_kernel_witness()
    prop_crash_hook_gated()
    prop_durability_scope_exact()
    # ---- final checkpoint-integrity delta ---------------------------------
    for control in DELTA_CONTROLS:
        control()
    prop_public_artifacts_have_no_private_coordinates()
    prop_purge_source_custody()
    # residency runs last: it asserts the root is clean after everything above
    prop_j_residency()

    failed = [r for r in results if not r["pass"]]
    summary = {
        "schema": "tier-bench/native-rail-cold-qualification@6",
        "controller_root": str(ROOT),
        "host": os.uname().nodename,
        "accepted_runner_profile_sha256": ACCEPTED_PROFILE_SHA,
        "qualification_runner_profile_sha256": QPROFILE_SHA,
        "controller_interpreter": {
            "path": str(Path(os.path.realpath(sys.executable))),
            "version": "%d.%d.%d" % sys.version_info[:3],
        },
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
