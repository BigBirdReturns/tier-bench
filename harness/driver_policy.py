"""
Capture the driver's DECISION TREE — not its outputs — and freeze it as an
immutable snapshot, so the orchestration survives the driver's disappearance.

`distill.py` captures what the driver ANSWERED (repair examples). This captures
how it DECIDED: for a task of a given signature, how it decomposed the work,
what it chose to verify, and when it escalated. That decision procedure is a
POLICY — it generalizes to task classes it has seen, not just exact tasks — and
it is the part that does NOT yield to brute force (disposition is flat on effort;
see data/control-results). Freeze the policy while the frontier driver is
reachable, and a cheaper model can execute UNDER it: the cheap model is the
hands, the snapshot is the frozen brain. When Fable disappears, its judgment
about HOW to attack a task class stays.

Three moves:
  capture — log one DecisionRecord per driven task -> driver_decisions.jsonl
  freeze  — aggregate the log into an immutable, versioned snapshot
            (driver/policy/vN/policy.json). Never edited in place; a change is a
            new vN — the same law the identity releases follow.
  resolve — given a new task's signature, return the frozen plan the driver
            would have used, for a cheaper model to follow. No match => None:
            no snapshot, no guess.

Run `python harness/driver_policy.py --selftest` to see the loop close offline.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DECISIONS_DEFAULT = REPO / "driver_decisions.jsonl"
POLICY_DIR = REPO / "driver" / "policy"


def _canon(v):
    """Canonicalize a signature value: sort dict keys AND list contents. A task
    signature's lists (e.g. the set of validators a task requires) are SETS —
    order must not matter — so ['compile','tests'] and ['tests','compile'] key
    to the same class. (Plans, where order matters, are keyed separately as
    tuples, not through here.)"""
    if isinstance(v, dict):
        return {k: _canon(v[k]) for k in v}
    if isinstance(v, list):
        return sorted((_canon(x) for x in v), key=lambda z: json.dumps(z, sort_keys=True))
    return v


def signature_key(sig: dict) -> str:
    """Canonical, order-independent key for a task signature — so the SAME class
    of task always resolves to the same policy entry regardless of dict/list order."""
    return json.dumps(_canon(sig), sort_keys=True, separators=(",", ":"))


@dataclass
class DecisionRecord:
    """One branch-point trace: the JUDGMENT the driver made on a task, not the
    answer it produced. signature says what CLASS of task this is; plan is how it
    decomposed the work; verify is what it chose to check; escalate_when is the
    condition under which it took the work back from the hands."""
    signature: dict
    plan: list
    verify: list
    escalate_when: str
    driver_model: str
    passed: bool
    task_id: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def capture(record: DecisionRecord, path=DECISIONS_DEFAULT) -> None:
    """Append one decision. Call this from the driver loop on every driven task —
    the corpus is the raw material the freeze step distills into a policy."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(record.to_json() + "\n")


