# Tier pilot bridge — activation-blocked coordinator

This module connects the merged three-arm composition state machine to the
existing argv/result adapter boundary. It is deliberately **not a live pilot
entrypoint**. `start_pilot_arm()` always refuses because no ratified activation
schema currently binds a code-owned adapter implementation to frozen backend
bytes. Deterministic tests use the explicitly named fixture-only entrypoints;
they cannot authorize a backend, disclose a task, run a canary, grade an output,
or mint a verdict.

## Transaction and isolation contract

One arm owns one detached target-repository worktree for its whole lineage. A
fresh Git-free packet is snapshotted from that worktree for each call and removed
afterward; the next packet advances from the sealed candidate left by the prior
call. No packet or worktree crosses arms. Each call must report a fresh provider
session, registered in the separate control/evidence repository's global session
registry.

Before adapter invocation the bridge writes exact prompt and dispatch bytes and
appends `PREPARED` then `DISPATCH_STARTED` to the call journal. The call ID is a
deterministic function of task, arm, ordinal, and incoming state hash. If the
process dies after dispatch becomes ambiguous, the existing call directory and
journal block redispatch; repair requires explicit future adjudication, never an
automatic retry.

The manifest argv is not executed by the public production entrypoint. Tests
inject a fixture executor into `start_fixture_pilot_arm()` and
`answer_and_resume_fixture_pilot_arm()`. This exercises argv expansion and the
adapter result interface without turning arbitrary committed command text into
host execution authority.

## Evidence derived by the bridge

The adapter preserves a `tier-backend-result@1` provider result, an exact
`pilot_output` envelope, and at least one hash-bound `provider_raw` artifact.
The bridge—not the adapter—derives the canonical full-index patch, candidate
tree digest, call receipt, and immutable acceptance receipt. Acceptance keeps
raw stdout, stderr, report, and before/after candidate snapshots. A temporary
Git index derives the tree without changing the persistent arm lineage.

Every model-call, operator-answer/decline, and acceptance transition is appended
to `state.jsonl` and immediately replayed. Arm C may pause only on an exact
`{outcome: question, text}` provider envelope that made no candidate edit; resume
requires the active question ID, a UUID intervention ID, and a sealed answer.
ADMIN still owns the global non-overlapping intervention log and verifies that
the question receipt's intervention ID closes exactly one operator interval.

Provider and acceptance descriptors are not decorative bridge output. ADMIN now
requires `provider_receipts` and `acceptance_receipts` on every arm run, opens the
provider result and raw artifacts, binds the provider ledger call to the sealed
call receipt, reopens the exact acceptance receipt, and checks stdout/stderr,
report, and unchanged before/after candidate bytes.

Bridge receipts keep the no-verdict boundary explicit:

- `scientific_verdict_minted: false`
- `equivalence_claim_permitted: false`
- `noninferiority_claim_permitted: false`

## Remaining activation gates

These are intentionally unresolved and fail closed:

1. adopt an activation schema/receipt that binds the exact composition manifest,
   code-owned adapter identity and source hash, adapter help surface, and control
   repository custody;
2. implement and review a real adapter shim that emits the exact pilot output
   envelope and preserves binary provider bytes for every stage;
3. freeze backend, prompt, and tool-version bytes and pass a manifest-bound live
   activation canary;
4. freeze the ten-task plan and audit material, then obtain operator ratification
   and separate execution authority.

Until all four land, the production entrypoint refuses before subprocess
dispatch. The bridge implementation is machinery under test, not a runnable
pilot and not evidence about any model.
