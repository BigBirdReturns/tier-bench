"""Hidden grader for t3_parse_duration — never shown to the solver.

Every case below is derivable from the spec in input.py's docstring. The
visible checks in input.py cover only happy paths; these decide the grade.
"""
import sys

from input import parse_duration

VALID = [
    ("1h2m3s", 3723),
    ("0s", 0),
    ("010m", 600),
    ("999h", 3596400),
    ("2h15s", 7215),        # m omitted
    ("\t1h\n", 3600),       # surrounding tabs/newlines stripped
    ("0h0m0s", 0),
]

INVALID = [
    "1m1h",      # wrong order
    "1h1h",      # repeated unit
    "",          # empty
    "   ",       # whitespace only
    "42",        # bare number, no unit
    "h",         # unit with no count
    "1h30",      # trailing digits without a unit
    "1.5h",      # decimal
    "+1h",       # sign
    "-1h",       # sign
    "2H",        # uppercase unit
    "1h 30m",    # internal whitespace
    "1d",        # unknown unit
    "1s2m",      # wrong order (s before m)
]


def main() -> int:
    for text, want in VALID:
        try:
            got = parse_duration(text)
        except Exception as e:  # noqa: BLE001
            print(f"HIDDEN FAIL: parse_duration({text!r}) raised {type(e).__name__}: {e}")
            return 1
        if got != want:
            print(f"HIDDEN FAIL: parse_duration({text!r}) = {got!r}, want {want}")
            return 1
    for text in INVALID:
        try:
            got = parse_duration(text)
        except ValueError:
            continue
        except Exception as e:  # noqa: BLE001
            print(f"HIDDEN FAIL: parse_duration({text!r}) raised {type(e).__name__}, want ValueError")
            return 1
        print(f"HIDDEN FAIL: parse_duration({text!r}) = {got!r}, want ValueError")
        return 1
    print("HIDDEN OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
