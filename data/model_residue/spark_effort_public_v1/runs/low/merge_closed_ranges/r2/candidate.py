def merge_closed_ranges(ranges):
    """
    Merge closed integer intervals that overlap or touch.

    Two intervals [a, b] and [c, d] (with integer points) are merged when
    c <= b + 1 after normalization, because there is no integer gap.
    """
    # Normalize each interval so start <= end and avoid mutating input.
    normalized = []
    for start, end in ranges:
        if start <= end:
            normalized.append((start, end))
        else:
            normalized.append((end, start))

    if not normalized:
        return []

    # Sort by start, then end for deterministic order.
    normalized.sort(key=lambda interval: (interval[0], interval[1]))

    merged = [normalized[0]]

    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:  # overlap or touch as integer sets
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged