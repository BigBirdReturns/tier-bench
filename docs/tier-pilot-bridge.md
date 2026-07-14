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

The manifest argv is not executed by the public production entrypoint. The
fixture entrypoint uses one code-owned subprocess executor identity and stamps
`execution_mode: fixture` on its distinct dispatch, provider, acceptance, and
bridge receipt schemas. ADMIN explicitly rejects those descriptors. This tests
transaction mechanics without allowing fixture bytes to resemble admissible
pilot evidence. Exact pre-read provider prompt identity remains unresolved for
a real shim; a post-execution equality check is not claimed as a TOCTOU proof.

## Evidence derived by the bridge

The fixture adapter preserves a `tier-backend-result@1` provider result, an exact
`pilot_output` envelope, and at least one hash-bound `provider_raw` artifact.
The raw fixture artifact must deterministically open that exact output.
The bridge—not the adapter—derives the canonical full-index patch, candidate
tree digest, call receipt, and immutable acceptance receipt. Acceptance keeps
raw stdout, stderr, report, and before/after candidate snapshots. A temporary
Git index derives the tree without changing the persistent arm lineage. Ignored
files inside scope are refused before dispatch and after packet sync because the
patch contract cannot seal them.

Every fixture model-call and acceptance transition is appended to `state.jsonl`
and immediately replayed. Arm C may pause only on one canonical bounded JSON
question with an enumerated category and no candidate edit. Fixture resume and
decline both refuse: a freehand answer and UUID are not global intervention
authority. Resume remains unimplemented until the bridge can open a canonical
closed clarification interval owned by ADMIN.

Fixture provider and acceptance descriptors are transaction-test artifacts only
and are ADMIN-inadmissible. The future production format must open an exact,
duplicate-free provider artifact sequence and distinct before/after acceptance
snapshots. Acceptance reports already carry bounded stdout/stderr content plus
full byte counts, truncation flags, and hashes so a repair prompt sees the
failure rather than hashes alone.

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
dispatch. The journal is hash/sequence/transition validated, but ambiguous
calls are fail-stopped: no recovery consumer or idempotent redispatch is claimed.
The fixture transaction contract is machinery under test, not a production
bridge, runnable pilot, or evidence about any model.
