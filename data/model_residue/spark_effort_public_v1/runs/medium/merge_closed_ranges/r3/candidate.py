def merge_closed_ranges(ranges):
    """
    Merge closed integer intervals where intervals that overlap or touch are combined.

    Args:
        ranges: Iterable of (start, end) integer pairs. Each pair may be reversed.

    Returns:
        List of merged (start, end) tuples sorted by start.
    """
    normalized = []

    for interval in ranges:
        start, end = interval
        if start <= end:
            normalized.append((start, end))
        else:
            normalized.append((end, start))

    if not normalized:
        return []

    normalized.sort(key=lambda x: (x[0], x[1]))

    merged = [normalized[0]]
    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:  # overlap or touch with no integer gap
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged