#!/usr/bin/env python3
"""Authoring batch 3 — derive hidden vectors mechanically and verify key material.

Two tasks aimed at the only measured discriminator shapes (LESSONS 11b):

  * t3_null_filter_001 — FELT-CONTRADICTION: SQL-style three-valued logic.
    The rule is stated completely, but the correct reading (NOT of UNKNOWN is
    UNKNOWN; "!=" of an unknown is UNKNOWN) fights the boolean prior even
    after reading. Paired naives: none_is_false (None comparisons -> False,
    then plain booleans) and skip_none (any referenced None excludes).
  * t3_accrual_crossover_001 — DERIVED-QUANTITY: integer floor-compounded
    crossover. The answer must be derived by exact simulation; the paired
    naive is the formula-thinker (float compounding, no floor), which misses
    the stall case (initial interest floors to 0 forever -> None) and drifts
    at exact boundaries and long horizons.

Discipline (batch-2 post-review standard, applied from the start):
  * expected values are COMPUTED from the reference, never typed;
  * bidirectional verification runs in BOTH modes: reference passes every
    vector; every naive fails at least one knot vector;
  * generated graders ENFORCE declared return types (wrong container ->
    TypeError -> fail);
  * --check recomputes graders AND the verification receipt and fails on any
    diff (CI drift guard).

Run:  python experiments/breadth/authoring3/build_vectors.py          # derive + verify + write
      python experiments/breadth/authoring3/build_vectors.py --check  # CI drift guard
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# ------------------------------------------------------------- task A: kleene

TRUE, FALSE, UNKNOWN = "T", "F", "U"


def _cmp(a, op, b):
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b,
            "==": a == b, "!=": a != b}[op]


def _kleene(record, cond):
    kind = cond[0]
    if kind == "cmp":
        _, field, op, value = cond
        v = record.get(field)
        if v is None:
            return UNKNOWN
        return TRUE if _cmp(v, op, value) else FALSE
    if kind == "not":
        r = _kleene(record, cond[1])
        return {TRUE: FALSE, FALSE: TRUE, UNKNOWN: UNKNOWN}[r]
    if kind == "and":
        a, b = _kleene(record, cond[1]), _kleene(record, cond[2])
        if FALSE in (a, b):
            return FALSE
        if UNKNOWN in (a, b):
            return UNKNOWN
        return TRUE
    if kind == "or":
        a, b = _kleene(record, cond[1]), _kleene(record, cond[2])
        if TRUE in (a, b):
            return TRUE
        if UNKNOWN in (a, b):
            return UNKNOWN
        return FALSE
    raise ValueError(kind)


def ref_select(records, condition):
    return [r["id"] for r in records if _kleene(r, condition) == TRUE]


def _boolish(record, cond):
    kind = cond[0]
    if kind == "cmp":
        _, field, op, value = cond
        v = record.get(field)
        if v is None:
            return False
        return _cmp(v, op, value)
    if kind == "not":
        return not _boolish(record, cond[1])
    if kind == "and":
        return _boolish(record, cond[1]) and _boolish(record, cond[2])
    if kind == "or":
        return _boolish(record, cond[1]) or _boolish(record, cond[2])
    raise ValueError(kind)


def naive_none_is_false(records, condition):
    """The drift: None comparisons -> False, then ordinary booleans."""
    return [r["id"] for r in records if _boolish(r, condition)]


def _touches_none(record, cond):
    if cond[0] == "cmp":
        return record.get(cond[1]) is None
    return any(_touches_none(record, c) for c in cond[1:])


def naive_skip_none(records, condition):
    """The other drift: any referenced UNKNOWN excludes the record outright."""
    return [r["id"] for r in records
            if not _touches_none(r, condition) and _boolish(r, condition)]


RECS = [
    {"id": 1, "price": None, "cat": "a"},
    {"id": 2, "price": 150, "cat": None},
    {"id": 3, "price": 50, "cat": "b"},
]
RECS_KNOWN = [
    {"id": 1, "price": 50, "cat": "a"},
    {"id": 2, "price": 150, "cat": "b"},
    {"id": 3, "price": 99, "cat": "a"},
]
NULL_INPUTS = [
    # visible-band (all-known) — mirror main()
    [RECS_KNOWN, ["cmp", "price", ">", 100]],
    [RECS_KNOWN, ["not", ["cmp", "cat", "==", "a"]]],
    [RECS_KNOWN, ["and", ["cmp", "price", "<", 100], ["cmp", "cat", "==", "a"]]],
    # KNOT: bare cmp over UNKNOWN (coverage; UNKNOWN never selects)
    [RECS, ["cmp", "price", ">", 100]],
    # KNOT: NOT over UNKNOWN — the boolean prior says not(False)=True
    [RECS, ["not", ["cmp", "price", ">", 100]]],
    # KNOT: "!=" of an unknown is UNKNOWN, and its NOT stays UNKNOWN
    [RECS, ["not", ["cmp", "cat", "!=", "b"]]],
    # KNOT: OR TRUE-rescue — a known TRUE selects despite an UNKNOWN sibling
    [RECS, ["or", ["cmp", "cat", "==", "a"], ["cmp", "price", ">", 100]]],
    # KNOT: AND FALSE-domination with UNKNOWN sibling
    [RECS, ["and", ["cmp", "price", ">", 100], ["cmp", "cat", "==", "zzz"]]],
    # coverage: double negation of UNKNOWN
    [RECS, ["not", ["not", ["cmp", "price", ">", 100]]]],
    # KNOT: nested — NOT(UNKNOWN) inside OR inside AND
    [RECS, ["and", ["not", ["cmp", "price", "<=", 100]],
            ["or", ["cmp", "cat", "==", "x"], ["not", ["cmp", "cat", "==", "y"]]]]],
]
NULL_KNOT_FROM = 3

# --------------------------------------------------------- task B: crossover


def ref_crossover(principal, num, den, threshold, max_days):
    balance = principal
    if balance > threshold:
        return 0
    for d in range(1, max_days + 1):
        balance += (balance * num) // den
        if balance > threshold:
            return d
    return None


def naive_float_formula(principal, num, den, threshold, max_days):
    """The drift: float compounding without the integer floor."""
    if principal > threshold:
        return 0
    balance = float(principal)
    rate = 1.0 + num / den
    for d in range(1, max_days + 1):
        balance *= rate
        if balance > threshold:
            return d
    return None


CROSS_INPUTS = [
    # visible-band — mirror main()
    [1000, 1, 10, 2000, 30],
    [5000, 1, 4, 20000, 30],
    [100, 1, 2, 1000, 30],
    # KNOT: stall — initial interest floors to 0 forever; float grows anyway
    [100, 1, 1000, 5000, 100000],
    # KNOT: exact-boundary — balance lands exactly ON threshold (== is not >)
    [1000, 1, 10, 1210, 30],
    # day-0 rule (coverage)
    [5000, 1, 10, 4999, 10],
    # KNOT: long-horizon floor drag — float overestimates growth over thousands of days
    [1000000, 1, 997, 3000000, 20000],
    # KNOT: big-int precision — beyond float's 2^53 integer window
    [10**13, 3, 7, 10**15, 100],
    # coverage: crossing beyond max_days -> None for both
    [1000, 1, 10, 10**9, 50],
    # KNOT: near-stall but alive — interest exactly 1 at the start
    [1000, 1, 1000, 1100, 100000],
]
CROSS_KNOT_FROM = 3

# ---------------------------------------------------------------- generation

TASKS = {
    "t3_null_filter_001": {
        "ref": ref_select,
        "naives": {"none_is_false": naive_none_is_false, "skip_none": naive_skip_none},
        "inputs": NULL_INPUTS, "knot_from": NULL_KNOT_FROM,
        "call": lambda fn, a: list(fn(a[0], a[1])),
        "sig": "select_ids",
        "knot": "three-valued UNKNOWN under negation (the boolean prior)",
        "call_body": (
            "    got = fn(args[0], args[1])\n"
            "    if not isinstance(got, list) or not all(\n"
            "            isinstance(x, int) and not isinstance(x, bool) for x in got):\n"
            "        raise TypeError('select_ids must return list[int]')\n"
            "    return got"),
    },
    "t3_accrual_crossover_001": {
        "ref": ref_crossover,
        "naives": {"float_formula": naive_float_formula},
        "inputs": CROSS_INPUTS, "knot_from": CROSS_KNOT_FROM,
        "call": lambda fn, a: fn(*a),
        "sig": "crossover_day",
        "knot": "exact integer floor-compounding (stall, ==-boundary, float drift)",
        "call_body": (
            "    got = fn(*args)\n"
            "    if got is not None and (not isinstance(got, int) or isinstance(got, bool)):\n"
            "        raise TypeError('crossover_day must return int or None')\n"
            "    return got"),
    },
}

GRADER_TEMPLATE = '''#!/usr/bin/env python3
"""Hidden grader for {task}. Frozen vectors derived mechanically from
experiments/breadth/authoring3/build_vectors.py (--check in CI guards drift).
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


