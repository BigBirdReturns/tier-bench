"""
capability_harness — lift a cheap model to the tier above, on operational tasks.

The whole thing in one idea: a single review pass misses what it doesn't look
for. Decompose the work into a fixed set of *targeted lenses*, run one pass per
lens, and union the findings. "Iteration can only buy what selection can see" —
the lens is what makes it see. Measured in tier-bench/experiments/tier-uplift:
haiku + this sweep matched sonnet and beat opus-solo on unseen tasks, ~4-5x
cheaper (see that folder's LEDGER.md).

Design goals for giving it to everyone:
  * MODEL-AGNOSTIC — you pass a `call(prompt) -> str` for YOUR model/provider.
    The harness has ZERO dependencies and no opinion about who you call.
  * FROZEN, GENERIC lenses — not tuned to any task. Same set every time.
  * OPERATIONAL, not surface — it hunts for what's actually wrong/missing, and
    unions across lenses; it does not care whether two runs phrase it the same.

    from capability_harness.uplift import review
    result = review(open("mycode.py").read(), call=my_model_call)
    for f in result.findings: print(f["lens"], "->", f["text"])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Lens:
    key: str
    instruction: str


# The five frozen, task-independent review lenses (verbatim from
# experiments/tier-uplift/lenses.md — the set proven to transfer blind).
DEFAULT_LENSES: list[Lens] = [
    Lens("control_flow",
         "CONTROL FLOW & BOUNDARIES only: every loop bound, range, slice, index, "
         "early return, termination condition. Trace a small example through any "
         "loop and count outputs against the intended count. Off-by-one, missed "
         "first/last element, wrong stop."),
    Lens("state",
         "STATE & EFFECTS only: mutation of arguments or shared/persistent state; "
         "aliasing; ordering of mutations vs checks; partial updates left un-rolled-"
         "back on an error path; two functions that disagree about an invariant."),
    Lens("data_types",
         "DATA & TYPES only: types and precision (int vs float), None/empty/"
         "degenerate inputs, conversions, comparisons that misbehave on ties or "
         "specific values, container-type assumptions."),
    Lens("contracts",
         "CONTRACTS & ERRORS only: missing input validation; silent failures; "
         "functions that return a misleading value instead of raising; unguarded "
         "division; documented invariants the code can violate."),
    Lens("adversarial",
         "ADVERSARIAL SEMANTICS only: assume the obvious implementation is subtly "
         "wrong and try to BREAK it. Is the whole approach (a greedy choice, a sort "
         "key, a recurrence) correct, or only on easy inputs? Actively CONSTRUCT a "
         "specific input that exposes a wrong algorithm, not just a wrong line."),
]

_PROMPT = """You are doing a focused code review through ONE lens only.

LENS — {instruction}

Review the target below. Report every issue this lens surfaces: for each, the
location (line/function), a one-sentence explanation of the failure, and a
concrete input or scenario that triggers it. If the lens surfaces nothing, say so.

----- TARGET -----
{target}
----- END TARGET -----"""


@dataclass
class SweepResult:
    findings: list[dict] = field(default_factory=list)   # {lens, text}
    by_lens: dict = field(default_factory=dict)          # lens key -> raw text
    calls: int = 0

    def merged_text(self) -> str:
        return "\n\n".join(f"## {f['lens']}\n{f['text']}" for f in self.findings)


def sweep(target: str,
          call: Callable[[str], str],
          lenses: list[Lens] = DEFAULT_LENSES) -> SweepResult:
    """Run one review pass per lens against `target`, using YOUR `call(prompt)->str`.
    Returns the union of what every lens saw. This is the whole mechanism.

    `call` is any callable that takes a prompt string and returns the model's text.
    Bring your own model — see capability_harness/backends.py for ready adapters,
    or write a two-line one for any provider you like."""
    res = SweepResult()
    for lens in lenses:
        text = call(_PROMPT.format(instruction=lens.instruction, target=target))
        res.calls += 1
        res.by_lens[lens.key] = text
        res.findings.append({"lens": lens.key, "text": (text or "").strip()})
    return res


# A plain, no-checklist pass. NOT part of the frozen lens registry (a general pass
# definitionally can't clear the lens bar — it IS the baseline). It exists because
# focused apertures buy recall in their lanes and pay with blindness between lanes:
# measured in experiments/lens-proofs/dense_orders, the five-lens sweep alone
# unioned 9/10 while a plain pass caught the one it missed (a generator escaping
# its `with` block). The sweep needs one open eye.
GENERAL_PASS = Lens(
    "general",
    "GENERAL, no fixed checklist: a careful, whole-file review. Report every real "
    "issue you find, especially anything that does not fit a named category.")


# `review` is the friendly name; kept separate from `sweep` so the public entry
# point can grow without changing the core. Since the dense_orders measurement it
# runs the general open pass alongside the frozen lenses by default —
# `include_general=False` restores the pure lens sweep.
def review(target: str, call: Callable[[str], str],
           lenses: list[Lens] = DEFAULT_LENSES,
           include_general: bool = True) -> SweepResult:
    run = ([GENERAL_PASS] + list(lenses)) if include_general else list(lenses)
    return sweep(target, call, run)
