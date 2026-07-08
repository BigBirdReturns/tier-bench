"""Duration parser — implement parse_duration() exactly to this spec.

parse_duration(s: str) -> int
    Parse a compact duration string into total seconds.

    Format rules (ALL of them matter):
    - The string contains one or more components, each an integer count
      followed by a unit letter: 'h' (hours), 'm' (minutes), 's' (seconds).
    - Units must appear in the order h, then m, then s. Any unit may be
      omitted, but at least one must be present.
    - Each unit may appear AT MOST ONCE ("1h1h" is invalid).
    - Counts are one or more ASCII digits. No sign ("+1h", "-1h" invalid),
      no decimals ("1.5h" invalid). Leading zeros are fine ("010m" == 600).
    - Units are lowercase only ("2H" is invalid).
    - Leading and trailing whitespace (spaces, tabs, newlines) is ignored,
      but whitespace INSIDE the string is invalid ("1h 30m" invalid).
    - A bare number with no unit is invalid ("42" invalid), as is a unit
      with no count ("h" invalid) or trailing digits without a unit
      ("1h30" invalid). The empty string is invalid.
    - Return the total number of seconds as an int ("0s" -> 0).
    - Every invalid input raises ValueError.
"""


def parse_duration(s: str) -> int:
    raise NotImplementedError


def main() -> int:
    checks = [
        ("2h30m15s", 9015),
        ("90m", 5400),
        ("1h", 3600),
        ("45s", 45),
        (" 1m ", 60),
    ]
    for text, want in checks:
        got = parse_duration(text)
        if got != want:
            print(f"FAIL: parse_duration({text!r}) = {got!r}, want {want}")
            return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
