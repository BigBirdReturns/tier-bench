def parse_duration(s: str) -> int:
    if s == "":
        raise ValueError("empty duration")

    total = 0
    i = 0
    seen = set()
    order = {"h": 0, "m": 1, "s": 2}
    last_order = -1

    while i < len(s):
        if not s[i].isdigit():
            raise ValueError("expected count")

        j = i
        while j < len(s) and s[j].isdigit():
            j += 1

        if j == len(s):
            raise ValueError("missing unit")

        unit = s[j]
        if unit not in order:
            raise ValueError("unknown unit")
        if unit in seen:
            raise ValueError("repeated unit")

        unit_order = order[unit]
        if unit_order <= last_order:
            raise ValueError("units out of order")

        seen.add(unit)
        last_order = unit_order
        total += int(s[i:j]) * (3600 if unit == "h" else 60 if unit == "m" else 1)
        i = j + 1

    return total
