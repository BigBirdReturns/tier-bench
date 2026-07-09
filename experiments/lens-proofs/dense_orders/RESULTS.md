# dense_orders — the dense-subject mint run (scored matrix)

The re-test LESSONS.md prescribed: candidate lenses failed the bar on small
subjects, where a single pass sees everything; prove or kill them on a **dense**
subject where attention thins. Subject: `subject.py` (~190 lines, realistic
order-fulfillment module), 10 planted defects across 8 classes, keyed in
`answer_key.md` (hidden from all solvers — every agent got the code inline and
zero file access).

Solvers: real `claude-haiku-4-5` instances, one pass each. 1 baseline (general
review) + the 5 frozen shard lenses + 2 candidates (`resource_lifetime`,
`concurrency_atomicity`). K=1 — this is a lens-validation run, not a settled-cell
claim. Subagent tokens ≈ 159k (shadow-class; session subagents, no provider bill).

## The matrix

✅ = caught (function + mechanism, per the key; ties scored AGAINST the lens)

| bug | class | baseline | ctrl_flow | state | data_types | contracts | adversarial | res_life* | concur* |
|-----|-------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| B1 page off-by-one | control_flow | ✅ | ✅ | — | ✅ | — | ✅ | — | — |
| B2 DEFAULT_FILTERS mutation | state | ✅ | — | ✅ | ✅ | ✅ | — | — | — |
| B3 float `==` on money | data_types | ❌ | — | — | ✅ **lift** | — | — | — | — |
| B4 reserve TOCTOU (no lock) | concurrency | ✅ | — | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| B5a generator escapes `with` (use-after-close) | resource | ✅ | — | — | — | — | — | ✅ | — |
| B5b handle leak on early return | resource | ✅ | — | ✅ | — | ✅ | ✅ | ✅ | — |
| B6a parse_qty silent 0 | contracts | ❌ | — | — | — | ✅ **lift** | — | — | — |
| B6b unknown SKU priced $0.00 | contracts | ❌ | — | — | — | ✅ **lift** | — | — | — |
| B7 discount sort violates SPEC | adversarial | ✅ | ✅ | ✅ | — | ✅ | ✅ | — | — |
| B8 UTC docstring vs local now() | time | ✅ | — | — | ✅ | ✅ | ✅ | — | — |
| **total /10** | | **7** | 2 | 4 | 5 | 6 | 5 | 2 | 1 |

\* candidates

## Verdicts

**1. The frozen five re-proved themselves with unique lift — density works.**
Baseline 7/10. `data_types` recovered B3 (float `==` money, with accumulation
reasoning); `contracts` recovered B6a AND B6b. Baseline ∪ frozen five = **10/10**.
This is the task05 result reproduced on a fresh dense subject: the misses of a
single general pass concentrate in specific lanes, and the lanes recover them.

**2. Both candidates are dead — third kill, corroborated, retired.**
`resource_lifetime` caught its full lane (B5a+B5b) and `concurrency` produced the
single deepest B4 analysis of any agent (incl. the lost-update interleaving against
`release`'s locked write) — but the baseline had every one of those bugs already.
Zero unique lift on two small subjects and now a dense one. Resource lifetime and
concurrency are **not haiku blind spots at any tested density**. Candidates
permanently retired; do not re-propose without a fundamentally different failure
mode (see the bar in CONTRIBUTING.md).

**3. NEW FINDING — the deployed sweep has tunnel vision without a general pass.**
The shipped harness (`review()` = the five lens passes, no general pass) unions to
only **9/10 on this subject: every frozen lens missed B5a** (the generator escaping
its `with` block). The baseline caught it; the killed resource_lifetime candidate
caught it; no frozen lens owns that class. Focused apertures buy recall in their
lanes and pay for it with blindness between lanes — "iteration can only buy what
selection can see" applies to the lens set itself. **Fix (shipped with this run):
`review()` now includes a general open pass alongside the five frozen lenses by
default** (`include_general=False` restores the old behavior). This is harness
*composition*, not a new lens — a general pass definitionally cannot pass the
lens-vs-baseline bar, and the frozen five stay frozen; the sealed shard is
unchanged.

**4. Bycatch — unplanted but real defects the agents found (subject realism check).**
- negative `n` accepted by `reserve`/`restock`/`release` (silent stock corruption)
- `page_count(n, size=0)` unguarded division by zero; `page_of(..., size=0)` silent empty
- `search_orders` never applies its own `status` filter (it is decorative)
- `fulfill` leaves reservations un-released if `mkdir`/`export_report` raises
- `apply_discounts` treats unknown kinds as "fixed"; negative values become surcharges

These are now part of the key's value: the subject is reusable as a dense probe,
and any future run can be scored against planted + bycatch.

## Honest scope

K=1 per pass; the lens-validation bar (unique lift vs baseline on held-out dense
code) is met/failed decisively at K=1 for these verdicts, but no *capability*
"settled" claim is made from this run. Judged by the session driver against the
pre-committed key, quotes above; ambiguous credit went against the lens.
