def pick(xs, k):
    """Return the maximum total value of exactly k picks from xs such that no two
    picked positions are adjacent (|i - j| > 1 for every pair of picked indices
    i, j). Return None if no such selection of exactly k positions exists."""
    n = len(xs)
    order = sorted(range(n), key=lambda i: (-xs[i], i))
    chosen = []

    def ok(sel, j):
        return all(abs(j - c) > 1 for c in sel)

    for i in order:
        if len(chosen) == k:
            break
        if ok(chosen, i):
            chosen.append(i)
    if len(chosen) == k:
        return sum(xs[i] for i in chosen)
    # Repair pass: greedy fell short, so try exchanging one chosen position for
    # one unchosen position, then greedily extending; keep the best result that
    # reaches exactly k picks.
    best = None
    for c in list(chosen):
        for u in range(n):
            if u in chosen:
                continue
            trial = [i for i in chosen if i != c]
            if not ok(trial, u):
                continue
            trial.append(u)
            for i in order:
                if len(trial) == k:
                    break
                if i not in trial and ok(trial, i):
                    trial.append(i)
            if len(trial) == k:
                s = sum(xs[i] for i in trial)
                if best is None or s > best:
                    best = s
    return best
