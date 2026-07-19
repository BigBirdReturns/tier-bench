# Sol cross-engine audit — Monster Wrangler side-by-side (2026-07-19)

*Authored by gpt-5.6-sol via codex exec (read-only sandbox, stdout transport). Bytes committed verbatim (surviving portion) by the Claude desk with attribution.*

*TRANSPORT DEFECT, recorded honestly: the dispatching desk piped codex stdout through tail -N, truncating the head of this review. What follows is the SURVIVING portion; the beginning is lost and NOT reconstructed. Severity counts at the end are Sol's own and cover the full original. Future stdout-transport dispatches capture to file, never through tail.*

Both default `TierRunExecutor` implementations:

1. Require a readable `receipt.json`.
2. Invoke `tier_runner.cli verify`.
3. Take the terminal state from `receipt.state`.
4. Force `ERROR` when verification fails.

Evidence:

- #118: `tier_runner/desk_runtime.py:146-173`
- #119: `tier_runner/desk.py:1682-1727`

Thus exit zero alone cannot close a task through the default subprocess path.

### Whole-system invariant: refuted

Neither store rechecks the evidence when committing terminal state:

- #118 `DeskStore.complete()` accepts any terminal `ExecutionResult.state` and writes it directly to both run and task: `tier_runner/desk_store_queue.py:214-250`.
- #119 `DeskStore.complete_run()` does the same—even `evidence_complete` is merely stored, not required for `ACCEPTED`: `tier_runner/desk.py:1196-1245`.

The committed tests exercise the bypass:

- #118’s `FakeExecutor` defaults to `ACCEPTED` with a fabricated minimal receipt/verification object and no verified run directory: `tests/test_tier_desk.py:29-50`.
- #119 directly calls `complete_run(ExecutionResult(state="ACCEPTED", receipt={"state":"ACCEPTED"}, verification={"ok":true}))`, then observes that dependent work unlocks: `tests/test_monster_wrangler.py:195-232`.

This is not remotely reachable through the default HTTP/executor path, but it is a real internal/injected-executor bypass. The constitutional invariant is an adapter convention, not a state-machine invariant.

**Required repair:** the store must refuse `ACCEPTED` unless a verifier-minted result proves a readable receipt, `receipt.state == ACCEPTED`, successful `tier verify`, matching run/task bindings, and complete evidence. Add a negative witness where a fake executor returns `ACCEPTED` without those facts and the store records `ERROR`.

## 2. Recommendation of #119

### Verdict: not justified by the stated rationale

The extra #119 machinery is real: tanks, route fallback, basis labels, token/cost ceilings, and a hash-linked event table. But it is not “the policy-kernel card already implemented.”

The frozen card defines a pure, deterministic, hash-bound decision function that:

- consumes four sealed inputs, including an evidence index;
- cannot spawn;
- cannot modify scheduler state;
- prevents hypotheses from becoming measurements;
- emits a decision binding task, cartridge, tank and evidence hashes.

See `origin/claude/kernel-contracts-v1:experiments/breadth/crates/policy_kernel_contract_v1/010.100.TASK.md:8-49`. The same card says implementation beyond the validator is blocked pending the Gas Town smoke at lines 3-6.

#119 instead:

- embeds routing inside the mutable SQLite scheduler;
- spawns `tier run`;
- produces no hash-bound decision object;
- accepts operator-supplied `capability_basis` and `quota_basis` after enum validation only, with no evidence-index check (`tier_runner/desk.py:680-703`).

Therefore the review mistakes adjacent UI/control-plane features for conformance to the frozen kernel.

### Simplicity was materially undervalued

Actual diff surfaces:

- #118: 2,719 insertions across 16 files, with production logic split into focused modules.
- #119: 4,659 insertions across 8 files, dominated by a 2,693-line `desk.py` plus 796-line UI.

#118 also already owns two operationally important properties absent from #119: heartbeat-bound child lifetime and a whole-envelope CLI boundary. If the immediate requirement is a minimal desk over existing `tier run`, #118 is the lower-risk base after shared closure/security repairs.

**Recommendation:** merge neither as-is. If one must become the desk base, prefer #118’s smaller modular control plane; port #119’s tank/policy ideas later behind the actual pure policy-kernel boundary.

