from typing import Iterable, List, Tuple


def merge_closed_ranges(ranges: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    normalized = sorted(
        ((a, b) if a <= b else (b, a) for a, b in ranges),
        key=lambda interval: interval[0],
    )

    merged: List[Tuple[int, int]] = []

    for start, end in normalized:
        if not merged:
            merged.append((start, end))
            continue

        last_start, last_end = merged[-1]

        if start <= last_end + 1:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))

    return merged