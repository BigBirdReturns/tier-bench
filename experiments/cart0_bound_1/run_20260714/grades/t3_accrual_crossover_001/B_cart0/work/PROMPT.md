Task: Implement the function specified in the docstring of input.py exactly.

Rules:
- Return ONLY the full updated content for input.py.
- Do not add commentary.
- Make the program print OK and exit 0 when run.
- The docstring spec is the contract: EVERY rule in it is graded, including cases the visible checks in main() do not exercise. Implement the spec, not just the sample checks.
- Do not modify any file outside input.py.

Current file content:
"""Daily floor-compounded accrual — find the crossover day, exactly.

Implement:

    def crossover_day(principal, num, den, threshold, max_days) -> int | None

All inputs are ints: starting balance `principal` (cents, >= 1), daily rate
num/den (1 <= num < den <= 10**6), `threshold` (cents), and `max_days`
(1 <= max_days <= 200000).

The rules (complete — every sentence is normative):

1. The balance is `principal` at the end of day 0.

2. If the balance at the end of day 0 already strictly exceeds `threshold`,
   the answer is 0.

3. At the end of each day d = 1, 2, ..., max_days the balance grows by that
   day's interest, computed on the balance at the end of the previous day:

       interest = (balance * num) // den      (integer floor division)
       balance  = balance + interest

4. The answer is the smallest d with balance strictly greater than
   `threshold` at the end of day d; if no d <= max_days satisfies that,
   return None.

5. Exact integer arithmetic is normative: every intermediate value above is
   an exact integer, and an implementation whose result differs from exact
   integer evaluation of these rules for ANY valid input is incorrect.

Notes: deterministic, standard library only.
"""


def crossover_day(principal: int, num: int, den: int, threshold: int, max_days: int):
    raise NotImplementedError


def main() -> int:
    checks = [
        # ordinary growing cases (no boundary in play)
        ((1000, 1, 10, 2000, 30), 8),      # +10%/day, floor
        ((5000, 1, 4, 20000, 30), 7),      # +25%/day
        ((100, 1, 2, 1000, 30), 6),        # +50%/day
    ]
    ok = True
    for args, want in checks:
        got = crossover_day(*args)
        if got != want:
            print(f"FAIL {args}: got {got}, want {want}")
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
  File "<SOLVER_ROOT>\input.py", line 60, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "<SOLVER_ROOT>\input.py", line 49, in main
    got = crossover_day(*args)
          ^^^^^^^^^^^^^^^^^^^^
  File "<SOLVER_ROOT>\input.py", line 37, in crossover_day
    raise NotImplementedError
NotImplementedError


Other files in fixture (read-only context):

