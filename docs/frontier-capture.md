# Frontier capture — measuring when expensive cognition becomes reusable machinery

*The economic proof object.* The repo's root primitive says frontier models are
discovery instruments, not answer vendors — that the durable output of a frontier
call is a **captured artifact** (a grader, an edge family, a routing rule, a
scaffold packet, a lens), not the answer itself. That claim is either measurable
or it is marketing. This layer makes it measurable:

```
Was expensive cognition converted into reusable machinery?
How much did it cost?
How many future frontier calls does it retire?
When did it break even?
```

Routing alone is not proof ("frontier orchestrator + cheap workers seems
cheaper" is a demo, not a measurement). Capture is proof when four things hold:
a **durable artifact exists**, its **cost is on a ledger**, **replays are
validated against a hidden grader**, and the **break-even arithmetic is done in
public** — with projection and fact kept apart.

## The objects

Rows live in `data/capture/*.jsonl`, typed by `record_type`. This pipeline has
its **own door** — capture rows never flow through `contribute.py` or
`data/results/` (that pipeline is for solve rows; this one is for machinery).

### `capture` (schemas/capture_ledger.schema.json)

One captured frontier move. The two path legs read as:

- **`new_path`** — the frontier call being **retired**: what you'd pay per trial
  without the artifact (for task02: sonnet-5 @ low, $0.227 real-billed).
- **`old_path`** — the **floor the replay runs on** once the artifact carries the
  judgment (haiku, ~$0.04 shadow-estimated).

So `savings_per_replay = new_path.cost − old_path.cost`, and
`projected_break_even = ceil(capture_cost / savings_per_replay)`.

### `delta_observation` (schemas/delta_observation.schema.json)

The raw material: what a higher rung did that a lower rung missed, scoped to one
task. `delta_types` name the axis (`edge_delta`, `framing_delta`,
`routing_delta`, `spec_delta`, `transport_delta` — the last is serialization
damage and must be adjudicated, never counted as model failure). A delta with
`capturable: true` must name `captured_as` — the artifact class it can freeze
into.

## Evidence classes

Every cost carries its basis, and mixed-basis arithmetic is named as such
(`capture_roi.py` prints the mix — a projection is only as hard as its softest
basis):

| basis | meaning |
|---|---|
| `real-billed` | provider-billed USD from the API response |
| `shadow-estimated` | exact tokens × price table, no bill |
| `subscription-derived` | UI/subscription lane; no per-call bill exists |
| `repaired-transport-adjudicated` | evidence reconstructed after transport damage, per an adjudication record |

## The closure rules (burden discipline, enforced in code)

"Amortized" is a **closure claim**, so every capture row carries a full burden
packet (`docs/burden-discipline.md`: requested outcome, claimant, authority,
predicates, burden holder, evidence, verifier, gap, closure decision, failure
default) and `scripts/validate_capture_ledger.py` enforces:

1. **No vaporware captures** — `captured_artifact.path` must exist in the repo.
2. **No amortization without replays** — `status: amortized` or
   `closure_decision: closed` with `validated_replays == 0` fails validation.
   The failure default is `needs_replay`/`partial`, never silence.
3. **Projection is not fact** — `break_even_reuse_count` stays `null` in the
   ledger until replays are validated; `capture_roi.py` computes the projection
   at read time and labels it PROJECTED. It is never written back.
4. **No fabricated receipts** — `validated_replays > 0` requires non-empty
   `replay_evidence`.
5. **Waterline is read-only** — a `waterline_effect` claim must resolve to a
   real waterline cell, and this ledger never mutates `waterline.json`.

## The replay protocol (how a projection becomes a fact)

A **validated replay** is one hidden-graded solve that used the captured
artifact on the floor path instead of a frontier call:

1. Emit the artifact in portable form: `python scripts/emit_scaffold.py --task <id>`.
2. Run the floor model with the packet in context on the task, K trials.
3. Grade against the **hidden** grader (never shown to the solver) and re-run
   the grade yourself — same rules as every breadth row.
4. Each passing, hidden-graded trial appends its ledger row to
   `replay_evidence` and increments `validated_replays`.
5. When `validated_replays ≥` the projected break-even, `capture_roi.py`
   reports `amortized` — and only then may the ledger row's
   `break_even_reuse_count` be set to the measured value.

This is also the crossing-event experiment: if the floor + artifact clears a
cell the floor alone couldn't (haiku bare 3/5 → haiku+packet K-of-K on task02),
the *system* beats raw model access on that cell, measured, at floor prices.

## The worked example

`data/capture/task02_escape_class_boundary.jsonl` — the first capture:

- **Artifact:** the task02 edge family + routing rule (in-class backslash is a
  literal, not an escape prefix), portable via `emit_scaffold.py`.
- **Capture cost:** $0.6805 real-billed (the three sonnet trials on the ledger:
  0.3405 + 0.1721 + 0.1679).
- **Savings per replay:** $0.187 (retire a $0.227 sonnet call onto a $0.04
  floor). **Projected break-even: 4 validated replays.**
- **State:** `needs_replay` — zero validated replays, and the row says so in its
  burden packet. The projection looks good; the ledger refuses to care until
  the hidden grader does.

```
python scripts/validate_capture_ledger.py   # structure + closure rules
python scripts/capture_roi.py               # projection vs measured, labeled
```

## What this layer does not claim

It does not claim any capture **has** amortized (none has: the replay protocol
has not run). It does not claim frontier models are unnecessary — the capture
itself is frontier work; that's the point. And it makes no benchmark claim: the
capability numbers live in the waterline; this ledger only prices the moves
between its cells. The `capture_ledger` primitive in
`data/primitives/axm_primitives.v0.1.json` carries the same guards.
