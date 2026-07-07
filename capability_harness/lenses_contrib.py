"""
Community lens registry — the part that compounds.

`uplift.DEFAULT_LENSES` is the frozen five: generic, task-independent, proven to
transfer blind. This file is where *everyone else* adds to the library. Every
lens here is a captured frontier move — a specific way of looking that a single
pass tends to miss — written once and then runnable on a cheap model forever.

The bar to get in (enforced by `scripts/validate_lens.py`, not by taste):

  1. GENERIC — it names a *class* of failure ("aliasing", "resource lifetime"),
     never a specific bug in a specific file. If it only works on the subject it
     shipped with, it is tailoring, not a lens.
  2. PROVEN — it must surface, on a HELD-OUT subject, at least one real issue the
     same model's plain single pass missed. A lens that never adds a finding the
     baseline already had is dead weight; the validator rejects it.
  3. ATTRIBUTED — it carries where it came from and what it caught, so the library
     stays auditable as it grows.

Add yours to `CONTRIB_LENSES` below and open a PR. See CONTRIBUTING.md → "Contribute
a lens." The union of DEFAULT + CONTRIB is what `all_lenses()` returns; opt in with
`review(code, call, lenses=all_lenses())`.
"""
from __future__ import annotations

from dataclasses import dataclass

from .uplift import DEFAULT_LENSES, Lens


@dataclass(frozen=True)
class ContribLens:
    """A community lens plus the provenance that earned it a place."""
    lens: Lens
    author: str          # who proposed it (github handle / name)
    proven_on: str       # held-out subject it lifted a model on (path or short id)
    caught: str          # the class of issue it surfaced that the baseline missed


# Seeded empty on purpose: the five defaults are the whole proven set today, and
# the honest thing is to grow this from real, validated contributions rather than
# pad it. Your PR is the first entry.
CONTRIB_LENSES: list[ContribLens] = [
    # ContribLens(
    #     lens=Lens("resource_lifetime",
    #         "RESOURCE LIFETIME only: every acquire (open file, lock, connection, "
    #         "allocation) matched to a release on ALL paths including exceptions and "
    #         "early returns; double-release; use-after-release; leak on the error path."),
    #     author="your-handle",
    #     proven_on="fixtures/tX_leaky_pool",
    #     caught="a file handle left open on the validation-error return",
    # ),
]


def contrib_lenses() -> list[Lens]:
    """Just the plain lenses from the community registry (provenance stripped)."""
    return [c.lens for c in CONTRIB_LENSES]


def all_lenses() -> list[Lens]:
    """The frozen five plus every validated community lens. De-duplicated by key;
    the default keeps priority if a contribution collides on a key."""
    seen = {ln.key for ln in DEFAULT_LENSES}
    extra = [ln for ln in contrib_lenses() if ln.key not in seen]
    return list(DEFAULT_LENSES) + extra
