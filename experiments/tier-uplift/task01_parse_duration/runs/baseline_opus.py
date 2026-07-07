import re


def parse_duration(s: str) -> int:
    pattern = re.compile(r"(\d+)([hms])")
    order = {"h": 0, "m": 1, "s": 2}
    multipliers = {"h": 3600, "m": 60, "s": 1}

    pos = 0
    total = 0
    seen = set()
    last_order = -1
    matched_any = False

    for match in pattern.finditer(s):
        if match.start() != pos:
            raise ValueError("invalid duration string")
        count_str, unit = match.group(1), match.group(2)
        if unit in seen:
            raise ValueError("repeated unit")
        if order[unit] <= last_order:
            raise ValueError("units out of order")
        seen.add(unit)
        last_order = order[unit]
        total += int(count_str) * multipliers[unit]
        pos = match.end()
        matched_any = True

    if not matched_any or pos != len(s):
        raise ValueError("invalid duration string")

    return total
