# Driver-boundary pilot — pre-registered protocol (v1, 2026-07-13)

Status: **REGISTERED, not yet authorized to run.** This document is committed
before any pilot task list exists. Per the adapt.py discipline, changing the
arms, metrics, audit design, or success criteria after task-list disclosure is
a GATED act requiring operator sign-off recorded in the queue.

Registered by the Claude-lane driver from a cross-lineage design exchange
(Sol correction of the Claude draft, 2026-07-13). Both resident frontier
lineages are conflicted parties on the outcome; that is why the protocol is
frozen first.

## What this pilot is and is not

- It is a **feasibility pilot** (n≈10 real tasks): it estimates failure modes,
  variance, and instrumentation gaps. **It cannot establish equivalence or
  non-inferiority at this n, and no such claim may be made from it.** Its
  output is a decision about whether a larger comparison is justified.
- It tests **H-driver-execution** and instruments **H-authority-routing**.
  **H-driver-discovery is NOT tested here** — it needs a separate
  acceptance-authoring task set with a withheld audit (see §Discovery).
  Bundling them would let an easy execution result erase a real discovery
  difference.

## Vehicle

The `tier run` contract (cross-lineage spec, 2026-07-13):

```
tier run --repo <path> --task "specific requested change" \
         --files <scope> --acceptance "<executable command>"
```

Requirements (all arms): immutable executable acceptance supplied by the
operator — the solver never authors its own grader; disposable worktree;
cheapest-rung subscription backend for hands; deterministic acceptance
execution; escalation only after a recorded failure; output is a patch +
receipt, never a silent merge; full telemetry (wall-clock, interventions,
model usage, failures, repairs).

## Arms

Identical starting commits. Isolated worktrees. No cross-arm exposure (an arm
never sees another arm's patch, receipt, questions, or existence). Same cheap
hands in every arm. Same visible task brief and the same acceptance command.

- **Arm A — frontier driver**: frontier model decomposes, coordinates,
  verifies, repairs. **Frontier repair traces are a PRIMARY OUTPUT** (the
  first rows of `driver_traces.jsonl`), not optional logging.
- **Arm B — cheap driver**: same protocol, cheap model in the driver seat.
- **Arm C — no model driver**: cheap executor + deterministic gates;
  unresolved questions route to the operator as concise questions. Operator
  time spent on those questions is COUNTED AT FULL WEIGHT in the primary
  metric — transferring judgment cost to the operator is not a speedup.

## Task selection

Real tasks from the operator's actual repositories, selected by the operator
BEFORE any arm runs and disclosed to arms one at a time. Selection note:
requiring pre-existing executable acceptance PRESELECTS toward tasks where
the driver has little remaining work — this bias is accepted for the pilot
and must be stated in every readout. The separate discovery set (below)
compensates.

## Audit — because deterministic tests only catch anticipated failures

A **withheld final audit** runs after all arms complete, checking MORE than
the visible acceptance: repository CI, diff constraints (scope creep, files
touched outside --files), operator acceptance of the change, and **escaped
defects discovered during a fixed follow-up window** (length set at task-list
creation). The weakest arm must not be able to win by satisfying incomplete
tests. Audit content is withheld from all arms and from both drivers until
every arm has sealed.

## Metrics

**Primary: operator active minutes per accepted change** — including
interruptions, clarification handling, and rescue work.

Secondary: elapsed wall-clock; frontier tokens/$ (real-billed); cheap
tokens/$; escaped defects (from the withheld audit + follow-up window);
failed attempts; clarification count (Arm C's question rate is the
H-authority-routing instrument — viability requires questions to be rare and
decision-needs reliably noticed, both measured here); time-to-merge.

## Discovery (separate, not this pilot)

H-driver-discovery gets its own task set: tasks whose stated acceptance is
DELIBERATELY incomplete (missing invariants planted by the operator or drawn
from real defect history). Frontier review, cheap review, and operator-only
routing each get the same materials; the withheld key scores which missing
invariants each surfaces. Note the standing evidence asymmetry: every
discovery anecdote to date (PR #84/#85/#89 review findings) is from frontier
reviewers, with an empty cheap-review comparison class.

## Failure defaults

Missing telemetry rows, cross-arm exposure, post-hoc metric changes, or an
arm authoring its own acceptance void that task for all arms (never one arm
selectively). A voided pilot reports as PARTIAL — never as evidence for any
hypothesis.
