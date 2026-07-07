"""
intervals.py — utilities over closed integer intervals [start, end].
Touching intervals (e.g. [1,2] and [2,3]) are considered to overlap and should
merge. Part of a scheduling service. Review for correctness.
"""


def merge_intervals(intervals):
    """Merge all overlapping (or touching) intervals; return a new sorted list."""
    if not intervals:
        return []
    s = sorted(intervals, key=lambda x: x[0])
    merged = [s[0]]
    for cur in s[1:]:
        last = merged[-1]
        if cur[0] < last[1]:
            last[1] = max(last[1], cur[1])
        else:
            merged.append(cur)
    return merged


def total_covered(intervals):
    """Total length covered by the union of the intervals."""
    return sum(e - s for s, e in merge_intervals(intervals))


def contains_point(intervals, p):
    """True iff point p lies within any interval (endpoints included)."""
    for s, e in intervals:
        if s < p < e:
            return True
    return False


def max_non_overlapping(intervals):
    """Maximum number of mutually non-overlapping intervals that can be chosen
    (classic interval scheduling; touching counts as overlapping)."""
    if not intervals:
        return 0
    s = sorted(intervals, key=lambda x: x[0])
    count = 1
    end = s[0][1]
    for cur in s[1:]:
        if cur[0] >= end:
            count += 1
            end = cur[1]
    return count


def busiest_point(intervals):
    """Return a point covered by the greatest number of intervals."""
    best_point, best_count = None, 0
    for s, e in intervals:
        count = sum(1 for a, b in intervals if a <= s <= b)
        if count > best_count:
            best_count = count
            best_point = s
    return best_point
