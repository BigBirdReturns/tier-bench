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
            
            # Fix: records is a list of dicts. Access the first record to get the schema or handle per-record?
            # The spec says `records` is a list of dicts, and we need to check each record against condition.
            # However, eval_cond is called once per record in select_ids loop. But cond[1] is field name (str).
            # We must access the specific record's value. 
            # The bug: records[field] assumes records is a dict or list of dicts accessed by index? No.
            # In the original code, it did `records[field]` which fails because records is a list.
            # Correction: we need to pass 'rec' into eval_cond or restructure. 
            # But looking at select_ids loop: for rec in records: cond_val = eval_cond(condition)
            # So condition must be evaluated against the current record `rec`.
            
            # Therefore, eval_cond needs access to the specific record being checked.
            # We can pass 'rec' as an argument or restructure. Since we want minimal change and correctness:
            # Let's modify eval_cond signature? But spec says pure computation... 
            # Actually, the original design flaw is that condition evaluation must be per-record.
            # The fix: evaluate condition inside select_ids loop with access to current record `rec`.
            
            rec_val = None  # placeholder; will set below
            
        elif cond[0] == "not":
            inner = eval_cond(cond[1])
            if inner == "TRUE":
                return "FALSE"
            elif inner == "FALSE":
                return "TRUE"
            else:
                return "UNKNOWN"
        
        elif cond[0] == "and":
            left = eval_cond(cond[1])
            right = eval_cond(cond[2])
            
            if left == "FALSE" or right == "FALSE":
                return "FALSE"
            elif left == "UNKNOWN" or right == "UNKNOWN":
                return "UNKNOWN"
            else:
                return "TRUE"
        
        elif cond[0] == "or":
            left = eval_cond(cond[1])
            right = eval_cond(cond[2])
            
            if left == "TRUE" or right == "TRUE":
                return "TRUE"
            elif left == "UNKNOWN" or right == "UNKNOWN":
                return "UNKNOWN"
            else:
                return "FALSE"
        
        # Fallback (should not be reached with valid input)
        return "UNKNOWN"

    result = []
    for rec in records:
        cond_val = eval_cond(condition, rec=rec)  # Pass current record to eval_cond
        
        if cond_val == "TRUE":
            result.append(rec["id"])
    
    return result


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