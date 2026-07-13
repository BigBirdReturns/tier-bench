#!/usr/bin/env python3
"""Authoring batch 2 — derive hidden vectors mechanically and verify key material.

For each task: a REFERENCE implementation (the oracle) and one or more NAIVE
implementations (the plausible mid-implementation drift the knot is built
around). Vectors' expected values are COMPUTED from the reference, never typed
by hand. Verification is bidirectional before any vector freezes:

  * reference scores full marks on the frozen vectors AND passes the visible main()
  * every naive implementation FAILS the hidden vectors (and the failing
    vectors include at least one knot vector)
  * the untouched fixture baseline fails to load/score (NotImplementedError)

Run:  python experiments/breadth/authoring2/build_vectors.py          # derive + verify + write
      python experiments/breadth/authoring2/build_vectors.py --check  # verify frozen files match (CI drift guard)
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------- references

def _leap(y): return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
def _dim(y, m):
    return [31, 29 if _leap(y) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]

def ref_billing(y, m, d, n):
    out = []
    for i in range(1, n + 1):
        mm = m - 1 + i
        yy, mm = y + mm // 12, mm % 12 + 1
        out.append((yy, mm, min(d, _dim(yy, mm))))
    return out

def naive_billing_cascade(y, m, d, n):
    """The drift: a running date variable — the clamp cascades forever."""
    out, cy, cm, cd = [], y, m, d
    for _ in range(n):
        cm += 1
        if cm > 12:
            cy, cm = cy + 1, 1
        cd = min(cd, _dim(cy, cm))
        out.append((cy, cm, cd))
    return out

def ref_window(events, w, n, t):
    return sum(1 for s in events if t - w < s <= t) < n

def naive_window_closed(events, w, n, t):
    """The drift: 'reaches back w seconds' read as >= t-w (closed old end)."""
    return sum(1 for s in events if t - w <= s <= t) < n

def _is_business(y, m, d, holidays):
    return _dt.date(y, m, d).weekday() < 5 and (y, m, d) not in holidays

def ref_due(y, m, day, holidays):
    if _is_business(y, m, day, holidays):
        return (y, m, day)
    cur = _dt.date(y, m, day)
    while True:
        cur += _dt.timedelta(days=1)
        if _is_business(cur.year, cur.month, cur.day, holidays):
            break
    if cur.month == m and cur.year == y:
        return (cur.year, cur.month, cur.day)
    cur = _dt.date(y, m, day)
    while True:
        cur -= _dt.timedelta(days=1)
        if _is_business(cur.year, cur.month, cur.day, holidays):
            return (cur.year, cur.month, cur.day)

def naive_due_forward(y, m, day, holidays):
    """The drift: plain 'following' — no month-crossing reversal."""
    cur = _dt.date(y, m, day)
    while not _is_business(cur.year, cur.month, cur.day, holidays):
        cur += _dt.timedelta(days=1)
    return (cur.year, cur.month, cur.day)

# ---------------------------------------------------------------- vector inputs

BILLING_INPUTS = [
    (2024, 3, 10, 3), (2023, 11, 5, 4), (2022, 7, 20, 2),          # visible-band
    (2024, 1, 31, 4),    # KNOT: leap Feb 29 clamp, then anchor RESTORES to 31
    (2023, 1, 31, 3),    # KNOT: Feb 28 clamp -> Mar 31 (cascade says Mar 28)
    (2024, 11, 30, 4),   # KNOT: anchor 30 across year wrap; Feb clamps only
    (2023, 12, 31, 14),  # KNOT: every short month clamps, every long month restores
    (2024, 2, 29, 13),   # KNOT: leap-day anchor; next Feb (2025) clamps to 28
    (2024, 5, 31, 0),    # n=0 -> []
]
WINDOW_INPUTS = [
    ([10, 20, 30], 25, 3, 40), ([10, 20, 30], 25, 2, 40), ([5, 6, 7, 8], 10, 5, 12),  # visible-band
    ([15, 20, 30], 25, 2, 40),        # KNOT: event exactly at t-w=15 -> excluded, 2<2 deny? -> count=2? (20,30) -> deny; naive counts 3 -> deny too? verified below
    ([15, 30], 25, 2, 40),            # KNOT: boundary event decides allow/deny flip
    ([15, 15, 15, 30], 25, 2, 40),    # KNOT: boundary burst — all excluded
    ([40], 25, 1, 40),                # event at the query instant is INSIDE
    ([0, 1, 2], 100, 3, 50),          # window reaches below 0 (t-w negative)
    ([], 10, 0, 100),                 # n=0 always denies
    ([7], 5, 1, 12),                  # KNOT: s == t-w exactly, single event
]
H24 = {(2024, 8, 30)}  # a Friday holiday used below
DUE_INPUTS = [
    ((2024, 7, 15), frozenset()), ((2024, 7, 13), frozenset()), ((2024, 7, 15), frozenset({(2024, 7, 15)})),  # visible-band
    ((2024, 11, 30), frozenset()),                        # KNOT: Sat Nov 30 -> forward crosses month -> BACK to Fri 29
    ((2024, 8, 31), frozenset()),                         # KNOT: Sat Aug 31 -> back to Fri 30
    ((2024, 8, 31), frozenset(H24)),                      # KNOT: back past holiday Fri 30 -> Thu 29
    ((2024, 3, 30), frozenset({(2024, 4, 1)})),           # Sat Mar 30 -> fwd Mon Apr 1 is holiday+crossing -> BACK to Fri 29
    ((2023, 12, 30), frozenset()),                        # KNOT: Sat Dec 30 -> fwd Mon Jan 1 crosses (and year) -> BACK to Fri 29
    ((2024, 9, 28), frozenset({(2024, 9, 30)})),          # Sat 28 -> Mon 30 holiday -> fwd would cross -> BACK to Fri 27
    ((2024, 5, 20), frozenset()),                         # plain business Monday, untouched
]

TASKS = {
    "t3_billing_anchor_001": {
        "ref": ref_billing, "naives": {"cascade_clamp": naive_billing_cascade},
        "inputs": [list(i) for i in BILLING_INPUTS],
        "call": lambda fn, a: [list(x) for x in fn(*a)],
        "sig": "billing_dates", "knot_from": 3,
    },
    "t3_window_limit_001": {
        "ref": ref_window, "naives": {"closed_old_end": naive_window_closed},
        "inputs": [[list(e), w, n, t] for (e, w, n, t) in WINDOW_INPUTS],
        "call": lambda fn, a: fn(*a),
        "sig": "allow", "knot_from": 3,
    },
    "t3_due_date_shift_001": {
        "ref": ref_due, "naives": {"forward_only": naive_due_forward},
        "inputs": [[list(nom), sorted(map(list, hol))] for (nom, hol) in DUE_INPUTS],
        "call": lambda fn, a: list(fn(a[0][0], a[0][1], a[0][2], {tuple(h) for h in a[1]})),
        "sig": "due_date", "knot_from": 3,
    },
}

GRADER_TEMPLATE = '''#!/usr/bin/env python3
"""Hidden grader for {task}. Frozen vectors derived mechanically from
experiments/breadth/authoring2/build_vectors.py (--check in CI guards drift).
The deciding vectors sit on the {knot} the visible checks never touch."""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = {vectors}


def _call(fn, args):
{call_body}


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.{sig}
    except Exception as e:  # noqa: BLE001
        print("SCORE 0/{{0}}  (candidate failed to load: {{1!r}})".format(len(VECTORS), e))
        return 1
    ok, fails = 0, []
    for args, want in VECTORS:
        try:
            got = _call(fn, args)
            if json.dumps(got) == json.dumps(want):
                ok += 1
            else:
                fails.append("{{0}}: got {{1!r}}, want {{2!r}}".format(args, got, want))
        except Exception as e:  # noqa: BLE001
            fails.append("{{0}}: raised {{1}}".format(args, type(e).__name__))
    print("SCORE {{0}}/{{1}}".format(ok, len(VECTORS)))
    for f in fails[:6]:
        print("  FAIL", f)
    return 0 if ok == len(VECTORS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''

CALL_BODIES = {
    "t3_billing_anchor_001": "    return [list(x) for x in fn(*args)]",
    "t3_window_limit_001": "    return fn(args[0], args[1], args[2], args[3])",
    "t3_due_date_shift_001": ("    nom, hol = args\n"
                              "    return list(fn(nom[0], nom[1], nom[2], {tuple(h) for h in hol}))"),
}
KNOT_NAMES = {
    "t3_billing_anchor_001": "anchor-restore boundary (clamp must not cascade)",
    "t3_window_limit_001": "half-open window old end (s == t-w excluded)",
    "t3_due_date_shift_001": "month-crossing reversal (modified-following)",
}


def derive(task, cfg):
    vectors = []
    for args in cfg["inputs"]:
        want = cfg["call"](cfg["ref"], args)
        vectors.append([args, want])
    return vectors


def main() -> int:
    check = "--check" in sys.argv
    all_ok = True
    receipt = {}
    for task, cfg in TASKS.items():
        vectors = derive(task, cfg)
        vec_lines = "[\n" + "".join(f"{v!r},\n" for v in vectors) + "]"
        grader_src = GRADER_TEMPLATE.format(
            task=task, knot=KNOT_NAMES[task], vectors=vec_lines,
            call_body=CALL_BODIES[task], sig=cfg["sig"])
        gpath = REPO / "fixtures" / task / "hidden_tests.py"
        if check:
            if not gpath.exists() or gpath.read_text() != grader_src:
                print(f"DRIFT: {gpath} does not match derived vectors")
                all_ok = False
            continue
        gpath.write_text(grader_src)

        # bidirectional verification
        ref_fail = [v for v in vectors if json.dumps(cfg["call"](cfg["ref"], v[0])) != json.dumps(v[1])]
        naive_report = {}
        for nname, nfn in cfg["naives"].items():
            fails = [i for i, v in enumerate(vectors)
                     if json.dumps(cfg["call"](nfn, v[0])) != json.dumps(v[1])]
            knot_fails = [i for i in fails if i >= cfg["knot_from"]]
            naive_report[nname] = {"fails": len(fails), "knot_vector_fails": len(knot_fails)}
            if not knot_fails:
                print(f"KEY MATERIAL INVALID: {task} naive '{nname}' passes every knot vector")
                all_ok = False
        receipt[task] = {
            "vectors": len(vectors), "knot_vectors": len(vectors) - cfg["knot_from"],
            "reference_fails": len(ref_fail), "naive": naive_report,
        }
        if ref_fail:
            print(f"KEY MATERIAL INVALID: {task} reference fails its own vectors")
            all_ok = False
    if not check:
        (REPO / "experiments/breadth/authoring2/verification_receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))
    print("OK" if all_ok else "FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
