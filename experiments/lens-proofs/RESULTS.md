# Lens-proof attempts — the gate refusing dead weight

The flywheel's bar for a new lens is objective: on a **held-out** subject it was
not written for, the lens's single pass must surface a real issue the same model's
plain pass **missed** (`scripts/validate_lens.py`). This is the honest record of
trying to mint the first community lens — and failing the bar three times, on
purpose kept as data.

Model: `claude-haiku-4-5` (the cheap tier), real instances, one baseline pass vs
one lens pass per subject.

| # | candidate lens | held-out subject | baseline (no lens) | lens | verdict |
|---|---|---|---|---|---|
| 1 | resource_lifetime | leaked lock on an early return (`resource_lifetime/subject.py`, v1) | **caught it** (+ the exception paths) | caught it | **no lift — rejected** |
| 2 | resource_lifetime | use-after-close: a reader escaping its `with` block (v2) | **caught it** | caught it | **no lift — rejected** |
| 3 | concurrency | TOCTOU memoize + non-atomic increment (`concurrency/subject.py`) | **caught both** | caught both | **no lift — rejected** |

Three plausible, genuinely-new classes. In every case the cheap model's *general*
review already found the defect zero-shot, so the targeted lens added nothing. Per
the doctrine, none was added to `CONTRIB_LENSES`; the registry stays at the frozen
five, and the sealed shard with it.

## What this actually shows (it's not a null result)

1. **The gate is real and unfakeable.** A lens cannot enter by sounding good — it
   has to beat the model's own general pass on code it hasn't seen. Three did not.
   That is exactly what keeps the library (and the shard) worth trusting.

2. **Broad categories are not the cheap model's blind spot.** "Resource lifetime,"
   "concurrency," "types" are categories a strong general reviewer *reaches for on
   its own*. Naming them buys no lift. The frozen five don't name broad categories
   either — they target **specific, easy-to-overlook semantic cases** (a boundary
   miscount, an aliased mutation, a wrong greedy/sort-key exposed by a constructed
   counterexample) that have no blanket warning a general pass reaches for.

3. **The lift is attention under load, not category knowledge.** In
   `experiments/tier-uplift`, the harness lifted haiku on subtle bugs it missed
   *inside larger, denser tasks* — where a single pass thins out across many
   things. On a 15-line subject a single pass sees everything, so no lens can lift
   there. **A valid new lens must therefore be proven on a dense subject** where the
   baseline pass demonstrably misses the target among real distractors.

## Consequence for contributors

The bar in `CONTRIBUTING.md` stands, with this sharpening: prove your lens on a
**dense** held-out subject (not a snippet), and target a **specific** failure mode,
not a category the model already checks. If the baseline pass catches it too, the
lens is dead weight — the validator will say so, as it did here.
