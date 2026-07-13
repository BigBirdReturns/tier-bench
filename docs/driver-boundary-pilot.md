# Driver-boundary pilot — pre-registered protocol (v1.2, 2026-07-13)

Status: **REGISTERED, not yet authorized to run.** This document is committed
before any pilot task list exists. Per the adapt.py discipline, changing the
arms, metrics, audit design, or success criteria after task-list disclosure is
a GATED act requiring operator sign-off recorded in the queue.

Registered by the Claude-lane driver from a cross-lineage design exchange
(Sol correction of the Claude draft, 2026-07-13). Both resident frontier
lineages are conflicted parties on the outcome; that is why the protocol is
frozen first.

## What this pilot is and is not

- It is a **feasibility pilot** with **exactly N = 10 tasks**, drawn once by
  the operator and never replaced. Stopping rule (deterministic, no
  discretion): every drawn task runs in all three arms unless VOIDED by the
  failure defaults below; voided tasks are reported, not replaced; if fewer
  than 7 of 10 tasks complete un-voided in all arms, the pilot reports
  PARTIAL and supports no hypothesis movement. There is no early stopping for
  results — only the void rule ends a task early. **N=10 cannot establish
  equivalence or non-inferiority, and no such claim may be made from it.**
  Its output is a decision about whether a larger comparison is justified.
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

## Frozen backend manifest — configuration precedes disclosure

BEFORE task disclosure, a `pilot_backends.json` is committed freezing, per
arm: driver model id + effort + surface, hands model id + effort + surface,
the escalation ladder (if any), and tool version pins. Its sha256 is echoed
in every ledger row's `extra.backend_manifest_sha256`. The runner refuses to
start an arm whose runtime configuration differs from the manifest, and any
per-call row that contradicts the manifest voids the task. Configuration is
therefore an input frozen up front — never an after-the-fact recording.

## Arm order — seeded and counterbalanced

Within a task, arms run sequentially (one operator), so operator familiarity
grows with each pass — a bias that must not correlate with arm. Arm order is
GUARANTEED balanced by construction, not left to hash luck:

1. Sort the 10 disclosed task_ids lexicographically (deterministic given the
   fixed list).
2. Assign orders from the fixed schedule
   `[ABC, BCA, CAB, ABC, BCA, CAB, ABC, BCA, CAB, R]` — three full cycles of a
   3×3 Latin square, so over tasks 1–9 every arm occupies every position
   EXACTLY three times.
3. The 10th (residual) order `R` is drawn from the six permutations by
   `int(sha256(task_id_10 + ":" + protocol_commit).hexdigest(), 16) % 6`,
   where `protocol_commit` is the commit hash of THIS protocol version.

Maximum position imbalance is therefore 1, by construction. Reproducible by
anyone from the task list + this file; zero discretion. The readout still
reports per-position means so the residual single-task imbalance is visible.

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
defects discovered during a fixed follow-up window of exactly 14 days from
the final arm's seal on that task** (fixed here, pre-disclosure; not
adjustable at task-list creation). The weakest arm must not be able to win by satisfying incomplete
tests. Audit content is withheld from all arms and from both drivers until
every arm has sealed.

**Arm blinding of the audit.** Patches are audited as normalized artifacts
under opaque labels: seeded-shuffled identifiers (same seeding scheme as arm
order), diffs stripped of branch names, timestamps, worktree paths, and any
runner metadata before presentation. All audit scores (CI result, diff
constraints, acceptance, escaped defects) are recorded against opaque labels
and SEALED before unblinding. Honest limit, stated up front: the operator
cannot be fully blind to Arm C for tasks where it asked them questions —
blinding is complete between Arms A and B, and partial for C; the readout
must carry this caveat on every C comparison. Neither resident driver
participates in auditing its own pilot's artifacts.

## Metrics

**Primary: operator active minutes per accepted change** — including
interruptions, clarification handling, and rescue work.

**Reproducible accounting (schemas fixed here, pre-disclosure):**

- *Operator time*: an append-only EVENT log — two rows per touch, each
  appended at the moment it occurs (a single row carrying both start and end
  cannot be append-only; it would be written or edited after the fact):
  `{"task_id", "arm", "event": "start"|"stop", "category", "ts"}` with
  category in {brief, clarification, rescue, review, acceptance, other}.
  Intervals are DERIVED by pairing each start with the next stop for the same
  (task_id, arm); active minutes = sum of derived intervals. An unpaired
  start at pilot close, out-of-order timestamps, or any edited row voids the
  task. Untracked operator work discovered later likewise voids it.
- *Model/backend usage*: one row per model call using the EXACT
  `experiments/breadth/ledger.py` `Call` dataclass fields: `ts`, `account`,
  `model`, `tier`, `task_id`, `phase`, `outcome`, `effort`, `input_tokens`,
  `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`,
  `latency_ms`, `trial`, `note`, `extra`. Pilot conventions: `phase` carries
  the arm (`arm_a`|`arm_b`|`arm_c`); `extra` carries
  `{"backend_surface": <subscription-cli|api|agent-tool>,
  "runtime_model_id": <exact id>, "backend_manifest_sha256": <hash>}`;
  `cost_usd` is real-billed where the surface reports it and the row's `note`
  says `shadow-estimated` otherwise. Reconciliation (`ledger.reconcile`) runs
  at pilot close; unreconciled books void the affected tasks.

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

Missing telemetry rows, missing/edited intervention-log rows, unreconciled
ledgers, cross-arm exposure, post-hoc metric changes, deviation from the
seeded arm order, unblinded audit scoring, or an arm authoring its own
acceptance void that task for ALL arms (never one arm selectively). Voided
tasks are never replaced. A pilot below the 7-of-10 completion floor reports
as PARTIAL — never as evidence for any hypothesis.

## Change log

- v1.1 (2026-07-13, pre-task-disclosure): fixed exact N and deterministic
  stopping/void rule; seeded counterbalanced arm order; arm-blind audit
  procedure with the honest Arm-C partial-blindness caveat; reproducible
  operator-time and model/backend accounting schemas. Recorded as blockers by
  the Sol lane on draft PR #90 before any task disclosure — pre-disclosure
  amendment is permitted; post-disclosure amendment remains GATED.
- v1.2 (2026-07-13, pre-task-disclosure, Sol re-review round 2): arm order
  now GUARANTEED balanced (3× Latin-square cycles + one seeded residual; max
  position imbalance 1 by construction — v1.1's hash draw was random, not
  counterbalanced); operator-time log corrected to append-only start/stop
  EVENT rows with derived intervals (v1.1's single start+end row was
  internally impossible to append); ledger fields now name the exact Call
  dataclass fields incl. effort/trial/extra (v1.1's list did not match
  ledger.py); backend configuration frozen pre-disclosure in a committed
  pilot_backends.json echoed per-row by hash (v1.1 recorded it after the
  fact); follow-up window fixed at exactly 14 days from final arm seal
  (v1.1 left it discretionary at task-list creation).
