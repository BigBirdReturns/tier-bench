from typing import Iterable, List, Tuple

def merge_closed_ranges(ranges: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    normalized = []
    for start, end in ranges:
        if start <= end:
            normalized.append((start, end))
        else:
            normalized.append((end, start))

    if not normalized:
        return []

    normalized.sort(key=lambda x: x[0])

    merged = []
    current_start, current_end = normalized[0]

    for start, end in normalized[1:]:
        if start <= current_end + 1:
            if end > current_end:
                current_end = end
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end

    merged.append((current_start, current_end))
    return merged