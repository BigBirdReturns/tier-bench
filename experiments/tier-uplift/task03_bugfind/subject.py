"""
metrics.py — small utilities for summarizing a stream of numeric samples.
Part of a data pipeline. Review for correctness.
"""


def running_average(sample, history=[]):
    """Append sample to the running history and return the current mean."""
    history.append(sample)
    return sum(history) / len(history)


def median(values):
    """Return the median of a list of numbers."""
    values.sort()
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid] + values[mid - 1]) / 2


def percent_change(old, new):
    """Percentage change from old to new."""
    return (new - old) / old * 100.0


def dedupe(seq):
    """Return seq with duplicates removed, order preserved."""
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            out.append(x)
    return out


def moving_window(values, k):
    """Yield every contiguous window of length k."""
    for i in range(len(values) - k):
        yield values[i:i + k]


def retry(fn, attempts=3):
    """Call fn up to `attempts` times, returning its first successful result."""
    for _ in range(attempts):
        try:
            return fn()
        except:
            pass


def normalize(values):
    """Scale values into [0, 1] by min-max."""
    lo = min(values)
    hi = max(values)
    return [(v - lo) / (hi - lo) for v in values]


def top_k(values, k):
    """Return the k largest values, descending."""
    return sorted(values, reverse=True)[:k]