### Additional #119 quota defect

#119 accepts arbitrary future `observed_at` timestamps (`desk.py:117-128`). Its freshness test computes `age = current - observed` and rejects only when `age > max_age` (`desk.py:871-878`). A future-dated snapshot therefore has negative age and remains “current” until that future time plus the allowance.

That defeats the claimed fail-closed tank staleness control.

**P1 repair:** reject snapshots materially later than controller time, with a bounded clock-skew allowance and a negative witness.

## 3. Sufficiency of the proposed merge gates

### Verdict: insufficient

- Gate 1, deleting the dead write-scoped workflow, is necessary.
- Gate 2, a real end-to-end closure test, is necessary but does not close the current injected-executor/store bypass.
- Gate 3 combines useful features with further implementation expansion; it is not itself proof of closure.

### Fourth gate I would add

**Approval-to-dispatch byte binding.**

Both desks validate a manifest path when creating/approving work, but persist only the path and mutable task fields:

- #118 task record: `desk_store_base.py:241-260`
- #119 route/task record: `desk.py:650-703, 767-791`

At execution, the shared runner independently selects whatever repository `HEAD` exists then and loads the manifest/template from that commit: `origin/main:tier_runner/core.py:448-463`.

A commit between operator approval and dispatch can therefore change the backend manifest, prompt template, adapter/source bytes, or base tree without invalidating approval. The resulting receipt faithfully binds the new bytes—but does not prove they are the bytes the operator approved.

The fourth gate must persist an approval object binding:

- base commit;
- task, acceptance and scope hashes;
- manifest, prompt-template and adapter source-closure hashes;
- selected route/tank snapshot.

`claim()` must recompute these and refuse on any drift. No silent “use current HEAD.”

## 4. Security findings beyond `assemble.yml`

### P1 — Shared ambient-credential exposure

Both desk executors clone the complete environment into the child:

- #118: `desk_runtime.py:117-137`
- #119: `desk.py:1651-1671`

The shared runner passes every non-`TIER_` variable to the backend (`core.py:555-558`) and passes the full ambient environment to the acceptance command (`core.py:617-620`). Model-authored candidate code executed by the trusted acceptance command can therefore read unrelated `GH_TOKEN`, cloud credentials, API keys, or other secrets and emit them through logs or network access.

This is inherited from `origin/main`, not introduced by one rival, but both desks turn it into an unattended repeated-execution path.

**Required repair:** construct explicit environment allowlists separately for the adapter and acceptance process; run acceptance in a credential-empty, network-bounded environment.

### P1 — Approval/manifest TOCTOU

The approval-to-dispatch drift described above is also a security issue: another actor able to commit to the managed repository after approval can replace the committed backend command or prompt bytes that will execute with the desk’s ambient authority.

### P2 — The HTTP token is CSRF protection, not local authentication

Both unauthenticated root handlers embed the mutation token in returned HTML:

- #118: `desk_http.py:185-192`
- #119: `desk.py:2175-2182`

GET state, logs, receipts and patches are also tokenless. Any local process that can reach the port can obtain the token and mutate the desk. Host/origin controls materially protect against ordinary browser CSRF and DNS rebinding, but the side-by-side table’s “loopback bearer token” wording overstates the boundary. Both projects’ own docs more accurately limit it to a same-machine browser session and explicitly disclaim remote authentication.

### P2 — #119 event chain is diagnostic, not tamper-evident custody

The event hashes and their “sealed” head/count metadata reside in the same mutable SQLite database. `verify_event_chain()` is exposed through `/healthz`, but scheduler startup and `tick()` do not require it to pass. A rewritten chain plus rewritten metadata is undetectable, and even detectable corruption does not stop dispatch.

Call it an accidental-corruption detector unless its head is externally anchored and scheduler admission fails closed on verification.

## Final disposition

**CHANGES_REQUESTED_BEFORE_EITHER_MERGE.**

The default execution paths independently converge on the right referee pattern, which is useful cross-lineage evidence. The desk state machines do not yet enforce it. #119’s recommendation relies on a policy-kernel conformance claim contradicted by the frozen card, while #118’s smaller, modular and heartbeat-supervised surface is genuinely valuable.

No aggregate “#119 wins” verdict is supported by the bytes.
