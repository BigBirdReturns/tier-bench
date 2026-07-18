def merge_closed_ranges(ranges):
    merged = []
    normalized = []

    for interval in ranges:
        start, end = interval
        if start > end:
            start, end = end, start
        normalized.append((start, end))

    normalized.sort(key=lambda x: x[0])

    for start, end in normalized:
        if not merged:
            merged.append((start, end))
            continue

        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged