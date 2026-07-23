# REFUTATION PACKET — kernel-contract cards (tier-bench, 2026-07-19)
# Lane: chat_planner_lane_v1 (role: adversarial reviewer; your output is
# single-source hypothesis-class evidence; a driver adjudicates it; you have
# NO closure authority and this packet grants none.)

TASK: Adversarial refutation of four frozen contract cards, below in full.
Hunt schemes that satisfy the LETTER while violating the INTENT. For each
card find: (a) ways a compliant implementation could still leak authority to
a model, scheduler, or chat surface; (b) ambiguities a hostile implementer
could exploit; (c) missing negative witnesses; (d) fields whose absence from
a schema would let evidence be laundered. Severity-class every finding
P0/P1/P2. Do not propose fixes; refute only. Output: a findings table, then
per-card detail. These cards will govern real evidence custody — assume an
adversary implements them.

Context you may rely on: repo constitution = deterministic referees are the
only pass criterion; scheduler state never outranks a receipt; the operator
gates merges/dispatches; chat surfaces propose, drivers adjudicate, referees
decide. The four cards follow, byte-for-byte.

=============== CARD: policy_kernel_contract_v1 ===============
# 010.100 Task — policy_kernel_contract_v1

**Status: CONTRACT FROZEN 2026-07-19 (operator decision, this card). Schema /
validator / fixture implementation is a cheap-hand job; ANY kernel
implementation beyond the validator is BLOCKED until the
gastown_tier_run_smoke_v1 receipt exists.**

## What the policy kernel IS

A **pure decision function**. The host (operator, drainer, Desk client)
provides four sealed inputs; the kernel returns exactly one hash-bound
routing decision. It never invokes a model, never inspects or holds
credentials, never modifies scheduler state, never executes acceptance.

Inputs: task envelope, cartridge manifest, tank snapshot, evidence index.
Output: one decision object binding, at minimum:

    schema
    decision_id
    task_envelope_sha256
    cartridge_manifest_sha256
    tank_snapshot_sha256
    evidence_refs
    selected_cartridge
    capability_basis        # measured | hypothesis | unmeasured
    quota_basis             # observed | derived | declared | unknown
    route_reason
    fallback_order
    operator_gate
    observed_at
    snapshot_max_age

## Frozen invariants (the acceptance predicates, verbatim authority)

1. **Determinism**: identical inputs → byte-identical decision (modulo
   decision_id, which must derive from input hashes, not clock/random).
2. **Fail closed on missing evidence**: absent evidence index entry for the
   selected cartridge at the task's tier → the kernel may not emit
   `capability_basis: measured`; if no admissible basis exists, it refuses.
3. **Hypotheses cannot serialize as measurements**: no code path may emit
   `measured` from a hypothesis or unmeasured input. Negative witness required.
4. **Staleness stays labeled**: a tank snapshot older than `snapshot_max_age`
   may support an explicitly ADVISORY decision; it may never be represented
   as current headroom. Negative witness required.
5. **No credentials anywhere**: schema-level rejection of any field carrying
   key/token/credential material; validator scans all string values.
6. **No process spawning**: the policy command cannot spawn an adapter or
   model process. Witness: run under a spawn-intercepting harness; any
   subprocess/exec attempt = FAIL.

The initial router need not solve every economic policy. It only needs to
preserve the evidence distinction and emit a decision another system can
execute.

## Design decisions frozen by cross-session review (2026-07-19)

- **Capability source**: the kernel reads `models.json` tier_ceilings — which
  are hypothesis-class today. The first kernel therefore emits almost
  entirely `capability_basis: hypothesis` decisions, and the contract makes
  that look NORMAL, not shameful. `measured` arrives only as waterline
  evidence accumulates.
- **Fail-closed shape**: refusal is a `NO_DECISION` terminal object carrying
  its reason — refusals are receipts too (use-all-the-buffalo), never a bare
  nonzero exit.
- **Determinism mechanics**: `observed_at` is isolated in one detachable
  field so the determinism predicate is byte-identity of the remainder;
  `decision_id` derives from input hashes, never clock or random.

## Bounds

Hand may build: JSON Schema, fail-closed validator, fixtures (one valid
decision, one per negative witness), tests. Hand may NOT build: routing
logic, adapters, any model invocation. Referee: validator green on fixtures,
all six invariants witnessed, zero model calls.

=============== CARD: referee_kernel_contract_v1 ===============
# 010.100 Task — referee_kernel_contract_v1

**Status: CONTRACT FROZEN 2026-07-19 (operator decision, this card). This
card FORMALIZES existing `tier run` behavior as a stable published contract —
it creates NO second execution system and does NOT broaden `tier run` into an
orchestrator. Implementation beyond contract doc + negative witnesses is
BLOCKED until the gastown_tier_run_smoke_v1 receipt exists.**

## The contract (published semantics any host can call)

Before dispatch the operator freezes: base commit, allowed scope, task bytes,
acceptance command. The host invokes a cartridge and returns a candidate. The
referee evaluates the candidate OUTSIDE the authoring model and emits exactly
one terminal class: `ACCEPTED` | `REJECTED` | `ERROR`.

Guarantees retained from the merged `tier run` (these are the contract, not
aspirations — each already implemented, now published):

- The operator checkout remains untouched.
- The candidate sees a restricted packet (declared scope only).
- The acceptance command cannot silently author the result.
- The emitted patch represents the exact candidate tree tested.
- Missing telemetry, out-of-scope writes, manifest drift, mutable
  acceptance, failed cleanup, or reused sessions CANNOT produce `ACCEPTED`.

## Frozen acceptance: negative witnesses (each must terminate with a
## specific machine-readable reason, never an undifferentiated exit code)

Reason codes are a CLOSED enum frozen in the schema — "specific
machine-readable reason" is only a guarantee if the vocabulary is closed.
Base implementation already exists (`tier_runner/core.py` +
`schemas/tier_run_receipt.schema.json`): this card is formalization plus the
witness suite, not construction.

1. Acceptance-command mutation between freeze and evaluation → refusal.
2. Scope escape (write outside declared files) → refusal.
3. Changed base bytes (repo drifted from frozen commit) → refusal.
4. Empty patch presented as success → not `ACCEPTED`.
5. Failed acceptance → `REJECTED` with the acceptance output preserved.
6. Candidate modified BY the verifier → refusal (verifier is read-only).
7. Deliberately corrupted receipt → `tier verify` refusal naming the binding.

## Bounds

Hand may build: the contract document (docs/), machine-readable failure-class
enum, the seven negative-witness fixtures/tests against the existing
`tier_runner` (zero model calls — fixture mode only). Hand may NOT: modify
`tier_runner` production behavior, add orchestration, touch pilot machinery
(all TIER-PILOT gates remain exactly as merged). Referee: 7/7 negative
witnesses produce their specific reasons; existing runner test suites stay
green; zero model calls.

=============== CARD: work_receipt_contract_v1 ===============
# 010.100 Task — work_receipt_contract_v1

**Status: CONTRACT FROZEN 2026-07-19 (operator decision, this card).
Converts the human 700.100 convention into a portable machine contract.
Implementation beyond schema + validator + fixtures is BLOCKED until the
gastown_tier_run_smoke_v1 receipt exists.**

**Not green-field**: `schemas/tier_run_receipt.schema.json` and
`schemas/tier_run_backend_manifest.schema.json` already exist and are the
base. This contract is a superset/wrapper adding the decision binding
(`decision_receipt_sha256`), successor effects (`unlocks`/`blocks`), and
`external_refs`.

## What a work receipt binds

The decision that authorized an attempt, the exact task and repository
state, the cartridge execution evidence, the candidate patch, the frozen
referee, and the resulting state transition. Minimum fields:

    schema
    task_id
    attempt_id
    predecessor_receipts
    decision_receipt_sha256
    task_envelope_sha256
    base_commit
    scope
    cartridge_manifest_sha256
    runtime_evidence
    patch_sha256
    referee_spec_sha256
    referee_result
    terminal_state
    unlocks
    blocks
    external_refs
    created_at

## Frozen authority structure (the split-brain prohibition)

- Committed task envelopes and kernel receipts are AUTHORITATIVE for work
  definition and evidence.
- Beads (or any scheduler) is a REBUILDABLE SCHEDULING PROJECTION.
- A task envelope may be exported into a Bead; a terminal kernel receipt may
  REQUEST a Bead transition; a Bead identifier may appear in `external_refs`.
- `external_refs` (Bead ID, Gas Town rig, worker identity, Agent Deck
  session) are DESCRIPTIVE. They never acquire authority over the verdict.
- Scheduler state may NEVER rewrite the specification, acceptance predicate,
  evidence classification, or terminal verdict.
- `unlocks`/`blocks` express logical successor effects. The receipt kernel
  does NOT call Beads or Gas Town; a host adapter reads the VERIFIED receipt
  and projects effects into its scheduler. (Replace Beads tomorrow without
  rewriting historical evidence.)

## Frozen acceptance: the validator must REJECT

1. An orphaned decision (receipt citing no known decision hash).
2. Missing content binding (any *_sha256 absent or unverifiable).
3. Contradictory terminal states in one receipt.
4. Duplicate terminal receipts for one attempt_id.
5. Nonexistent predecessor references — with this frozen scoping: receipts
   form a DAG and the validator checks hash-linkage against ONLY the
   receipts presented to it; an unpresented predecessor degrades to a
   labeled `UNVERIFIED_PREDECESSOR`, never a silent pass and never a
   requirement for a central store (a global-history assumption is exactly
   what this contract exists to avoid).
6. Malformed scheduler effects (unlocks/blocks not resolvable to task_ids).
7. Any external system claiming to override the referee verdict (an
   external_ref carrying a verdict field = rejection).

## Bounds

Hand may build: JSON Schema, fail-closed validator, fixtures (one valid
chain of two receipts + one fixture per rejection class), tests. Hand may
NOT: build scheduler adapters or touch Beads/Gas Town. Referee: validator
green on valid fixtures, 7/7 rejections fire with named reasons, zero model
calls.

=============== CARD: gastown_tier_run_smoke_v1 ===============
# 010.100 Task — gastown_tier_run_smoke_v1

**Status: PROTOCOL FROZEN 2026-07-19. Operator has authorized exactly ONE
live model dispatch (phase 2). The claim "Gas Town worker-command = tier run"
is a HYPOTHESIS this smoke tests — not an assumption it builds on. No
compensating platform development is authorized by any outcome of this
experiment.**

## Pinned before the live call (record exact values in the receipt)

tier-bench commit, `gt` version, `bd` version, model CLI version + hash,
adapter version, custom Gas Town preset bytes (sha256), task envelope bytes
(sha256), acceptance command bytes (sha256).

## Integration seam (frozen)

Target Gas Town's documented NON-INTERACTIVE preset / formula seam via its
public boundary ONLY: the `gt` CLI, environment variables, and
`settings/agents.json`. `tier run` is a one-shot patch runner, not a
conversational agent — do NOT assume a long-lived worker session can host
it. If the installed Gas Town version cannot supply the fixed arguments and
dynamic task field without substantive wrapper logic, that is a USEFUL
TRANSPORT FAILURE — seal it; it is not permission to build a custom worker
framework. No coupling to Gas Town internal Go structures.

## Phase 1 — provider-free command transport ($0, run first, gate for phase 2)

A local argument-capture fixture receives the Gas Town-generated invocation
and proves: task text, repository path, file scope, and acceptance command
reach the intended `tier run` flags without shell reinterpretation or
dropped fields. Phase 2 is forbidden until phase 1 passes.

## Phase 2 — ONE live subscription-backed T1 invocation

TRUE T1 per the repo's own tier table: ONE tightly-scoped file, simple
change, deterministic acceptance. (Multi-file is T2; a later multi-file
smoke is recorded honestly as T2 — not tonight.) Frozen task selection:
`fixtures/t1_impl_from_docstring/` — already manifest-bound, single file,
deterministic acceptance. Against a disposable clone or pinned test
repository. The provider-free NEGATIVE run executes BEFORE the live call —
if rejection semantics are broken, no subscription token is spent finding
out. `tier run` emits patch + receipts; `tier verify`
reopens bindings; the operator checkout stays unchanged.

## Pass requires ALL NINE facts evidenced in one closure packet

1. Beads computed the item ready and recorded an atomic claim.
2. Gas Town launched the configured non-interactive surface with zero
   upstream code changes.
3. The official model CLI retained custody of authentication.
4. `tier run` emitted a candidate patch and complete backend telemetry.
5. The frozen referee returned `ACCEPTED`.
6. `tier verify` reopened every relevant hash and binding.
7. The ACCEPTED RECEIPT — not process exit, not model narration —
   authorized the Bead closure.
8. The Bead retains the receipt path and digest as its closure evidence.
9. No patch was automatically applied or merged.

## Negative run (provider-free, required)

One run whose acceptance intentionally fails: must produce `REJECTED` or
`ERROR`, preserve diagnostics, and leave the Bead open or explicitly
blocked. A system that closes work because the command exited, the agent
claimed success, or a patch merely exists has FAILED the evidence contract.

## Freeze-time custody of external beliefs

Gas Town and Beads are the first UNPINNED EXTERNAL dependencies to enter
this repo's evidence boundary. Beyond version pins: vendor into this crate
the exact preset bytes AND excerpts of the Gas Town public-boundary docs
relied upon (`gt` CLI, `settings/agents.json`, non-interactive preset
docs), so a later pass/fail is adjudicated against what was believed at
freeze time — never against upstream's current docs. Phase 1's
argument-capture fixture reuses the `tests/test_smoke_before_cage.py`
idiom (the repo's established transport-proof pattern).

## PARTIAL is a complete night (frozen expectation)

The one-dispatch budget composes with one-attempt-per-tier: if the live
call fails for a transport reason phase 1 didn't catch, the night's output
is three frozen contracts and a PARTIAL — a legitimate, complete outcome
under burden discipline. Precedent: ARC-D-PILOT sealed 3/3 systemErrors as
PARTIAL, and its retry required a separately versioned, operator-authorized
protocol (ARC-D-PILOT-R1). A PARTIAL seal here does NOT authorize any next
session to retry; a retry is a new protocol version with new operator
authority.

## Predetermined no-go classes (any one → seal PARTIAL/FAIL, stop)

Command-transport mismatch; nested-worktree conflict; credential exposure;
receipt not deterministically locatable; premature Bead closure; Gas Town
modifying the candidate outside `tier run`; missing runtime telemetry;
reliance on an undocumented Gas Town internal API.

## Bounds

Install `gt`/`bd` at pinned versions (record source + hash). One live model
call TOTAL. All other runs provider-free. The three contract crates
(policy_kernel / referee_kernel / work_receipt) stay implementation-blocked
until this receipt exists; no Agent Deck card, no general Beads importer,
no drainer card may be opened on any outcome of this smoke alone.

