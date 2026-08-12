#!/usr/bin/env python3
"""Cold qualification for the v2 native rail.

Runs from a FRESH controller root supplied on the command line. It never reads
or writes the operational ~/.tbrail, and it refuses to start if the root it is
given already holds a database, lease, workspace or receipt.

Covers the original A-F properties plus every property the second-desk review
required before product admission.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TBRAIL = HERE / "tbrail.py"
ENVDIR = HERE / "envelopes-v2"

ROOT = Path(sys.argv[1]).resolve()
SOURCE_BUNDLE = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
PY = sys.executable

results: list[dict] = []


def record(prop, name, ok, detail=None):
    results.append({"property": prop, "name": name,
                    "pass": bool(ok), "detail": detail})
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {prop} :: {name}")
    if not ok:
        print(f"        detail: {json.dumps(detail, default=str)[:400]}")


def rail(*args, timeout=600, env_extra=None):
    e = dict(os.environ)
    e["TBRAIL_HOME"] = str(ROOT)
    if env_extra:
        e.update(env_extra)
    return subprocess.run([PY, str(TBRAIL), *args], capture_output=True,
                          text=True, timeout=timeout, env=e)


def db():
    return sqlite3.connect(ROOT / "rail.db", timeout=30)


def jloads(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------
# cold-root precondition
# --------------------------------------------------------------------------
def assert_cold():
    if ROOT.exists():
        stale = [p.name for p in ROOT.iterdir()
                 if p.name in ("rail.db", "work", "receipts")]
        if stale:
            print(f"REFUSING: {ROOT} is not cold; found {stale}")
            raise SystemExit(2)
    (ROOT / "source").mkdir(parents=True, exist_ok=True)
    if SOURCE_BUNDLE:
        shutil.copy2(SOURCE_BUNDLE, ROOT / "source" / SOURCE_BUNDLE.name)
    record("COLD_ROOT", "fresh controller root with no prior db/leases/work/receipts",
           True, {"root": str(ROOT)})


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
# B. credential isolation, now structural
# --------------------------------------------------------------------------
def prop_b():
    rail("submit", str(ENVDIR / "isolation.json"))
    out = jloads(rail("execute", "estate-isolation-001").stdout)
    ok = out and out["terminal"] == "PASS"
    log = ""
    lp = ROOT / "receipts" / "estate-isolation-001" / "logs"
    if lp.is_dir():
        for f in lp.iterdir():
            log += f.read_text(errors="replace")
    record("B_CREDENTIAL_ISOLATION", "worker sees no credential, no home, no network",
           ok and "CREDENTIAL_ISOLATION_HOLDS" in log,
           {"terminal": out and out.get("terminal"), "log": log[-300:]})
    record("B_STRUCTURAL", "controller home is not mounted into the worker",
           "controller_home_mounted= False" in log, {"log_tail": log[-200:]})


# --------------------------------------------------------------------------
# C. replay, real crash recovery, effectful refusal
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


def prop_c_real_crash():
    """Kill the controller MID-PHASE, then prove recovery does not re-run
    already-completed phases."""
    rail("submit", str(ENVDIR / "crash-pure.json"))
    e = dict(os.environ)
    e["TBRAIL_HOME"] = str(ROOT)
    proc = subprocess.Popen([PY, str(TBRAIL), "execute", "estate-crash-pure-001"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=e)
    # wait until phase 0 has PASSed and phase 1 (the long hold) is RUNNING
    deadline = time.time() + 180
    killed = False
    while time.time() < deadline:
        try:
            rows = dict((r[0], r[1]) for r in db().execute(
                "SELECT idx,state FROM phase WHERE txn_id=?",
                ("estate-crash-pure-001",)))
        except sqlite3.Error:
            rows = {}
        if rows.get(0) == "PASS" and rows.get(1) == "RUNNING":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            killed = True
            break
        time.sleep(0.3)
    proc.wait(timeout=30)
    record("C3_CRASH_INJECTED", "controller killed mid-phase (SIGKILL to its group)",
           killed, {"killed": killed})
    if not killed:
        return

    pre = db().execute(
        "SELECT idx,state,attempt,digest FROM phase WHERE txn_id=? ORDER BY idx",
        ("estate-crash-pure-001",)).fetchall()
    phase0_digest_before = dict((r[0], r[3]) for r in pre).get(0)

    out = jloads(rail("execute", "estate-crash-pure-001", timeout=900).stdout)
    post = db().execute(
        "SELECT idx,state,attempt,digest FROM phase WHERE txn_id=? ORDER BY idx",
        ("estate-crash-pure-001",)).fetchall()
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


def prop_c_effectful_refusal():
    """An interrupted EFFECTFUL phase must not be silently re-run."""
    rail("submit", str(ENVDIR / "crash-effectful.json"))
    txn = "estate-crash-effectful-001"
    # simulate the crash directly: phase 0 PASS, phase 1 left RUNNING
    con = db()
    con.execute("INSERT OR REPLACE INTO phase(txn_id,idx,name,op,state,attempt,"
                "exit_code,digest,log_path,started_at,ended_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (txn, 0, "compile-candidate", "python.py_compile", "PASS", 1, 0,
                 "0" * 64, str(ROOT / "receipts" / txn / "logs" / "00-x.log"),
                 time.time(), time.time()))
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
# D. leases: collision, fencing, pid reuse
# --------------------------------------------------------------------------
def prop_d_collision():
    rail("submit", str(ENVDIR / "collision-holder.json"))
    rail("submit", str(ENVDIR / "collision-contender.json"))
    e = dict(os.environ)
    e["TBRAIL_HOME"] = str(ROOT)
    holder = subprocess.Popen([PY, str(TBRAIL), "execute", "estate-collision-holder-001"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              start_new_session=True, text=True, env=e)
    time.sleep(12)
    rows = db().execute("SELECT resource_key,txn_id,fence FROM lease").fetchall()
    out = jloads(rail("execute", "estate-collision-contender-001").stdout)
    refused = out and out.get("reason") == "COLLISION_HELD"
    record("D1_COLLISION_HELD", "contender refused while holder leases the resource",
           refused and bool(rows), {"leases": rows, "reason": out and out.get("reason")})
    holder.wait(timeout=120)


def prop_d_pid_reuse():
    """A stale lease whose PID was reused must still be reclaimed."""
    con = db()
    con.execute("DELETE FROM lease")
    # our own live pid, but a wrong start-tick value => PID reuse signature
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

    # a genuinely live holder must NOT be reclaimable
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

    # fencing: the old holder must refuse to settle after losing its lease
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
    # independent descendant proof: nothing from that phase is still alive
    leftover = subprocess.run(
        ["pgrep", "-af", "spawn_descendant.py"], capture_output=True, text=True)
    record("E2_NO_LIVE_DESCENDANTS", "no descendant of the torn-down phase survives",
           leftover.returncode != 0, {"pgrep": leftover.stdout.strip()[:200]})


# --------------------------------------------------------------------------
# F. receipt reconstruction and tamper refusal
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

    def tamper(path: Path, mutate, restore_from=None):
        original = path.read_bytes()
        try:
            mutate(path)
            out = jloads(rail("verify", str(rpath), "--anchor", anchor).stdout)
            return out
        finally:
            path.write_bytes(original)

    # log tamper
    logs = sorted((rdir / "logs").iterdir())
    out = tamper(logs[0], lambda p: p.write_bytes(p.read_bytes() + b" "))
    record("F3_LOG_TAMPER_REFUSED", "modified phase log is refused",
           out and out["verdict"] == "REFUSED"
           and "phase_logs_rehash" in out["failures"],
           {"failures": out and out.get("failures")})

    # envelope tamper
    out = tamper(rdir / "ENVELOPE.json", lambda p: p.write_bytes(p.read_bytes() + b" "))
    record("F4_ENVELOPE_TAMPER_REFUSED", "modified envelope is refused",
           out and out["verdict"] == "REFUSED"
           and "envelope_recomputes" in out["failures"],
           {"failures": out and out.get("failures")})

    # receipt + sidecar forged together: local pair is consistent, anchor refuses
    original_r = rpath.read_bytes()
    original_s = (rdir / "RECEIPT.sha256").read_bytes()
    try:
        data = json.loads(original_r)
        data["terminal"] = "PASS"
        data["provider_calls"] = 99
        rpath.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        import hashlib
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

    # source tamper
    src = next((ROOT / "source").iterdir())
    out = tamper(src, lambda p: p.write_bytes(p.read_bytes() + b" "))
    record("F6_SOURCE_TAMPER_REFUSED", "modified source bundle is refused",
           out and out["verdict"] == "REFUSED"
           and "source_bundle_rehashes" in out["failures"],
           {"failures": out and out.get("failures")})


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


def prop_h_exec_negatives():
    cases = [
        ("exec-neg-script-digest", "neg-script-digest", "script_digest_mismatch"),
        ("exec-neg-arg-grammar", "neg-arg-grammar", "bad_param:args[]"),
        ("exec-neg-undeclared-switch", "neg-undeclared-switch", "undeclared_switch"),
        ("exec-neg-allowed-path", "neg-allowed-path", "dot_segment"),
        ("exec-neg-outside-allowed", "neg-outside-allowed", "path_not_in_allowed_paths"),
    ]
    bad = []
    for envf, txn, expect in cases:
        rail("submit", str(ENVDIR / f"{envf}.json"))
        out = jloads(rail("execute", txn).stdout)
        note = ""
        if out:
            for p in out.get("phases", []):
                note += str(p.get("note", ""))
        if not (out and out.get("terminal") == "HOLD" and expect in note):
            bad.append({"case": envf, "expected": expect,
                        "terminal": out and out.get("terminal"), "note": note[:160]})
    record("H_OPERATION_NEGATIVES",
           "digest drift, undeclared switch, traversal and allowed-path violations refused",
           not bad, {"unrefused": bad})


# --------------------------------------------------------------------------
# I. runtime equivalence
# --------------------------------------------------------------------------
def prop_i_equivalence(first):
    rail("submit", str(ENVDIR / "canary-py314.json"))
    other = jloads(rail("execute", "estate-canary-py314-001", timeout=900).stdout)
    same = (first and other
            and first["terminal"] == other["terminal"] == "PASS"
            and [p["name"] for p in first["phases"]] == [p["name"] for p in other["phases"]]
            and [p["state"] for p in first["phases"]] == [p["state"] for p in other["phases"]])
    record("I_RUNTIME_EQUIVALENCE",
           "3.11 datum and 3.14 matrix point agree phase-for-phase", same,
           {"py311": first and first.get("runtime", {}).get("version"),
            "py314": other and other.get("runtime", {}).get("version"),
            "py311_terminal": first and first.get("terminal"),
            "py314_terminal": other and other.get("terminal")})


# --------------------------------------------------------------------------
# J. residency vs retained custody
# --------------------------------------------------------------------------
def prop_j_residency():
    out = jloads(rail("residency").stdout)
    zero_exec = out and out["leases_held"] == 0 and out["workspaces_present"] == []
    retained = out and out["retained_source_custody"]["total_bytes"] > 0
    record("J1_ZERO_TRANSACTION_EXECUTION_RESIDUE",
           "no leases, no workspaces after all transactions", zero_exec,
           {"leases": out and out["leases_held"],
            "workspaces": out and out["workspaces_present"]})
    record("J2_RETAINED_CUSTODY_DECLARED",
           "retained source custody reported separately with digest, bytes and purge law",
           retained and bool(out["retained_source_custody"].get("purge_law")),
           {"total_bytes": out and out["retained_source_custody"]["total_bytes"],
            "items": out and [i["name"] for i in out["retained_source_custody"]["items"]]})


def main():
    assert_cold()
    prop_g_negatives()
    first = prop_c_settled_replay()
    prop_a()
    prop_b()
    prop_h_exec_negatives()
    prop_c_real_crash()
    prop_c_effectful_refusal()
    prop_d_collision()
    prop_d_pid_reuse()
    prop_e_teardown()
    prop_f_receipt()
    prop_i_equivalence(first)
    prop_j_residency()

    failed = [r for r in results if not r["pass"]]
    summary = {
        "schema": "tier-bench/native-rail-cold-qualification@1",
        "controller_root": str(ROOT),
        "host": os.uname().nodename,
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
