import re

_TOKEN = re.compile(r"(\d+)([hms])")
_ORDER = {"h": 0, "m": 1, "s": 2}
_MULTIPLIER = {"h": 3600, "m": 60, "s": 1}


def parse_duration(s: str) -> int:
    if not isinstance(s, str) or not s:
        raise ValueError("invalid duration string")
    if any(ch.isspace() for ch in s):
        raise ValueError("invalid duration string")

    total = 0
    pos = 0
    last_order = -1
    seen = set()

    for match in _TOKEN.finditer(s):
        if match.start() != pos:
            raise ValueError("invalid duration string")
        count_text, unit = match.groups()
        order = _ORDER[unit]
        if unit in seen or order <= last_order:
            raise ValueError("invalid duration string")
        seen.add(unit)
        last_order = order
        total += int(count_text) * _MULTIPLIER[unit]
        pos = match.end()

    if pos != len(s):
        raise ValueError("invalid duration string")

    return total
