"""capability_harness — lift a cheap model to the tier above, on operational tasks.

    from capability_harness import review, DEFAULT_LENSES
    from capability_harness.backends import anthropic_backend
    call = anthropic_backend("claude-haiku-4-5")
    result = review(open("mycode.py").read(), call)
    print(result.merged_text())

Model-agnostic (bring your own `call(prompt)->str`), zero required dependencies,
frozen generic lenses. See README.md and tier-bench/experiments/tier-uplift for
the evidence.
"""
from .uplift import DEFAULT_LENSES, Lens, SweepResult, review, sweep

__all__ = ["review", "sweep", "DEFAULT_LENSES", "Lens", "SweepResult"]
__version__ = "0.1.0"