def _load_decisions(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_policy(decisions: list) -> dict:
    """Aggregate decisions into a policy: signature -> the plan that WORKED.
    Only passed decisions become policy — a plan that failed isn't judgment worth
    replaying — and `support` counts the passing runs behind each entry, so a
    one-off never looks as trustworthy as a pattern the driver repeated."""
    by_sig: dict = {}
    for d in decisions:
        if not d.get("passed"):
            continue
        k = signature_key(d["signature"])
        e = by_sig.setdefault(k, {"signature": d["signature"], "plans": {},
                                  "verify": d.get("verify", []),
                                  "escalate_when": d.get("escalate_when", ""),
                                  "drivers": set(), "support": 0})
        pk = tuple(d.get("plan", []))
        e["plans"][pk] = e["plans"].get(pk, 0) + 1
        if d.get("driver_model"):
            e["drivers"].add(d["driver_model"])
        e["support"] += 1

    policy = {}
    for k, e in by_sig.items():
        best_plan = max(e["plans"].items(), key=lambda x: x[1])[0]  # the plan it used most
        policy[k] = {
            "signature": e["signature"],
            "plan": list(best_plan),
            "verify": e["verify"],
            "escalate_when": e["escalate_when"],
            "support": e["support"],
            "from_drivers": sorted(e["drivers"]),
        }
    return policy


def freeze(version: str, decisions_path=DECISIONS_DEFAULT, policy_dir=POLICY_DIR) -> Path:
    """Write an IMMUTABLE snapshot driver/policy/<version>/. Refuses to overwrite
    an existing version — frozen snapshots are never edited in place; a change is
    a new version. Same provenance law as identity/scg/releases/."""
    dest = Path(policy_dir) / version
    if dest.exists():
        raise FileExistsError(f"{dest} exists — frozen snapshots are immutable; use a new version")
    decisions = _load_decisions(decisions_path)
    policy = build_policy(decisions)
    dest.mkdir(parents=True)
    body = json.dumps(policy, indent=1, ensure_ascii=False, sort_keys=True)
    (dest / "policy.json").write_text(body, encoding="utf-8")
    manifest = {
        "version": version,
        "entries": len(policy),
        "source_decisions": len(decisions),
        "passed_decisions": sum(1 for d in decisions if d.get("passed")),
        "drivers": sorted({d.get("driver_model", "") for d in decisions if d.get("driver_model")}),
        "policy_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "law": "immutable — never edit in place; a change is a new version",
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return dest


class FrozenPolicy:
    """Load a frozen snapshot and resolve a task's plan from it — the driver's
    judgment, replayed without the driver in the room."""

    def __init__(self, version: str, policy_dir=POLICY_DIR):
        self.version = version
        self.policy = json.loads((Path(policy_dir) / version / "policy.json").read_text(encoding="utf-8"))

    def resolve(self, signature: dict):
        """Exact-match a task class to its frozen plan; None if the policy has
        never seen this class. Honest by construction: no entry, no guess — the
        caller falls back to a live driver (if any) rather than fabricating one."""
        return self.policy.get(signature_key(signature))

    def classes(self):
        return [v["signature"] for v in self.policy.values()]


def capture_composite_decision(task, comp, passed, path=DECISIONS_DEFAULT) -> None:
    """One-line, defensive capture hook for a driver_repair composite run — the
    real capture point during a benchmark. Coarse but honest: the task tier is
    the class, and the driver/hands split is the plan. Enrich the signature later
    (add the validator set, file kinds) to make the policy discriminate finer."""
    hands = comp.members[0] if getattr(comp, "members", None) else "?"
    driver = getattr(comp, "driver", None) or hands
    capture(DecisionRecord(
        signature={"tier": getattr(task, "tier", "?"), "strategy": getattr(comp, "strategy", "?")},
        plan=[f"draft with hands ({hands})", "verify against the task's validators",
              f"on failure, repair with driver ({driver})"],
        verify=["task validators"],
        escalate_when="hands attempt fails validation",
        driver_model=driver,
        passed=bool(passed),
        task_id=getattr(task, "task_id", ""),
    ), path)


def _selftest():
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    dec = tmp / "driver_decisions.jsonl"
    pol = tmp / "policy"
    fable = "claude-fable-5"

    # 1. simulate capturing the driver's DECISIONS across a few task classes
    recs = [
        DecisionRecord({"tier": "T2", "validators": ["compile", "tests"]},
                       ["read target", "draft patch (hands)", "run tests", "repair from failing test (driver)"],
                       ["compile", "tests"], "any validator fails", fable, True, "t2_fix_div"),
        DecisionRecord({"tier": "T2", "validators": ["compile", "tests"]},
                       ["read target", "draft patch (hands)", "run tests", "repair from failing test (driver)"],
                       ["compile", "tests"], "any validator fails", fable, True, "t2_multi_patch"),
        DecisionRecord({"tier": "T3", "validators": ["compile", "tests", "ast"]},
                       ["map call sites", "plan refactor", "draft (hands)", "run tests + AST check", "repair (driver)"],
                       ["compile", "tests", "ast"], "any validator fails", fable, True, "t3_refactor"),
        # a FAILED cheap run — must NOT become policy
        DecisionRecord({"tier": "T2", "validators": ["compile", "tests"]},
                       ["one-shot patch (hands)"], ["compile", "tests"], "n/a", "claude-haiku-4-5", False, "t2_haiku"),
    ]
    for r in recs:
        capture(r, dec)

    # 2. freeze the corpus into an immutable snapshot
    dest = freeze("v-selftest", dec, pol)

    # 3. a cheaper model resolves a NEW T2 task's plan straight from the snapshot
    fp = FrozenPolicy("v-selftest", pol)
    plan = fp.resolve({"tier": "T2", "validators": ["tests", "compile"]})  # order-independent match

    assert plan and plan["plan"][0] == "read target", plan
    assert plan["support"] == 2 and plan["from_drivers"] == [fable]      # only the driver's PASSED runs
    assert fp.resolve({"tier": "T5", "validators": ["human"]}) is None    # unknown class -> honest None
    try:
        freeze("v-selftest", dec, pol)
        raise AssertionError("freeze should refuse to overwrite a frozen version")
    except FileExistsError:
        pass

    print("PASS  capture -> freeze -> resolve")
    print(f"  captured {len(recs)} decisions ({sum(r.passed for r in recs)} passed, 1 failed cheap run dropped)")
    print(f"  froze {dest.name}: {len(fp.policy)} policy entries (only plans that worked)")
    print("  a cheaper model resolving a T2 task gets the driver's frozen plan:")
    for i, step in enumerate(plan["plan"], 1):
        print(f"    {i}. {step}")
    print(f"  support={plan['support']}  from={plan['from_drivers']} — the driver's judgment, replayed without the driver")
    print("  an unseen task class -> None (no snapshot, no guess)")
    print("  re-freezing the same version -> refused (snapshots are immutable)")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: python harness/driver_policy.py --selftest")
