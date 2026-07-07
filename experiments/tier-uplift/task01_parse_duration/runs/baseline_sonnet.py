import re

_PATTERN = re.compile(r'^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$')


def parse_duration(s: str) -> int:
    if not isinstance(s, str):
        raise ValueError("input must be a string")

    match = _PATTERN.fullmatch(s)
    if not match:
        raise ValueError(f"invalid duration string: {s!r}")

    hours, minutes, seconds = match.groups()
    if hours is None and minutes is None and seconds is None:
        raise ValueError(f"invalid duration string: {s!r}")

    total = 0
    if hours is not None:
        total += int(hours) * 3600
    if minutes is not None:
        total += int(minutes) * 60
    if seconds is not None:
        total += int(seconds)

    return total
