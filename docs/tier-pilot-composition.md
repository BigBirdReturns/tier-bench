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
- `schemas/tier_pilot_acceptance_receipt.schema.json`
- `schemas/tier_pilot_arm_state.schema.json`
- `schemas/tier_pilot_question_receipt.schema.json`
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
runtime-model drift *inside the supplied receipt set*. It also rejects session
reuse within one arm state. These are internal self-consistency checks, not yet
provider provenance: the production bridge must mint dispatch receipts from
actual adapter calls and use the existing repository-wide session registry as
the cross-task/arm backstop.

Output semantics are stage-bound rather than inferred later: driver planning
must emit `plan`, a completed hands/repair/escalation call must expose the
canonical `candidate_patch`, a question must emit `question`, and a failed call
must emit `error`. The future bridge is responsible for deriving the canonical
full-index candidate patch from the packet after each editing call; a friendly
model summary is not candidate evidence.

Call receipts are never collapsed: a frontier plan, cheap-hands attempt, and
frontier repair remain three ledger rows and three session identities.

Immutable acceptance is a separate sealed receipt, never a bare boolean. It
binds the causal call ID, base commit, exact command and hash, candidate patch
and candidate-tree hashes, exit code, pass bit, report, stdout/stderr hashes,
frozen acceptance-tool versions, and a whole-receipt hash. `COMPLETE` is
unreachable without that receipt. A question call records ledger outcome
`partial`, not `pass`; it produced no accepted candidate.

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
Invoking repair consumes the one-call repair budget even when the repair asks
an operator question. Resume cannot create a second repair after that budget is
spent.

## Pause/resume and operator-time custody

Arm state is not an overwriteable JSON snapshot. Every transition carries its
canonical self-hash, monotonically increasing sequence, parent-state hash, and
transition receipt hash. `write_state` appends one complete state to JSONL and
refuses a non-contiguous sequence or parent fork; `read_state` validates every
row, every self-hash, the entire parent chain, and every embedded model-call,
acceptance, and operator-response receipt against the state that preceded it.
This replay prevents a self-consistently rehashed chain from substituting a
different tool, model, candidate, question, or answer. The genesis row is also
canonical: it has no evidence, zero counters, no active question, and one
shared creation/transition timestamp. ADMIN later binds the exact final state
artifact hash in the arm seal, preventing whole-log replacement.

Every answered Arm-C question emits
`tier-bench/tier-pilot-question-receipt@1` with the stable question ID, task,
arm, ADMIN-supplied intervention ID, asked/answered timestamps, and
question/answer hashes. COMPOSE checks the binding shape; ADMIN owns the global
intervention ledger and must prove that intervention ID names exactly one
closed, non-overlapping operator-time interval. An empty intervention ledger
therefore cannot close an arm that has a question receipt.

An operator decline is one directly appendable transition from the waiting
state. It emits the same sealed question receipt with a declined marker and
ends the arm as `FAILED`; it does not manufacture an intermediate answer state
or skip a sequence number.

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
whole-row hash. New rows are replayed against the sealed hands call, failed
acceptance receipt, driver repair call, and post-repair acceptance receipt; a
rehashed but invented failure is refused. Trace custody lives under the pilot
evidence root, never the target repository. The append API requires explicit
target, packet, and worktree exclusions and refuses any evidence root or trace
path beneath them. It reads the full arm-state log itself, requires a terminal
replayed state, derives one task-specific trace filename from the frozen path
and task ID, and requires any preexisting artifact to equal that final state's
sealed traces exactly. A validly self-hashed row from another task therefore
cannot be inherited as historical evidence.

## Bridge status

The separately claimed bridge now implements an explicitly inadmissible fixture
transaction contract. Its production entrypoint remains activation-blocked
because no ratified activation schema yet binds a code-owned real adapter
identity to frozen backend bytes. See
`docs/tier-pilot-bridge.md`.

The bridge machinery:

1. keeps one isolated worktree/advancing packet lineage per arm without leaking
   it across arms, with a fresh provider session per call;
2. dispatches the exact rendered prompt bytes and mints one call receipt per
   provider invocation;
3. exposes stage output and derives the full-index candidate patch as sealed causal
   inputs without trusting freehand reconstruction;
4. runs immutable acceptance between candidate calls;
5. preserves an Arm-C pause from a strict question envelope but refuses resume
   or decline until ADMIN-owned global clarification closure exists; and
6. registers sessions globally and appends Arm-A traces atomically with the arm
   receipt.

Fixture receipts carry distinct schemas and `execution_mode: fixture`; ADMIN
rejects them. Until a separate production bridge is reviewed, merged, and
activated against a frozen backend manifest and code-owned adapter receipt,
these modules test coordination mechanics—not that the pilot can run.
