def merge_closed_ranges(ranges):
    normalized = sorted((min(a, b), max(a, b)) for a, b in ranges)
    merged = []
    for start, end in normalized:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged

