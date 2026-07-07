import re

def parse_duration(s: str) -> int:
    if not s:
        raise ValueError("Duration string cannot be empty")

    pattern = r'(\d+)([a-z])'
    matches = re.findall(pattern, s)

    reconstructed = ''.join(count + unit for count, unit in matches)
    if reconstructed != s:
        raise ValueError(f"Invalid duration format: {s}")

    unit_order = {'h': 0, 'm': 1, 's': 2}
    unit_to_seconds = {'h': 3600, 'm': 60, 's': 1}

    seen_units = set()
    last_unit_order = -1
    total_seconds = 0

    for count_str, unit in matches:
        if unit not in unit_to_seconds:
            raise ValueError(f"Unknown unit: {unit}")

        current_order = unit_order[unit]
        if current_order <= last_unit_order:
            raise ValueError(f"Units out of order: {unit}")
        last_unit_order = current_order

        if unit in seen_units:
            raise ValueError(f"Unit {unit} repeated")
        seen_units.add(unit)

        count = int(count_str)
        total_seconds += count * unit_to_seconds[unit]

    return total_seconds
