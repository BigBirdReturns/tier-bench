"""Pythagorean life path — the general rule and its exception class, exactly.

Implement:

    def life_path(y, m, d) -> int

Input is a birth date: year, month, day as ints. Return the life path number.

The rules (complete — every sentence is normative):

1. DIGIT REDUCTION. To reduce a number: while it is greater than 9, replace it
   with the sum of its decimal digits — EXCEPT that 11, 22, and 33 are master
   numbers and are terminal: whenever a value at ANY stage of ANY reduction
   equals 11, 22, or 33, reduction stops there and that value stands.

2. COMPONENTS. Compute three components: the reduced month, the reduced day,
   and the reduced digit-sum of the year (sum the year's four digits first,
   then reduce that sum under rule 1).

3. TOTAL. Sum the three components, then reduce the sum under rule 1. The
   result is the life path.

STEMS of the calculation are auditable integers; no strings, no dates
arithmetic — only rules 1-3.
"""


def life_path(y: int, m: int, d: int) -> int:
    def reduce(num):
        """Reduce a number following the master number rule."""
        while num > 9:
            if num in (11, 22, 33):
                return num
            num = sum(int(digit) for digit in str(num))
        return num

    # Compute the three components
    month_reduced = reduce(m)
    day_reduced = reduce(d)

    # Year: sum digits first, then reduce
    year_sum = sum(int(digit) for digit in str(y))
    year_reduced = reduce(year_sum)

    # Total: sum components and reduce
    total = month_reduced + day_reduced + year_reduced
    return reduce(total)


def main() -> int:
    checks = [
        # ordinary reductions (no master number in play)
        ((1990, 6, 15), 4),
        ((1966, 3, 6), 4),
        ((1959, 9, 9), 6),
    ]
    ok = True
    for args, want in checks:
        got = life_path(*args)
        if got != want:
            print(f"FAIL {args}: got {got}, want {want}")
            ok = False
    if ok:
        print("OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
