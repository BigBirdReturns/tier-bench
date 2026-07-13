"""Business-day due-date adjustment — the shift rules, applied exactly.

Implement:

    def due_date(y, m, day, holidays) -> tuple[int, int, int]

The nominal due date is `(y, m, day)` — a valid Gregorian date, 1900 <= y <=
2100. `holidays` is a set of `(year, month, day)` tuples (dates that are
holidays; may be empty; may include weekend dates). Return the adjusted due
date as a `(year, month, day)` tuple.

The rules (complete — every sentence is normative):

1. A BUSINESS DAY is a day that is neither a Saturday nor a Sunday nor listed
   in `holidays`.

2. If the nominal due date is a business day, it is the due date — return it
   unchanged.

3. Otherwise move FORWARD one calendar day at a time to the first business
   day.

4. EXCEPT: if the forward move of rule 3 would produce a date in a different
   calendar month than the nominal due date, do not use it; instead move
   BACKWARD one calendar day at a time from the nominal due date to the first
   business day. (The backward result may itself be earlier in the same month;
   in valid inputs a backward search always finds a business day inside the
   nominal month.)

Notes: pure calendar arithmetic, no timezone. The standard library (including
`datetime`) is available; `datetime.date(y, m, d).weekday()` returns 5 for
Saturday and 6 for Sunday.
"""


def due_date(y: int, m: int, day: int, holidays: set) -> tuple[int, int, int]:
    raise NotImplementedError


def main() -> int:
    checks = [
        # ordinary mid-month cases (no month boundary in play)
        ((2024, 7, 15, set()), (2024, 7, 15)),            # Monday — already business
        ((2024, 7, 13, set()), (2024, 7, 15)),            # Saturday -> forward to Monday
        ((2024, 7, 15, {(2024, 7, 15)}), (2024, 7, 16)),  # holiday Monday -> Tuesday
    ]
    ok = True
    for args, want in checks:
        got = due_date(*args)
        if tuple(got) != want:
            print(f"FAIL {args}: got {got}, want {want}")
            ok = False
    if ok:
        print("OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
