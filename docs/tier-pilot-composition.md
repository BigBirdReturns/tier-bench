# Tier pilot composition contract (proposal-only)

`tier-bench/pilot-backends@2` closes the representational gap between the
registered driver-boundary protocol and the original one-call daily runner.
It is additive: `tier run` and `tier-bench/pilot-backends@1` are unchanged.

This contract is **not pilot execution authority**. No production adapter
bridge exists in this change, no backend choices or prompt bytes are frozen,
and no real task may be disclosed through it. Cross-lineage review and merge
make the instrument available for later activation; they do not launch it.

## What v2 freezes

The manifest contains three exact arms and a reusable backend registry:

- Arm A is `frontier_driver`: a frontier driver plans, identical cheap hands
  implement, the frontier driver gets one failure-triggered repair, and any
  later escalation follows the frozen ordered ladder. Every Arm-A repair
  produces the historical distillation tuple in `driver_traces.jsonl`.
- Arm B is `cheap_driver`: a cheap driver performs the same plan/repair roles,
  the identical hands backend and hands prompt are used, and escalation is
  frozen rather than selected after seeing a failure.
- Arm C is `operator_routed`: it has no driver field and no model escalation.
  The identical cheap hands implement and perform the one repair. A hands
  response explicitly classified as a question pauses the state; only an
  answer bound to that exact question ID permits a fresh hands-resume call.

The loader rejects a missing/extra arm, Arm-C driver substitution, hands drift,
non-cheap hands, driver-tier drift, repair routed to someone other than the
arm's declared driver/hands, a model escalation in Arm C, prompt hash drift,
and more than one repair call. The one-repair limit is deliberate: repeated
repair semantics were not preregistered and cannot be invented in a manifest.

The portable shapes are:

- `schemas/tier_pilot_backend_manifest.schema.json`
- `schemas/tier_pilot_call_receipt.schema.json`
- `schemas/tier_pilot_arm_state.schema.json`
- `schemas/tier_pilot_driver_trace.schema.json`

## Causal prompt binding

Role names are not evidence that one role received another role's work. Before
each model call, `render_next_prompt` deterministically renders the committed
template from the state and the call receipt must echo that rendered prompt's
SHA-256.

Required causal material is stage-specific:

| stage | required committed-template markers beyond the base four |
|---|---|
| driver plan | none |
| hands | `DRIVER_PLAN` (`NO_MODEL_DRIVER` in Arm C) |
| repair / escalation | `CANDIDATE_OUTPUT`, `FAILED_ACCEPTANCE_REPORT` |
| Arm-C resume | `QUESTION`, `ANSWER`, `CANDIDATE_OUTPUT`, `FAILED_ACCEPTANCE_REPORT` |

Every model template also carries `TASK`, `FILES`, `ACCEPTANCE`, and
`BASE_COMMIT`. Missing or unknown uppercase markers fail closed. A later
adapter bridge must dispatch these exact rendered bytes; a paraphrase is not
the same call.

## Per-call evidence and fresh sessions

Each driver, hands, repair, escalation, and resume is one
`tier-bench/pilot-call-receipt@1`. It contains one exact `ledger.Call`, the
frozen backend and prompt-template identity, rendered-prompt hash, output hash,
dispatch hash, and session identity. The composition layer rejects model,
effort, account, tier, surface, cost-basis, tool-version, prompt, dispatch, or
runtime-model drift. It also rejects session reuse within the arm state. The
existing repository-wide session registry remains the cross-task/arm backstop
when the production bridge is implemented.

Output semantics are stage-bound rather than inferred later: driver planning
must emit `plan`, a completed hands/repair/escalation call must expose the
canonical `candidate_patch`, a question must emit `question`, and a failed call
must emit `error`. The future bridge is responsible for deriving the canonical
full-index candidate patch from the packet after each editing call; a friendly
model summary is not candidate evidence.

Call receipts are never collapsed: a frontier plan, cheap-hands attempt, and
frontier repair remain three ledger rows and three session identities.

## Failure routing

The deterministic transitions are:

```text
Arm A/B: driver_plan -> hands -> acceptance
                           fail -> repair -> acceptance
                                           fail -> frozen escalation(s)

Arm C:   hands -> acceptance
          |          fail -> cheap-hands repair -> acceptance
          + question -> WAITING_OPERATOR -> answer -> fresh hands_resume
```

An exhausted route ends `FAILED`; it never silently chooses a stronger model.
An Arm-C question above the frozen limit also fails. Operator decline is a
terminal failure, not an implicit answer. A provider/adapter call error is also
terminal: without a candidate and immutable acceptance failure, escalating it
would silently change the stopping rule rather than repair measured work.

## Driver trace semantics

An Arm-A repair trace preserves:

```text
(task, failed cheap-hands output, failed acceptance report)
    -> (frontier repair output, later repair pass/fail)
```

The `validator_report` is the failure that caused the repair. The subsequent
acceptance result is the separate `passed` field. Substituting the later
"tests passed" report for the causal failed report would destroy the training
example and is regression-tested. Trace rows carry content hashes and a
whole-row hash; append rejects duplicate or tampered existing rows.

## Deliberately unresolved boundary

This proposal stops before production dispatch. The current Claude adapter
emits the original one-call result shape and the current `tier run` owns a
single-call disposable worktree. A later, separately claimed bridge must:

1. keep one scoped packet/worktree across the composed arm without leaking it
   across arms;
2. dispatch the exact rendered prompt bytes and mint one call receipt per
   provider invocation;
3. expose the model's stage output and the candidate patch as sealed causal
   inputs without trusting freehand reconstruction;
4. run immutable acceptance between candidate calls;
5. preserve/resume an Arm-C packet safely across an operator pause; and
6. register sessions globally and append Arm-A traces atomically with the arm
   receipt.

Until that bridge is reviewed, merged, and activated against a frozen backend
manifest, this module proves the composition contract and state transitions —
not that the pilot can run.
