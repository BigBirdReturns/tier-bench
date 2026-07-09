# Burden discipline — closure packets before closure claims

This is the prosecutor-readable bridge for AXM.

AXM is not asking whether there is information in the file. It is asking whether
that file satisfies the burden for the action someone wants to take. Any system
that says **approved**, **verified**, **closed**, **safe**, **paid**, **accepted**,
**authorized**, **routed**, or **ready** is making a closure claim. If the burden
is unnamed, the verifier is incomplete. If the failure default is unnamed, the
system will invent one.

## The rule

No file closes merely because some evidence exists.

For every requested outcome, the packet must identify:

1. **Requested outcome** — the claim, payment, acceptance, action, route, or
   closure someone wants.
2. **Claimant** — who is asking the system to treat the outcome as closed.
3. **Authority** — the rule, contract, benchmark, source, reviewer, court,
   commander, or system gate allowed to close it.
4. **Predicates** — the elements that must be satisfied before closure.
5. **Burden holder** — who must prove the predicates or cure the missing
   foundation.
6. **Evidence** — the source rows, records, tests, receipts, artifacts, or
   testimony offered to satisfy the burden.
7. **Verifier** — who or what decides whether the evidence satisfies the burden.
8. **Gap** — what remains missing, disputed, contaminated, partial, or
   unmeasured.
9. **Closure decision** — accepted, rejected, held, escalated, disputed, sealed,
   routed, or left open.
10. **Failure default** — what happens if the burden is not met.

A missing failure default is itself a defect. Defaults must be explicit:
`reject`, `hold`, `deny`, `dispute`, `escalate`, `require_cure`, `keep_open`,
`abort`, `remain_unmeasured`, or another named consequence.

## How this maps to the repo

Tier Bench already practices this discipline under narrower names:

- **Waterline:** a routing cell closes only when the cheapest measured execution
  path clears the hidden grader; unmeasured cells answer `unmeasured`, never a
  guess.
- **Hidden grading:** capability evidence closes only when the deciding tests were
  never visible to the solver.
- **Provenance:** a primitive closes only with `source_basis`, `derived_claim`,
  `not_source_claim`, `verifier`, and `failure_mode`.
- **Control results:** a disposition score remains `single-source` until the
  evidence class and grader rules support stronger closure.
- **Adaptive harness:** models may adapt solve strategy, but grader/pass/cost
  changes are gated for human review; the subject cannot close its own file.
- **Capture ledger:** expensive cognition is not proven reusable until the ledger
  shows what was captured, what it cost, what replay evidence exists, and whether
  it has amortized.

The burden packet is the common shape behind all of these.

## Firehose meaning

In this repo, **firehose** means dense, demarcated execution — not uncontrolled
frontier spend.

The operator should be able to hand the repo to another model and see exactly
which model/effort tier owns which work:

| Work shape | Default lane | Closure burden |
|---|---|---|
| Mechanical edits, JSON plumbing, validators, CI wiring, docs copyedits | Cheap floor / hands | Tests, schema checks, compile, diff review |
| Hidden-graded settled cells | No model spend | Existing waterline evidence; do not re-derive |
| Mixed cheap-floor result (`unstable`) | More cheap trials / edge-family probe | K evidence that distinguishes noise from residue |
| Reproducible wall (`0/K`) | Next effort rung, bottom-up | `0/K` at current rung and `K/K` at next rung |
| Schema semantics, evidence-class adjudication, invariant freezing, oracle design | Driver / Fable-class judgment | Reviewed burden packet plus tests/CI |
| Fable effort gradient (`low → medium → high → xhigh → ultracode/max`) | Sparse, bottom-up, only on residual | Each rung earns the next by evidence; never jump for vibes |
| Access escalation / billing rung | Human gate | Decision packet showing unmapped residual that cannot fit quota |

The gradient between Fable low and ultracode/max is valuable data, but only when
it is walked bottom-up on residual work. A max-effort pass without lower-rung
receipts maps a ceiling, not the frontier. The repo wants the cheapest sufficient
rung for each closure claim.

## PR checklist

Every roadmap PR that introduces a new validator, ledger, result class, shard, or
authorization path should include a burden note answering:

```text
requested_outcome:
claimant:
authority:
predicates:
burden_holder:
evidence:
verifier:
gap:
closure_decision:
failure_default:
```

If a field cannot be answered yet, the closure status is `proposal`, `partial`,
`unmeasured`, `captured_not_yet_amortized`, or another explicit non-closed state.
