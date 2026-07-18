def merge_closed_ranges(ranges):
    """Merge closed integer intervals, normalizing reversed endpoints.

    Intervals are merged when they overlap or touch (no integer gap between them).
    """
    # Normalize reversed intervals and avoid mutating input.
    normalized = []
    for start, end in ranges:
        if start <= end:
            normalized.append((start, end))
        else:
            normalized.append((end, start))

    if not normalized:
        return []

    # Sort by interval start.
    normalized.sort(key=lambda x: x[0])

    merged = [normalized[0]]

    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]

        # Touching/overlapping if start is at most last_end + 1 (integer-closed intervals).
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged