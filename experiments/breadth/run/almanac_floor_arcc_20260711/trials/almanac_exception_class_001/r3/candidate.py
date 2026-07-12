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


def reduce_digit(n: int) -> int:
    """Reduce a number according to rule 1."""
    while n > 9:
        if n in (11, 22, 33):
            return n
        n = sum(int(digit) for digit in str(n))
    return n


def life_path(y: int, m: int, d: int) -> int:
    # Component 1: Reduced month
    reduced_month = reduce_digit(m)
    
    # Component 2: Reduced day
    reduced_day = reduce_digit(d)
    
    # Component 3: Reduced digit-sum of year
    year_sum = sum(int(digit) for digit in str(y))
    reduced_year = reduce_digit(year_sum)
    
    # Total: Sum components and reduce
    total = reduced_month + reduced_day + reduced_year
    result = reduce_digit(total)
    
    return result


def main() -> int:
    checks = [
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