def main() -> int:
    check = "--check" in sys.argv
    all_ok = True
    receipt = {}
    for task, cfg in TASKS.items():
        vectors = [[a, cfg["call"](cfg["ref"], a)] for a in cfg["inputs"]]
        vec_lines = "[\n" + "".join(f"{v!r},\n" for v in vectors) + "]"
        grader_src = GRADER_TEMPLATE.format(
            task=task, knot=cfg["knot"], vectors=vec_lines,
            call_body=cfg["call_body"], sig=cfg["sig"])
        gpath = REPO / "fixtures" / task / "hidden_tests.py"
        if check:
            if not gpath.exists() or gpath.read_text() != grader_src:
                print(f"DRIFT: {gpath} does not match derived vectors")
                all_ok = False
        else:
            gpath.write_text(grader_src)

        # bidirectional verification — runs in BOTH modes
        ref_fail = [v for v in vectors
                    if json.dumps(cfg["call"](cfg["ref"], v[0])) != json.dumps(v[1])]
        naive_report = {}
        for nname, nfn in cfg["naives"].items():
            fails = []
            for i, v in enumerate(vectors):
                try:
                    bad = json.dumps(cfg["call"](nfn, v[0])) != json.dumps(v[1])
                except (TypeError, ValueError):
                    bad = True
                if bad:
                    fails.append(i)
            knot_fails = [i for i in fails if i >= cfg["knot_from"]]
            naive_report[nname] = {"fails": len(fails), "knot_vector_fails": len(knot_fails),
                                   "failing_vector_indexes": fails}
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

    rpath = REPO / "experiments/breadth/authoring3/verification_receipt.json"
    expected = json.dumps(receipt, indent=2) + "\n"
    if check:
        if not rpath.exists() or rpath.read_text() != expected:
            print(f"DRIFT: {rpath} does not match the recomputed verification receipt")
            all_ok = False
    else:
        rpath.write_text(expected)
        print(json.dumps(receipt, indent=2))
    print("OK" if all_ok else "FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
