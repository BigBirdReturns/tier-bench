from typing import Iterable, List, Tuple


def merge_closed_ranges(ranges: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """
    Merge closed integer intervals, treating touching intervals as overlapping.
    Returns a new list of (start, end) tuples sorted by start.
    """
    # Normalize and sort without mutating input
    normalized = []
    for start, end in ranges:
        if start > end:
            start, end = end, start
        normalized.append((start, end))

    normalized.sort(key=lambda interval: interval[0])

    merged: List[Tuple[int, int]] = []
    for start, end in normalized:
        if not merged:
            merged.append((start, end))
            continue

        last_start, last_end = merged[-1]

        # Overlap or touch in integer domain
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged