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

Before fixture interpretation the bridge writes exact prompt and dispatch bytes and
appends `PREPARED` then `DISPATCH_STARTED` to the call journal. The call ID is a
deterministic function of task, arm, ordinal, and incoming state hash. Recovery is
explicit, lock-serialized, and split at that provider boundary:

- no journal or `PREPARED` alone, with no provider/session evidence, is provably
  pre-dispatch; exact bytes are write-ahead logged, archived, and the ordinal may
  be attempted once again;
- `EVIDENCE_SEALED` permits replay of the already sealed call and acceptance into
  the append-only state log without another provider call; and
- `DISPATCH_STARTED` without `EVIDENCE_SEALED`, malformed journal custody, or
  provider evidence on a claimed pre-dispatch call is permanently fail-stopped as
  `AMBIGUOUS_DISPATCH`. The arm worktree is removed and redispatch is forbidden.

The hash-chained recovery ledger is write-ahead: a second crash after the event
but before its archive/state mutation deterministically completes the same action
instead of appending a second story. A leftover drive lock may be cleared only by
the explicit recovery entrypoint, only when its exact bridge identity and
timestamp validate, and only when its recorded PID is no longer alive.

The manifest argv is not read or executed anywhere in the fixture path. The
fixture entrypoint accepts only a canonical data array of scripted responses,
interprets it in-process under one code-owned simulator identity, and stamps
`execution_mode: fixture` on its distinct dispatch, provider, acceptance, and
bridge receipt schemas. ADMIN explicitly rejects those descriptors. This tests
transaction mechanics without granting arbitrary manifest command text process
authority or allowing fixture bytes to resemble admissible pilot evidence. The
canonical script hash is preserved in dispatch and bridge receipts. Exact
pre-read provider prompt identity remains unresolved for a real shim.

## Evidence derived by the bridge

The in-process simulator preserves a `tier-backend-result@1` provider result, an exact
`pilot_output` envelope, and at least one hash-bound `provider_raw` artifact.
The raw fixture artifact must deterministically open that exact output.
The bridge—not fixture response data—derives the canonical full-index patch, candidate
tree digest, call receipt, and immutable acceptance receipt. Acceptance keeps
raw stdout, stderr, report, and before/after candidate snapshots. A temporary
Git index derives the tree without changing the persistent arm lineage. Ignored
files inside scope are refused before dispatch and after packet sync because the
patch contract cannot seal them.

A completed non-driver call must leave a non-empty cumulative candidate patch.
A repair that exactly restores the frozen base therefore fails closed instead of
sealing an empty candidate; this is an intentional custody refusal, not an
infrastructure retry signal.

Every fixture model-call and acceptance transition is appended to `state.jsonl`
and immediately replayed. Arm C may pause only on one canonical bounded JSON
question with an enumerated category and no candidate edit. Resume or decline
requires exactly one globally closed `clarification` interval matching task,
Arm C, and the sealed question ID. The bridge derives the UUID from that ledger;
the caller cannot supply one. The answer timestamp is the validated stop-event
timestamp, so the final receipt proves `asked <= start <= answered <= stop`.
Resume then uses a fresh `hands_resume` provider session; decline appends one
terminal `FAILED` transition and dispatches nothing.

Question receipts are durable standalone artifacts and bridge receipt v2 binds
them together with the optional recovery ledger. Missing receipt material after
a state-append crash can be reconstructed only from the exact replayed state and
is itself recorded as a recovery action.

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

1. implement and review the production bridge as the sole caller which re-loads
   the official activation for every fresh or resumed session; this fixture PR
   deliberately leaves `start_pilot_arm()` inert;
2. freeze backend, prompt, source/schema, and tool-version bytes in one operator-
   ratified activation instance;
3. separately authorize and pass the manifest-bound synthetic live canary; and
4. freeze the ten-task plan and audit material, then obtain separate execution
   authority.

Until all four land, the production entrypoint refuses before subprocess
dispatch. The fixture recovery consumer proves the transaction classification;
it does not turn fixture evidence into production evidence or authorize a live
retry. The fixture transaction contract is machinery under test, not a
production bridge, runnable pilot, or evidence about any model.
