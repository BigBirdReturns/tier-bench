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
    def reduce_number(value: int) -> int:
        while value > 9 and value not in (11, 22, 33):
            digit_sum = 0
            while value:
                value, digit = divmod(value, 10)
                digit_sum += digit
            value = digit_sum
        return value

    year_digit_sum = 0
    remaining_year = y
    for _ in range(4):
        remaining_year, digit = divmod(remaining_year, 10)
        year_digit_sum += digit

    month_component = reduce_number(m)
    day_component = reduce_number(d)
    year_component = reduce_number(year_digit_sum)

    return reduce_number(month_component + day_component + year_component)


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