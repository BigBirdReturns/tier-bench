# Five-arm bake-off on the fnmatch character-class boundary

*Run 2026-07-19 (session on `claude/chatgpt-dag-wiring`). Driver: Claude. Subjects
received identical generated packets through Tier Desk; the driver never edited a
candidate.*

## What was run

One work item, byte-identical across five arms, dispatched through the Tier Desk
API. Only the arm varied.

- **Task**: implement `translate_charclass(pat, i)` in
  `fixtures/t2_ossrf_fnmatch_charclass/input.py` from the normative docstring.
- **Writable scope**: `fixtures/t2_ossrf_fnmatch_charclass/input.py` — the file
  alone. The fixture's `hidden_tests.py` sits in the same directory but outside
  the scope, so it was neither writable by nor visible to the subject (the packet
  contains only in-scope files). Genuine hidden grading.
- **Acceptance**: `tests/fixture_checks/check_t2_ossrf_charclass.py`, outside every
  scope, wrapping the 23-vector hidden grader and echoing its `SCORE` line so
  partial credit survives rejection.
- **Discrimination gate**: the acceptance command was proven to exit non-zero
  against the unpatched fixture (`SCORE 0/23`) before any dispatch.

## Measured results (single trial per arm)

| arm | model | effort | verdict | hidden score | in | out | cache read | latency |
|---|---|---|---|---|---|---|---|---|
| arm_spark | gpt-5.3-codex-spark | low | ACCEPTED | 23/23 | 13168 | 3568 | 4224 | 5.5s |
| arm_luna | gpt-5.6-luna | medium | ACCEPTED | 23/23 | 13781 | 2324 | 8960 | 44.4s |
| arm_terra | gpt-5.6-terra | medium | ACCEPTED | 23/23 | 14970 | 2095 | 9472 | 44.8s |
| arm_a | gpt-5.6-sol | medium | ACCEPTED | 23/23 | 13443 | 1872 | 8960 | 36.9s |
| arm_haiku | claude-haiku-4-5 | low | ACCEPTED | 23/23 | 33 | 22670 | 50909 | 150.0s |
| arm_b | qwen3.5:9b-q4_K_M | deterministic | (see below) | — | — | — | — | — |

**`arm_haiku` is not surface-comparable to the rows above it.** The four GPT arms
ran on `codex_emit`: one blind shot, emit a complete file, no tools, no iteration.
`arm_haiku` ran on `claude_code`, an *agentic* surface with Read/Edit/Write and the
freedom to iterate — which it used, spending 22670 output tokens and 150s against
spark's 3568 and 5.5s. Same verdict, different amount of help. Read it as "this
instrument is clearable on both lineages", never as a model-vs-model ranking.

That gap is itself the routing finding: on this task every arm reached 23/23, so
the discriminator is not capability but consumption. `arm_spark` got there for
~1/6 the output tokens and ~1/27 the wall time of the agentic cheap arm, and the
Claude CLI self-reported $0.173 equivalent for the haiku run against $0 marginal
for the subscription Codex arms.

Zero scope violations on every accepted arm. Receipts under
`.git/tier-runs/monster-wrangler/charclass-arm-*/attempt-001/`. Costs are
subscription-derived, not billed dollars; no dollar figure is claimed.

## What this does and does not establish

**Does**: on this repo's committed hidden vectors for this boundary, four
GPT-lineage arms — including the cheapest one at `low` effort, in 5.5 seconds —
cleared it perfectly, first attempt, no repair round.

**Does not**: this is **not** a sealed measurement and does not refute the
`judgment_residue` row in `experiments/breadth/run/waterline.json`. That row was
measured on a different instrument (task02, hidden 10681-case grading) with
Anthropic-lineage models, where the cheap floor was unstable (haiku 3/5) and the
settled cost was ~6x the floor. This run is n=1 per arm, on a 23-vector grader,
with a different model family. Instruments and lineages both differ.

The honest reading is a **hypothesis for sealed follow-up**: the named residue may
be lineage-specific rather than a universal capability boundary. Testing it
properly needs K=3 replication per arm on a matched instrument, which this run
does not provide and which no verdict here is authorized to assume.

## The finding the cheap arm paid for

`arm_b` did not fail at the task — it exposed a defect in the referee. Its backend
returned a patch normally, then the run stayed `RUNNING` for over ten minutes: the
candidate contained an unbounded loop, the hidden grader never returned, and a
*grandchild* process burned 566 seconds of CPU while the desk's single worker sat
occupied. `tier_runner.core` ran the acceptance command with no timeout, so any
candidate — buggy or hostile — could hold the desk indefinitely, and on Windows the
spinner would have survived a plain child kill.

Fixed in `c970aba`: the acceptance command runs under a 300s cap with whole-tree
termination, and a timeout is recorded **REJECTED**, not ERROR — the candidate's
own code failed to terminate, so it stays in the capability denominator instead of
being excused as infrastructure.

**Evidence status of the fix.** The mechanism is witnessed deterministically by
`tests/test_acceptance_timeout.py` (3/3): a command whose *grandchild* spins is
terminated inside the cap, the tree is reaped, `rc=124` is returned, and ordinary
success and failure codes are unaffected. Regression on the affected surface is
green: tier_runner 24/24, tier_desk 21/21, desk_driver_loop 6/6, ollama_emit PASS.

An **in-situ desk witness is still outstanding**. The replay (`charclass-arm-b-retry`)
did not reach acceptance: the Ollama adapter hit its own 180s request cap and the
run ended `ERROR — backend adapter exited 2`, i.e. a transport skip, not a
capability result or a grader hang. Under burden discipline that replay proves
nothing either way, and the fix's end-to-end behaviour on a live hung candidate
remains unproven by receipt.

Four frontier arms passing cleanly would never have surfaced this. The cheap arm's
failure was the more valuable result.
