# Driver-boundary pilot administration — GATED proposal

Status: **proposal only; no task list, audit key, dispatch, result, or verdict
exists.** These validators implement the deterministic administration implied by
`docs/driver-boundary-pilot.md` without selecting work or invoking a backend.
The schemas and closure rules change what can count as a valid pilot, so operator
ratification and cross-lineage review are required before task disclosure.

## What this layer freezes

An exact `tier-bench/tier-pilot-plan@1` contains exactly ten unique tasks. Each
task binds the requested change, base commit, writable packet scopes, immutable
acceptance command, and a commitment to the withheld audit. The plan also binds
the backend-manifest hash, one canonical intervention-log path, the 14-day
follow-up rule, and a commitment to the audit-label seed.

The schedule is derived, never hand-entered:

1. sort the ten task IDs lexicographically;
2. tasks 1–9 receive `ABC`, `BCA`, `CAB` in three cycles;
3. task 10 uses the protocol's SHA-256 modulo-six rule.

### Residual-order ambiguity and proposed closure

Protocol v1.3 says “the six permutations” but does not enumerate them. A modulo
index has no meaning without that order. This implementation proposes and pins
the lexicographic enumeration:

```text
[ABC, ACB, BAC, BCA, CAB, CBA]
```

The plan must carry that exact array; the schema and executable validator reject
its absence or any alternate ordering. **This enumeration is not adopted law
until the operator ratifies it before task disclosure.** No implementation may
quietly substitute a language-library permutation order.

Every scheduled row repeats the task's base commit. The validator re-derives all
30 rows and therefore proves identical task bytes across the three arms,
counterbalancing, and zero schedule discretion.

## Evidence and atomic failure defaults

`tier-bench/tier-pilot-evidence@1` binds the exact plan bytes and backend
manifest. Every unvoided task must have exactly one sealed run for each of
`arm_a`, `arm_b`, and `arm_c`. Each arm ledger is checked bidirectionally against
its dispatch receipts; every call binds the frozen backend-manifest hash and its
task/arm coordinate. A dispatch may appear once globally. Real-billed rows must
reconcile by account; subscription-derived and shadow-estimated rows use the same
receipt-completeness check but never pretend a provider bill exists.

There is no arm-level void. A protocol fault creates one task-level void, and
the task disappears from the completion numerator for all arms. The frozen plan
still contains ten tasks: voided tasks are reported and cannot be replaced.
Any arm marked protocol-invalid without a matching whole-task void refuses
closeout.

The intervention artifact must live at the plan's one canonical path. Its
append-only hash chain must validate, be globally closed, and contain only the
frozen task/arm coordinates. The evidence record binds both whole-file SHA-256
and final event-chain head.

## Opaque audit and follow-up

Before disclosure, the plan carries `sha256(seed)` for a withheld 32-byte audit
label seed. At closeout the seed is revealed and each label is re-derived as:

```text
audit- + first20hex(HMAC-SHA256(seed, pilot_id NUL task_id NUL arm))
```

Each task's three audit scores are canonicalized in opaque-label order and
hash-sealed before the arm mapping is revealed. The validator refuses an early
reveal, a mapping that does not open the commitment, or scores sealed before the
fixed follow-up deadline. `followup_closes_at` must be exactly 14 days after the
last arm seal. The score includes repository CI, scope compliance, operator
acceptance, and escaped-defect count.

The audit evidence must also reveal the exact withheld-audit artifact whose
SHA-256 was committed in that task's plan row. A score set cannot close against
a decorative hash or a different audit. The evidence additionally carries an
operator-authorization artifact whose payload binds the exact plan bytes,
backend-manifest hash, protocol commit, pilot ID, and ratification timestamp.

The operator's known partial blindness for Arm C remains a protocol caveat; a
cryptographic label cannot erase human memory.

## Fail-closed commands

No command below invokes a model or chooses a task:

```console
tier pilot schedule --plan pilot/plan.json
tier pilot validate --plan pilot/plan.json
tier pilot close --plan pilot/plan.json --evidence pilot/evidence.json \
  --output pilot/closeout.json
```

`schedule` prints the mechanically derived rows. `validate` checks an exact plan.
`close` verifies every artifact before writing; an existing output is never
overwritten. Its receipt is administrative only:

- at least 7 unvoided, fully administered tasks → `ADMINISTRATIVELY_COMPLETE`;
- fewer than 7 → `PARTIAL`, with even a feasibility readout forbidden.

The receipt always says `scientific_verdict_minted: false`,
`equivalence_claim_permitted: false`, and
`noninferiority_claim_permitted: false`. Reaching 7/10 permits only the
registered feasibility readout and a decision about whether a larger comparison
is justified. It does not compare arms or conclude anything about a model.

## Required authority sequence

1. Merge and ratify this proposal, including the residual-order enumeration.
2. Land the separate three-arm driver/hands orchestrator and exact backend
   schema; this administration layer does not make the current one-call runner
   into that orchestrator.
3. Freeze backend and prompt bytes, then pass a manifest-bound activation
   canary before any task disclosure.
4. In a separately claimed driver row, propose ten real tasks and their
   pre-existing executable acceptance; do not invoke subjects.
5. Operator ratifies the exact plan bytes, withheld-audit commitments, and
   execution authority.
6. Claim a separate execution row. Subjects receive one Git-free packet at a
   time and never receive this plan, another task, a peer artifact, repository
   instructions, history, or audit material.

The plan's `files` are writable scopes, not read-only context. Until the runner
gains a distinct read-only context channel, task selection must exclude work
whose semantics depend on ambient repository material outside those scopes.
