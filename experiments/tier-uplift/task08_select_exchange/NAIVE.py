# Acceptance artifact: the plausible-but-insufficient submission (must FAIL).
#
# This is the pattern-matched answer: "greedy takes the middle 5 and blocks both
# 4s" — the classic non-adjacent-selection trap. It is exactly what a solver who
# recognizes the problem family (but does not read the repair pass) submits.
# The subject's exchange repair handles this shape, so it is NOT a counterexample.


def counterexample():
    return ([4, 5, 4], 2)
