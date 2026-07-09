# Acceptance artifact: a correct submission (must PASS).
#
# Derivation: the repair pass only fires when greedy falls short of k, and a
# single exchange changes at most one committed position. Force an arrangement
# where the optimum requires displacing BOTH greedy picks: five positions, k=3.
# Greedy takes the two 5s (indices 1 and 3), which shadow every other position;
# the only valid 3-pick is indices {0, 2, 4}, reachable from {1, 3} only by a
# double displacement. So pick returns None while 4+4+4 = 12 exists.


def counterexample():
    return ([4, 5, 4, 5, 4], 3)
