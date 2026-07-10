# Residue Broker — ARC-C orchestration benchmark contract

ARC-C asks a narrow question over the real almanac knots: does an orchestration
pattern keep settled work at the measured floor, escalate only after a reproducible
wall, and preserve enough evidence to audit every decision? It is not a demo that
assumes routing is cheaper. The route itself is under test.

`experiments/breadth/residue_broker.py` is the pure policy. It never calls a model
and never grades a candidate. Given sealed receipts, it returns exactly one next
action per task:

- no evidence: route to the cheapest rung;
- fewer than K decisive receipts: collect more at that rung;
- K/K passes: seal there and stop spending;
- mixed pass/fail evidence in the latest K decisive receipts: abstain from a
  conclusion and collect another trial at the same rung;
- 0/K: and only 0/K, permit the next rung;
- a wall at the top available rung: abstain; access escalation is a human gate.

Errors and partial observations remain in the record but never count toward a wall
or clear. The decisive K-window rolls forward, so one noisy miss triggers more
same-rung evidence instead of poisoning the cell forever. A candidate is decisive
only after it was sealed, graded with a manifest-
declared hidden grader, and independently re-run by the coordinator. The solver's
narration is never a verdict.

## Run artifact

`data/orchestration/arc_c_almanac_v1.json` is a sealed single-engine result, not
a cross-engine completion claim. It contains nine decisive floor trials: each of
exception-class, record-binding and rule-boundary has three passing observations
and is sealed at the floor. No task produced a 0/K wall, so no escalation was
authorized or attempted.
`rung_bindings` maps shared rung roles to this engine's actual model, effort and
surface, so Claude and Codex can compare routing decisions without pretending their
model ladders are identical. Trial rows preserve:

- route rationale and the evidence available before dispatch;
- candidate and grader hashes, with the hidden grader absent from the solver packet;
- model, effort, tokens, cost and cost basis (`subscription-derived` for Sol/Codex
subscription runs; desktop-thread trials explicitly mark token telemetry
unavailable rather than presenting zero sentinels as measurements);
- replay source, captured artifact and distinct work-item identity;
- explicit abstention for errors, partials and unstable evidence;
- manifest, prompt and solver-packet provenance.

Validate the contract and all committed receipts with:

```bash
python scripts/validate_orchestration_run.py
python tests/test_residue_broker.py
python tests/test_export_solver_packet.py
python tests/test_grade_solver_packet.py
python tests/test_compare_engine_runs.py
python tests/test_orchestration_clone_integrity.py
```

## Byte-stable evidence

Hash-bound task manifests, fixtures/graders, packet receipts and orchestration
artifacts are marked `-text` in `.gitattributes`. Git must preserve their exact
bytes across Windows and Linux checkouts. Curated orchestration `events.jsonl`
streams are explicitly exempted from the repository's blanket scratch ignore.

`tests/test_orchestration_clone_integrity.py` makes a fresh local clone with
`core.autocrlf=true` and recomputes every path-backed SHA-256 in the run and
packet/grade receipts. CI fails if checkout changes even one sealed byte or if a
referenced receipt artifact was not committed.

## Execution sequence

1. Copy each fixture to an isolated solver directory and remove every manifest-
   declared hidden file before constructing the solver packet.
2. Dispatch only the rung named by the current broker decision. Preserve the raw
   solver response and thread ID before any summary.
3. Seal the candidate and record its SHA-256.
4. In a separate coordinator step, inject the hidden grader and run it. Re-run it
   independently; only that result may become `pass` or `fail`.
5. Append the receipt, recompute broker decisions, validate the whole run, then
   dispatch the next allowed action. Never edit a prior receipt.
6. A sealed engine-run claim requires all three tasks to leave the
   unmeasured/collecting states and the engine burden packet to close. A paired
   ARC-C conclusion additionally requires compatible Claude receipts and the
   comparator; that cross-engine claim remains open.

Recompute the deterministic decision section after appending a receipt:

```bash
python experiments/breadth/residue_broker.py data/orchestration/arc_c_almanac_v1.json --write
python scripts/validate_orchestration_run.py
```

## Closure packet

```text
requested_outcome: Treat an ARC-C run as evidence that the orchestration pattern
  routes real hidden knots at the cheapest measured sufficient rung.
claimant: The ARC-C run coordinator.
authority: Manifest-declared hidden graders plus the floor-first K-of-K policy.
predicates: Every decisive candidate was sealed before grading; hidden graders were
  absent from solver packets; coordinator reruns match; no escalation precedes 0/K;
  spend/replay/provenance is complete; all task decisions are final.
burden_holder: Whoever asserts a routing or cost conclusion from the run.
evidence: The validated run artifact, candidate files, hashes, raw solver records,
  hidden-grader outputs and spend receipts.
verifier: scripts/validate_orchestration_run.py plus the manifest hidden graders.
gap: None for the Codex engine run; compatible peer comparison remains separate.
closure_decision: sealed for this engine run; paired ARC-C conclusion remains open.
failure_default: remain_unmeasured; do not route, escalate, price or claim success.
```
