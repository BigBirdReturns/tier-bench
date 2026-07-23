Task: Implement the function specified in the docstring of input.py exactly.

Rules:
- Return ONLY the full updated content for input.py.
- Do not add commentary.
- Make the program print OK and exit 0 when run.
- The docstring spec is the contract: EVERY rule in it is graded, including cases the visible checks in main() do not exercise. Implement the spec, not just the sample checks.
- Do not modify any file outside input.py.

Current file content:
"""Record filtering with UNKNOWN values — the three-valued rules, applied exactly.

Implement:

    def select_ids(records, condition) -> list[int]

`records` is a list of dicts; each has an integer `"id"` plus data fields.
A data field's value may be `None`, meaning the value is UNKNOWN — the record
has the field, but its value is not known. `condition` is a nested list AST:

    ["cmp", field, op, value]   op in (">", "<", ">=", "<=", "==", "!=")
    ["not", cond]
    ["and", cond1, cond2]
    ["or",  cond1, cond2]

`value` in a cmp is always a known int or str (never None). In valid inputs a
compared field is always present on every record, and comparisons never mix
types.

The rules (complete — every sentence is normative):

1. A condition evaluates to exactly one of TRUE, FALSE, UNKNOWN.

2. A comparison whose record field value is None evaluates to UNKNOWN.
   Otherwise it evaluates to TRUE or FALSE by the ordinary comparison. This
   applies to EVERY operator — including "!=": an unknown value is not known
   to differ from anything, so the result is UNKNOWN, not TRUE.

3. not: TRUE -> FALSE, FALSE -> TRUE, UNKNOWN -> UNKNOWN. The negation of
   "not known" is still not known.

4. and: FALSE if either side is FALSE; otherwise UNKNOWN if either side is
   UNKNOWN; otherwise TRUE.

5. or: TRUE if either side is TRUE; otherwise UNKNOWN if either side is
   UNKNOWN; otherwise FALSE.

6. A record is selected iff the whole condition evaluates to exactly TRUE.
   UNKNOWN never selects. Return the selected records' "id" values, in input
   order, as a list of ints.

Notes: pure computation, deterministic, standard library only.
"""


def select_ids(records: list, condition: list) -> list:
    raise NotImplementedError


def main() -> int:
    recs = [
        {"id": 1, "price": 50, "cat": "a"},
        {"id": 2, "price": 150, "cat": "b"},
        {"id": 3, "price": 99, "cat": "a"},
    ]
    checks = [
        # ordinary all-known cases (no UNKNOWN in play)
        ((recs, ["cmp", "price", ">", 100]), [2]),
        ((recs, ["not", ["cmp", "cat", "==", "a"]]), [2]),
        ((recs, ["and", ["cmp", "price", "<", 100], ["cmp", "cat", "==", "a"]]), [1, 3]),
    ]
    ok = True
    for args, want in checks:
        got = select_ids(*args)
        if list(got) != want:
            print(f"FAIL {args[1]}: got {got}, want {want}")
            ok = False
    if ok:
        print("OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


Baseline run (before edits):
exit=1
stdout:

stderr:
Traceback (most recent call last):
  File "<SOLVER_ROOT>\input.py", line 75, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "<SOLVER_ROOT>\input.py", line 64, in main
    got = select_ids(*args)
          ^^^^^^^^^^^^^^^^^
  File "<SOLVER_ROOT>\input.py", line 47, in select_ids
    raise NotImplementedError
NotImplementedError


Other files in fixture (read-only context):

