"""
select.py — bespoke constrained selection for a resource-quota system.
Review for correctness.
"""


def select(items, k):
    """Choose exactly `k` distinct items to MAXIMIZE total value, subject to the
    quota rule that the total weight of the chosen items must be divisible by 3.

    items: list of (value, weight) with value > 0 and weight >= 0, both ints.
    Return the maximum achievable total value, or None if no choice of exactly k
    items has total weight divisible by 3 (or if k is out of range).
    """
    n = len(items)
    if k < 0 or k > n:
        return None

    # Rank by value, take the k most valuable.
    order = sorted(range(n), key=lambda i: -items[i][0])
    chosen = order[:k]

    def wsum(sel):
        return sum(items[i][1] for i in sel)

    def vsum(sel):
        return sum(items[i][0] for i in sel)

    # If the top-k already satisfy the quota, that's optimal.
    if wsum(chosen) % 3 == 0:
        return vsum(chosen)

    # Otherwise repair: swap one chosen item for one un-chosen item to hit the
    # quota, keeping the most valuable such swap.
    rest = order[k:]
    best = None
    for c in chosen:
        for r in rest:
            candidate = [x for x in chosen if x != c] + [r]
            if wsum(candidate) % 3 == 0:
                v = vsum(candidate)
                if best is None or v > best:
                    best = v
    return best
