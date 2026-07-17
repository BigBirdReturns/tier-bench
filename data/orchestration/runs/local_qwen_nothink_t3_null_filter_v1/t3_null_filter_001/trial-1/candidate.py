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
    def eval_cond(cond):
        if cond[0] == "cmp":
            field = cond[1]
            op = cond[2]
            val = cond[3]
            rec_val = records[field]  # guaranteed to exist per spec
            
            is_unknown = (rec_val is None)
            
            if is_unknown:
                return UNKNOWN
            
            try:
                res = eval(f"{val} {op} {records[field]}")
            except TypeError:
                # Fallback for string comparisons which might raise in some contexts, 
                # though spec says types don't mix. Safe to assume valid ops here.
                pass
                
            return True if res else False
            
        elif cond[0] == "not":
            inner = eval_cond(cond[1])
            if inner is UNKNOWN:
                return UNKNOWN
            return not inner
            
        elif cond[0] == "and":
            left = eval_cond(cond[1])
            right = eval_cond(cond[2])
            
            if left is False or right is False:
                return False
            if left is UNKNOWN or right is UNKNOWN:
                return UNKNOWN
            return True
            
        elif cond[0] == "or":
            left = eval_cond(cond[1])
            right = eval_cond(cond[2])
            
            if left is True or right is True:
                return True
            if left is UNKNOWN or right is UNKNOWN:
                return UNKNOWN
            return False
            
        else:
            # Should not happen based on spec
            raise ValueError(f"Unknown operator type in condition: {cond[0]}")

    TRUE = object()
    FALSE = object()
    UNKNOWN = object()
    
    selected_ids = []
    for rec in records:
        result = eval_cond(condition)
        if result is TRUE:
            selected_ids.append(rec["id"])
            
    return selected_ids


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