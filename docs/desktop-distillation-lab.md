# Desktop Distillation Lab

The Desktop Distillation Lab turns a bounded frontier-model separation into an acquisition program for a local model, source scaffold, verifier, context compiler, routing rule, adapter, or weight delta.

The lab does not claim to recover proprietary weights. A closed service exposes behavior under controlled inputs. An open-weight or source-visible system exposes both behavior and a manipulable candidate mechanism. The acquisition target is the recurring behavior that survives external grading and remains absent from the current local route.

## Input contract

A candidate must preserve:

- the exact task fingerprint;
- the source packet hash;
- the external grader hash;
- the teacher pass receipt;
- the lower-route receipt;
- the teacher’s source-access class;
- recurrence and operator-attention estimates;
- proposed capture cost.

A lower route may be:

| Outcome | Lab treatment |
|---|---|
| `wall` | Decisive residue candidate. |
| `unstable` | Hypothesis worth minimizing and testing, without claiming a wall. |
| `transport_error` | Blocked. Adapter failure is not model capability evidence. |
| `unmeasured` | Blocked. A teacher pass alone does not establish residue. |

## Two acquisition lanes

### Behavioral lane

API-only and subscription-only teachers enter the behavioral lane. Permitted artifact classes include:

- prompt scaffold;
- context compiler;
- routing rule;
- verifier;
- tool policy;
- curriculum;
- inference policy that does not depend on proprietary internals.

The lab removes LoRA, adapter, and weight-delta proposals from a behavioral candidate. A closed-model output can supervise examples and expose a successful procedure. It cannot authorize a claim that proprietary parameters were recovered.

### Mechanistic lane

Open weights, runtime source, or both enter the mechanistic lane. The lab may test:

- inference policies;
- architecture or routing ablations;
- adapters and LoRA;
- weight deltas;
- quantization changes;
- context and cache policies;
- source-level tool orchestration;
- curricula derived from accepted teacher and failure traces.

Mechanistic access still does not establish why the teacher succeeded. The same hidden grader and distinct replay requirement apply.

## Acquisition sequence

Every planned candidate receives six dependency-bound work orders.

```text
minimize
  remove irrelevant context and ceremony while preserving separation
        |
        v
freeze
  bind source, receipts, model identities, and grader
        |
        v
variants
  author distinct withheld tasks before artifact training
        |
        v
capture
  build reusable source or weight artifact
        |
        v
replay
  run student + artifact without teacher access
        |
        v
promote
  admit through the capture ledger or preserve the open gap
```

The original task cannot prove amortization by being replayed against itself. Promotion requires distinct hidden-graded work items.

## Attention-first economics

The queue is ordered by projected monthly operator-attention savings, then by projected monthly frontier-cost savings, then by recurrence. Wall-clock time is not the primary ranking variable.

The lab calculates:

```text
cost savings per job
  = teacher recurring cost - student recurring cost

attention savings per job
  = teacher operator minutes - student operator minutes

cost break-even jobs
  = capture cost / cost savings per job

attention break-even jobs
  = capture operator minutes / attention savings per job
```

These are projections until replay receipts exist. Closure remains in the capture ledger, which validates artifact bytes and independent replays.

## Operation

Validate the example lab:

```console
tierdistill validate ^
  --lab experiments\sovereign_desktop\distillation_lab.json
```

Compile and verify the acquisition plan:

```console
tierdistill plan ^
  --lab experiments\sovereign_desktop\distillation_lab.json ^
  --out .git\tier-plane\distillation-plan.json

tierdistill verify ^
  --lab experiments\sovereign_desktop\distillation_lab.json ^
  --plan .git\tier-plane\distillation-plan.json
```

Emit stage work orders:

```console
tierdistill work-orders ^
  --lab experiments\sovereign_desktop\distillation_lab.json ^
  --out .git\tier-plane\distillation-work-orders.json
```

The example contains:

1. a closed Fable autonomous-recovery residue, routed behaviorally;
2. an open K3 context-routing residue, routed mechanistically;
3. an adapter transport error, blocked from capability capture.

## Relationship to the other instruments

```text
Model Waterline Observatory
  identifies where the expensive route still clears

Frontier Residue Refinery
  preserves the exact lower failures and higher success

Desktop Distillation Lab
  converts the bounded separation into acquisition work

Capture ledger
  closes only after artifact bytes and distinct replay receipts exist

Sovereign Desktop Execution Plane
  routes future work through the promoted local capability
```

This sequence prevents model preference, vendor marketing, and one impressive answer from becoming a routing rule.

## Hardware roles

The 3090 is the primary mechanistic lab surface for models and adapters that fit locally. It can run the student, generate training examples, evaluate LoRA or adapter candidates, and perform replay work.

The 4060 supports lower-cost preparation:

- extraction;
- embedding;
- reranking;
- variant generation;
- data cleaning;
- visual classification;
- grader-side utility work when the grader remains independent of the solver.

CPU, RAM, and NVMe hold the immutable acquisition packet, datasets, indexes, checkpoints, and cache artifacts. Remote open-weight compute is a temporary extension of the mechanistic lane when the donor model does not fit locally. Closed frontier calls remain teacher observations.

## Failure defaults

The lab remains open when:

- the lower route was never measured;
- the failure was transport-related;
- the grader changed during minimization;
- hidden keys leaked into the artifact;
- runtime identity is missing;
- replay work is not distinct;
- the student still requires the teacher during replay;
- cost or attention savings are projected but unreceipted.

The control question is whether a fresh work item can now clear through the student and captured artifact while the teacher is unavailable.
