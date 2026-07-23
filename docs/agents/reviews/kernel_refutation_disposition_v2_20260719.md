<!-- DRAFT v2, proposal-only — the unified operator decision document. Authored by a claude-sonnet-5 hand ($3.89) under KERNEL-REFUTATION-DISPOSITION-1, covering all 40 findings of the full Sol re-issue plus old P2-02 (41 rows). The hand verified implementation claims against committed code; desk spot-check confirmed the highest-leverage claim (work-receipt validate.py never references schema.json — grep returns zero hits). 33 ACCEPT / 6 PARTIAL-ACCEPT / 2 MOOT-BY-SEAL / 0 REJECT. No card, schema, or validator bytes change until operator disposition. -->

All four verification passes are in. Here is the complete unified disposition draft.

---

```markdown
<!-- DRAFT v2, proposal-only. Authored by a claude-sonnet-5 hand under KERNEL-REFUTATION-DISPOSITION-1,
against the COMPLETE 40-finding Sol re-issue (sol_kernel_contracts_refutation_full_20260719.md),
superseding kernel_refutation_disposition_draft_20260719.md (v1, old-numbering, 11 surviving findings).
Every implementation-level claim below was independently re-verified by four read-only crate-scoped
subagents reading the actual committed validate.py/schema.json/core.py/witnesses/fixtures — not taken
on Sol's word. Not yet desk-adjudicated; all amendments gated on operator disposition. Lane: driver,
read-only — no files touched authoring this document. -->

# Kernel-Card Refutation — Unified Per-Finding Disposition (v2, 2026-07-19)

Covers all 40 findings of Sol's complete re-issue (0 P0 / 31 P1 / 9 P2) plus old-pass P2-02
(canonicalization), which the cross-pass mapping found has no counterpart in the new pass and
stays live. 41 rows total. Every code-level claim was checked against the actual committed
implementation by four parallel verification agents (one per crate); all 41 claims were confirmed
TRUE or PARTIAL — none were refuted by the code. Where the cross-pass mapping links a finding to
v1's old-numbering disposition, that carryover is noted explicitly, including two cases where the
new pass's broader/deeper reading requires refining v1's framing rather than simply repeating it.

## Policy kernel contract

### P1-1 — Syntactically valid hash can turn hypothesis evidence into `measured`
DISPOSITION: ACCEPT
Verified: `validate.py:116-126` (`reject_hypothesis_as_measured`) branches only on `basis in ("hypothesis","unmeasured")`; when `capability_basis=="measured"` the function is a no-op. Nothing in `validate_decision` (`validate.py:203-242`) resolves `evidence_refs` against an evidence index, tier, or cartridge. `capability_basis: "measured"` + `evidence_refs: ["hypothesis:invented"]` + arbitrary 64-hex hashes passes. No fixture exercises this case (confirmed absent from `fixtures/`).
Repair: Validator must accept sealed evidence-index bytes + task tier as inputs, hash them, resolve the selected cartridge/tier record, and reject `measured` unless that record is measurement-class. Add 4 negative fixtures (invented ref, wrong-tier, wrong-cartridge, hypothesis-only-as-measured).
Cost class: small-validator-change (new input plumbing + lookup) + $0-fixtures.

### P1-2 — Evidence index absent from the decision's content binding
DISPOSITION: ACCEPT
Verified: `validate.py:162-166,194-195` and `schema.json:16-31` — `decision_id = sha256(task_hash + cartridge_hash + tank_hash)` only. No `evidence_index_sha256` field exists anywhere in schema; it is never part of the concatenation. Two different evidence indexes can back an identical `decision_id`, undetectably.
Repair: Add required `evidence_index_sha256`; define canonical serialization for all four inputs; fold the fourth digest + policy version into `decision_id` derivation.
Cost class: schema field + small-validator-change.

### P1-3 — `NO_DECISION` is an unbound, replayable assertion
DISPOSITION: ACCEPT
Verified: `schema.json:127-147` (`NoDecision`) — required = `{type, reason, observed_at}` only, and `additionalProperties: false` (line 146) *actively forbids* adding task/manifest/tank/evidence/policy-version/id binding fields. This is a schema-level guarantee of unboundedness, not an omission.
Repair: Give refusals the same four input digests, policy digest/version, deterministic `decision_id`, and operator-gate state as positive decisions.
Cost class: schema field (loosen `additionalProperties`, add required bindings) + small-validator-change.

### P1-4 — Staleness controlled by omitted argument and self-selected threshold
DISPOSITION: ACCEPT
Verified: `validate.py:137` defaults `tank_age_seconds: int = 0`; `validate.py:145` reads `max_age = obj.get("snapshot_max_age", 0)` — pulled straight from the decision under test; `validate.py:233-234` call site passes no independent age. Self-judging is exact and confirmed at the call site, not merely inferable.
Repair: Bind snapshot observed-at instant + operator-owned max-age policy into sealed inputs; verifier receives an explicit adjudication instant, independent of the decision. Add boundary witnesses (age = max, max±1s, self-enlarged max).
Cost class: small-validator-change (new sealed input) + $0-fixtures.

### P1-5 — Credential prohibition is a bypassable keyword filter
DISPOSITION: PARTIAL-ACCEPT
Verified: `validate.py:86-107` (`scan_for_credentials`) scans string VALUES only via whole-word regex (`\bkey\b`, `\btoken\b`, etc. — line 95 builds the path from `key` but only the string branch at line 101 pattern-matches); object KEYS are never scanned. `"sk_live_abcdef123456789"` (no trigger word) is confirmed to pass; a suspicious key holding a non-string value is never checked at all. `fixtures/invalid_credential_in_field.json:13` exists but only tests a string containing the literal trigger word "API_KEY" — the no-keyword and key-scanning gaps are untested.
Mapping: matches old-pass P2-01 (v1: PARTIAL-ACCEPT). Carried over — v1's framing holds and is now confirmed at the line level (no key-scanning at all, not merely "incomplete").
Repair: Scan keys as well as values; add fixtures for a no-keyword secret and a credential-shaped key with a non-string value; document the residual keyword-heuristic gap as an accepted bounded risk (kernel never holds/forwards credentials itself) pending a typed-secret-reference design.
Cost class: $0-fixture (2 new fixtures) + small-validator-change (key scanning).

### P1-6 — `operator_gate` lets the policy kernel award its own authority
DISPOSITION: ACCEPT
Verified: `schema.json:90-108` defines `operator_gate` as `oneOf` a bare bool or `{approved, approver}`. Confirmed stronger than Sol's framing: **no function in `validate.py` inspects `operator_gate` content at all** — its only appearance is in a presence-only fallback check (line 75). `fixtures/valid_hypothesis_decision.json:16-19` already ships a self-authored `{"approved": true, "approver": "system"}` as a *positive* fixture, with zero binding to any operator artifact.
Repair: Kernel reports gate requirements, not approval. If approval is an input, bind an operator-authored receipt digest, subject, scope, expiry, and decision predicate. Add a witness where the kernel fabricates approval with no matching operator receipt.
Cost class: schema field + small-validator-change.

### P2-1 — Fallback cartridges escape evidence and gate rules
DISPOSITION: ACCEPT
Verified: `validate.py:73-74` is the only place `selected_cartridge` and `fallback_order` both appear — a presence-only check in the no-jsonschema fallback path. Divergence from Sol's premise: Sol frames `selected_cartridge` as receiving "even nominal" scrutiny that `fallback_order` lacks; verification shows **neither** gets real content validation — `selected_cartridge` is never referenced again anywhere else in `validate.py`. The finding's conclusion (fallback entries are unvetted and executable) stands, and is broader than stated: the primary route selection is equally unvetted by this validator (tracks directly to P1-1's gap).
Repair: Represent each fallback as a complete, independently justified route entry with evidence/quota/gate basis, or mark fallback entries explicitly non-executable. Repair should be delivered jointly with P1-1's evidence-resolution work since both need the same cartridge/tier lookup machinery.
Cost class: small-validator-change (shared with P1-1).

### P2-2 — Process-spawn witness does not establish purity or absence of external effects
DISPOSITION: ACCEPT
Verified: Stronger than stated — the spawn-interception witness is **not implemented in-crate at all**. `test_validator.py:173,183` marks it "verified by harness, not validator" (i.e., asserted true without an actual check in this crate); no subprocess/exec-interception code exists anywhere under `crates/policy_kernel_contract_v1/`. There is currently zero enforcement of any kind against in-process network/model calls or direct filesystem/scheduler mutation.
Repair: Run the kernel in an OS-level capability sandbox (no network, no writable FS, no credentials, no scheduler handles); treat any external I/O as failure. A cheap interim step ($0): static-scan the kernel's own source for network/subprocess/filesystem-write imports as a coarse tripwire while full sandboxing is scoped.
Cost class: new-machinery (real sandbox) for the full repair; $0-fixture for the interim static-scan tripwire.

## Referee kernel contract

### P1-7 — Preflight failures do not emit a terminal receipt or machine-readable reason
DISPOSITION: ACCEPT
Verified: `tier_runner/core.py:448-464` — preflight (`_repo_root`, HEAD sampling, `_normalize_scope`, `load_backend`, `_committed_blob`) all runs outside any try/except, before the receipt dict is built at `core.py:489`. `witnesses/w3_base_commit_drift/witness.py:27-40` catches `RunError` and never reads a receipt. `cli.py:144-154`: `print(f"tier: {exc}", file=sys.stderr); return 2`. `reasons.py:67-83`'s `classify()` substring-matches raw exception text — it is a crate-local classifier never wired into anything `tier_runner` actually emits.
Mapping: old-pass P1-13 and P2-03 both PARTIAL-matched here (v1: both PARTIAL-ACCEPT, narrower framings). New verification confirms the underlying claim fully, not partially — upgrading from v1's PARTIAL framing to full ACCEPT for P1-7 itself.
Repair: Construct the terminal envelope before all fallible preflight work; emit `ERROR` with a schema-enforced closed reason code for every refusal path; integrate `reasons.py`'s codes into `schemas/tier_run_receipt.schema.json` (currently absent — see also the schema note under P2-3).
Cost class: new-machinery (control-flow restructuring in `core.py` across every preflight path).

### P1-8 — No external freeze authority for base, task, scope, or acceptance
DISPOSITION: ACCEPT
Verified: `core.py:449` samples `HEAD` at call time; `core.py:437-446` takes task/files/acceptance as plain invocation args; `core.py:521-544` stores `base_commit`/`files`/`task_sha256`/`acceptance_sha256` as *separate* fields with no combined envelope hash. Grep confirms no "envelope" concept exists anywhere in `tier_runner`. Only `base_commit` is independently re-verified against Git (via w3); task/scope/acceptance are trusted as given at invocation with zero substitution detection.
Mapping: old-pass P1-12 PARTIAL-matched here (v1: PARTIAL-ACCEPT, citing Gas Town's `phase1/PIN_LIST.draft.json` as ~80% mitigation). **Divergence from v1: PIN_LIST is scoped to `gastown_tier_run_smoke_v1`'s Gas-Town-specific one-call authorization, not to the referee kernel's general freeze contract that P1-8 targets.** P1-8 applies to any host calling `tier run`, not only the Gas Town smoke path, and remains fully open regardless of PIN_LIST's existence. Upgrading from v1's PARTIAL framing to full ACCEPT.
Repair: Accept one immutable operator-authored envelope digest binding all four values; require the current repository to match it before dispatch. Add independent substitution witnesses for base, task, scope, and acceptance between freeze and dispatch.
Cost class: new-machinery (`core.py` invocation-contract change).

### P1-9 — Hashing command text does not freeze acceptance semantics
DISPOSITION: ACCEPT
Verified: `core.py:538` — `"acceptance_sha256": _sha(acceptance.encode("utf-8"))`. Binds only the command string; `manifest.py`/`core.py` never hash a referenced script's bytes, PATH resolution, or dependency closure.
Repair: Freeze an executable acceptance specification — argv without shell reinterpretation, executable hash, script/dependency closure, controlled environment, network policy. Add a witness mutating a referenced script while the command string stays fixed.
Cost class: new-machinery (dependency-closure hashing is nontrivial).

### P1-10 — Verifier may mutate, test, and restore the candidate without detection
DISPOSITION: ACCEPT
Verified: `core.py:604-610` snapshots before acceptance; `core.py:620-633` compares only that pre-acceptance snapshot to the post-acceptance state. `witnesses/w6_verifier_mutated_candidate/witness.py` uses `accept_mutate.py`, which performs a **persistent** mutation — confirmed no witness tests mutate-then-restore. A write-test-restore sequence entirely inside the acceptance process is invisible to the current check.
Repair: Execute acceptance over a read-only mounted candidate, or instrument all writes (including transient ones) and reject on first attempted mutation. Add a mutate-test-restore witness.
Cost class: new-machinery (read-only mount or write-instrumentation) for full fix; the negative witness proving the gap is buildable at $0 today.

### P1-11 — Ignored/untracked test inputs can make the tested tree differ from the emitted patch
DISPOSITION: ACCEPT
Verified: `core.py:413-418` — `_changed_files` uses `git ls-files --others --exclude-standard` + `git diff --name-only HEAD`; ignored files never enter `untracked`/`changed`. Nothing inventories or rejects an undeclared ignored-file dependency used by acceptance.
Repair: Inventory all filesystem entries visible to acceptance, reject undeclared ignored/untracked dependencies, apply the emitted patch to a fresh detached worktree and rerun acceptance there.
Cost class: new-machinery (fresh-worktree rerun harness); partially buildable as a witness at $0.

### P1-12 — The "restricted packet" is not a security boundary
DISPOSITION: ACCEPT
Verified: `core.py:556-558` sets `env = {...os.environ... if not k.startswith("TIER_")}` (near-full environment inheritance), `cwd=packet`; `core.py:207-232` (`_prepare_packet`) is a plain tempdir with copied files — no filesystem jail, no network policy, no process containment.
Repair: Place the backend/model process in an enforceable sandbox — packet-only readable/writable filesystem, no operator checkout/`.git` visibility, scrubbed allowlist environment, bounded network, process containment. Add read-escape and write-escape canaries.
Cost class: new-machinery (real process sandbox — significant, likely OS-specific).

### P1-13 — Telemetry and session freshness are self-attested by the backend under test
DISPOSITION: PARTIAL-ACCEPT
Verified: `witnesses/common.py:53-63` — the fixture backend self-fabricates `session_id`/`telemetry_complete`/token counts with zero cross-check, confirming the hostile scheme fully for the kernel/witness layer. However, the real Claude Code adapter (`adapters/claude_code.py:239-251,282`) does seal a `raw_result_sha256` artifact from `process.stdout` — but `core.py:953-959` makes that check *conditional* (`if raw_hash is not None`, i.e. optional, not required), and the sealed data is parsed from the same self-produced stdout it then hashes, not an independently obtained provider/CLI receipt. So the real adapter has a partial building block that the fixture/witness path lacks entirely, but neither is currently sufficient.
Repair: Require provider/CLI-owned raw receipts (or independently captured process evidence) bound to dispatch; make `raw_result_sha256` mandatory, not optional; verify actual session creation and telemetry against that independent source rather than self-produced stdout. Add reused-session and fabricated-telemetry witnesses.
Cost class: small-validator-change (make the existing field mandatory) + new-machinery (independent capture for fixture/witness backends).

### P1-14 — `tier verify` has no external trust anchor and accepts coherent rewrites
DISPOSITION: ACCEPT
Verified: `core.py:668-679` — the receipt's own `artifacts` dict (the hashes that "protect" dispatch/ledger/etc.) is written into the same mutable `receipt.json` it protects. No signing/publish call exists anywhere in `core.py`/`cli.py`.
Note: This is a **distinct finding from old-pass P1-14** despite the identical number — the old finding (mapped in the cross-pass table to new P1-31/P1-28) was about Gas Town's closure-packet trust root; this new P1-14 is about the referee kernel's general `tier verify` trust anchor, applicable to every receipt produced today, not gated on any smoke-phase status. Do not conflate the two when adjudicating.
Repair: Publish the closure root digest through an operator-controlled append-only channel or signature before downstream use; `tier verify` requires that external root. Add a coherent full-packet rewrite witness.
Cost class: new-machinery (append-only log or signing infra) — applies now, not smoke-gated, since receipts are already being produced.

### P1-15 — Directory deletion is treated as cleanup even if spawned work survives
DISPOSITION: ACCEPT
Verified: `core.py:648-667` (finally block) — only `worktree remove` and `shutil.rmtree(packet)`, both pure existence checks. No descendant-process tracking, credential-release check, or delayed-external-write detection.
Repair: Own the full process/job tree, deny detachment, terminate and verify all descendants, prove no writable external capability remains. Add a detached-child witness with a delayed-write canary.
Cost class: new-machinery (process-tree tracking — note Windows-specific complications for this dev environment).

### P2-3 — Verification does not require rejected-run diagnostics to survive
DISPOSITION: ACCEPT
Verified: `core.py:730-736` loops process artifacts with `if process is None: continue` (runs for any state, but only when the key is present); `core.py:754-781`'s required-artifact/completeness checks are gated `if receipt.get("state") == "ACCEPTED"`. Deleting the `acceptance` key (and its stream files) from a REJECTED receipt hits the `continue` branch and raises nothing — confirmed no REJECTED-specific completeness check exists.
Also confirmed: `witnesses/w5_acceptance_failed_rejected/witness.py:33-36` already asserts `state=="REJECTED"`, `acceptance.returncode != 0`, and stdout/stderr/patch artifact existence for the *passing* case — but nothing prevents those same artifacts from being stripped post-hoc. Also confirmed: no `schema.json` exists in this crate at all despite the card's own text (`010.100.TASK.md:29-33`) claiming reason codes are "a CLOSED enum frozen in the schema" — the repo-root `schemas/tier_run_receipt.schema.json` has no reason-code field whatsoever, only `state: enum` and free-text `errors: array[string]`. This card-text/schema mismatch is a defect independent of Sol's finding, in the same vein as v1's note under old P2-03.
Repair: Define terminal-class-specific required artifacts and validate them for every state, not just ACCEPTED. Separately: either author the missing `schema.json` to match the card's claim, or correct the card's claim to match reality.
Cost class: small-validator-change (contained to `verify_run`'s state-gating) + card-text correction ($0).

## Work receipt contract

*Cross-cutting note, applies to all 11 findings below:* verification confirmed `validate.py` never loads or enforces `work_receipt_contract_v1/schema.json` at all (no `jsonschema` import, no `.validate()` call anywhere in the file). This single missing wire-up is the root cause of P1-16, P1-19 (partially), P1-20, P1-23, P2-4, and P2-5 all failing to enforce structure that is *already correctly defined in schema.json* (e.g., `external_refs`' closed 4-key union at `schema.json:146-168` is real and would foreclose part of P1-23's attack — but is never invoked). Wiring `jsonschema.validate(receipt, schema)` into `validate.py`, fail-closed if the dependency is unavailable, is the single highest-leverage repair across this crate and should be sequenced first.

### P1-16 — The production validator does not enforce its schema
DISPOSITION: ACCEPT
Verified: No `jsonschema` import (`validate.py:7-11`). `task_id`/`attempt_id`/`scope`/`runtime_evidence`/`created_at` are never referenced anywhere in the file (grep-confirmed) — 5 of the 9 named required fields are simply never read; the other 4 (`predecessor_receipts`, `unlocks`, `blocks`, `external_refs`) default permissively via `.get(field, [] / {})`. Removing all 9 still returns `valid: true`.
Repair: Run draft-2020-12 schema validation first; fail closed if the dependency is unavailable. Add one missing-field witness per required property and one unknown-property witness.
Cost class: small-validator-change (this is the cross-cutting fix above) + $0-fixtures.

### P1-17 — "Known decision" is reduced to 64 lowercase hex characters
DISPOSITION: ACCEPT
Verified: `validate.py:93-110` (`_check_orphaned_decision`) does only `SHA256_PATTERN.match(decision_hash)`. No decision document is ever passed in or dereferenced.
Repair: Require the cited decision document in the presented verification set, recompute its canonical digest, validate the decision, cross-check task/cartridge/gate bindings. Add absent, wrong-byte, wrong-task witnesses.
Cost class: new-machinery (verification-packet plumbing — shared with P1-18).

### P1-18 — "Unverifiable" content bindings accepted when strings look like hashes
DISPOSITION: ACCEPT
Verified: `validate.py:114-154` — all five `*_sha256` fields are regex/length checked only. `hashlib` is imported (line 9) but **never called** (grep-confirmed zero `hashlib.` invocations) — direct proof nothing is ever resolved against real bytes.
Repair: Define a verification packet mapping each digest to bytes, recompute all digests, validate each artifact's own schema, reject missing objects. Add forged-format-correct hashes for every binding.
Cost class: new-machinery (shared packet infra with P1-17).

### P1-19 — Anyone who can write JSON can mint terminal authority
DISPOSITION: ACCEPT
Verified: `schema.json:7-26`'s required list has no issuer/signer field; `external_refs.worker_identity` (`schema.json:158-161`) is explicitly descriptive per the card, not an authority binding. No signer/append-only-root concept exists in schema or validator.
Repair: Bind receipt issuer and referee identity to a trusted key or operator-controlled append-only log; verification starts from an external trusted root.
Cost class: new-machinery (signing/key infrastructure — real investment, but not live-dispatch-gated).

### P1-20 — `scope` does not bind repository identity or allowed paths
DISPOSITION: ACCEPT
Verified: `schema.json:64-80` — `scope` requires only `["tier","task_type"]`, `additionalProperties: false`. `base_commit` (format-checked only, `validate.py:146-152`) is a sibling field never used to bind `scope` or the patch.
Mapping: matches old-pass P2-05 exactly (v1: ACCEPT). Carried over cleanly, now confirmed at the schema/line level.
Repair: Add repository identity, object format, base-tree digest, ordered allowed paths, task-envelope cross-binding; verify the patch touches only those paths. Add cross-repository replay and scope-escape witnesses.
Cost class: schema field + small-validator-change (patch-path check).

### P1-21 — Predecessor membership is not hash linkage; cycles not rejected
DISPOSITION: ACCEPT
Verified: `validate.py:213-245` (`_check_unverified_predecessor`) — `if pred_hash not in known_receipts` is a pure dict-key membership test. No recompute, no recursive validation, no cycle tracking; self-cycle or two-node cycle both pass if the key is "known".
Repair: Recompute canonical receipt hashes, recursively validate presented predecessors, enforce acyclicity, verify successor-effect authorization. Add wrong-content, self-cycle, two-node-cycle, unrelated-task witnesses.
Cost class: small-validator-change (contained recursive-validation + cycle-detection logic).

### P1-22 — Duplicate terminal detection is optional caller testimony
DISPOSITION: ACCEPT
Verified: `validate.py:42,54` default `all_receipts_for_attempt` to `[]`; `validate.py:192-211` never filters by `attempt_id` — counts any terminal receipt in whatever list is supplied. Default-arg calls trivially both "pass"; unrelated-attempt receipts in a supplied list can false-flag.
Repair: Validate a complete presented set; group internally by exact `attempt_id`; fail closed when uniqueness cannot be established.
Cost class: small-validator-change.

### P1-23 — External authority can be smuggled through any spelling except nested `verdict`
DISPOSITION: ACCEPT
Verified: `validate.py:298-322` — only `isinstance(value, dict) and "verdict" in value` (line 315) is rejected. Separately confirmed: `schema.json:146-168`'s `external_refs` IS already a closed 4-key string-typed union (`additionalProperties: false`) that would foreclose the "add a verdict field" scheme at the schema level — but per the cross-cutting note, schema.json is never enforced, so this protection is currently inert. `fixtures/rejection_external_override_verdict.json:26-29` uses `gas_town_rig` as an *object* (which actually violates schema.json's `type:"string"` for that key at line 154-157) — passing today only because the schema is never applied.
Mapping: matches old-pass P2-04 exactly (v1: PARTIAL-ACCEPT, which already identified the schema-not-wired-in gap as "a latent defect independent of Sol's finding"). New verification confirms v1's read exactly and traces the same root cause across P1-16/P1-19/P1-20/P2-4/P2-5. Upgrading from PARTIAL-ACCEPT to ACCEPT now that the fix is understood to be a single shared wire-up plus targeted content restriction, not an open-ended design problem.
Repair: (1) wire `schema.json` into `validate.py` (shared with P1-16 — this alone closes the nested-verdict-key and object-typed-field variants); (2) add content restrictions to the four `external_refs` string fields (prohibit free-form directive strings; use opaque typed identifiers) to close the alternate-key/string-encoded variants schema enforcement alone won't catch.
Cost class: small-validator-change (shared wire-up, near-free) + schema field/small-validator-change (content restriction).

### P1-24 — Scheduler effects can silently fail open or contradict each other
DISPOSITION: ACCEPT
Verified: `validate.py:38` — `self.all_task_ids = set(...) if all_task_ids else set()`; `validate.py:267` — `if self.all_task_ids:` gates resolution entirely (opt-in, defaults skipped). `unlocks` (268-280) and `blocks` (282-294) are checked independently with no cross-check for overlap, no intra-list duplicate check, no self-reference check, and — since `terminal_state` is never read here — no gating against `unlocks` from REJECTED/ERROR receipts.
Repair: Require the authoritative task-envelope set (not opt-in default-empty); enforce uniqueness/disjointness/no-self-reference; define terminal-state-specific effect rules. Add nonexistent-default, overlap, duplicate, self-effect, rejected-unlock witnesses.
Cost class: small-validator-change.

### P2-4 — `ERROR` paired with `PASS` is declared logically consistent
DISPOSITION: ACCEPT
Verified: `validate.py:156-190` — ACCEPTED↔PASS enforced (176-181), REJECTED↔FAIL enforced (183-188); no equivalent branch exists for `terminal_state=="ERROR"`. ERROR receipts pass the enum checks (161, 168) with either PASS or FAIL, unconditionally.
Repair: Replace independent scalars with one closed terminal union, or define an explicit truth table where ERROR carries no referee verdict. Add every Cartesian-product witness.
Cost class: schema field + small-validator-change.

### P2-5 — Runtime evidence is an unauthenticated description
DISPOSITION: ACCEPT
Verified: `schema.json:90-99` — `execution_log` is `"type":"string"` only (comment "Path or hash," no `pattern`); `model_used` is `"type":"string","minLength":1`, unverified. `validate.py` never references `runtime_evidence` at all (grep-confirmed) — zero enforcement beyond bare JSON-Schema type presence, and even that is unenforced per the crate-wide schema-wiring gap.
Mapping: matches old-pass P1-11 exactly (v1: ACCEPT). Carried over cleanly, confirmed at the schema/line level — actually worse than v1 realized, since `validate.py` doesn't touch this field at all, not merely "supplying permissive defaults."
Repair: Make `runtime_evidence` a closed object of content-addressed artifacts with provider/adapter provenance and completeness predicates. Add missing-log, wrong-hash, false-model, reused-session, fabricated-telemetry witnesses.
Cost class: schema field (redefine `runtime_evidence`) + small-validator-change for structural checks; independent provenance verification is new-machinery.

## Gas Town / `tier run` smoke contract

*Status context for all 11 findings below, from `phase1/PHASE1_SEAL_AMENDMENT_20260719.md` (verified in full): phase 1 is sealed **PARTIAL**, no retry authorized. The native Windows `gt` path is blocked by a persistent-Dolt-daemon requirement; only config/probe `gt` commands ran (no `sling`/`assign`/`formula run`). Phase 2 (the one live model dispatch) was never authorized, never dispatched — the one-dispatch budget is fully unspent. The amendment narrows the stated *reason* for the phase-1 blocker but does not change the operative PARTIAL/no-phase-2 outcome.*

### P1-25 — Phase 1 can pass wrong values and does not target the real `tier run` CLI
DISPOSITION: ACCEPT
Verified: `phase1/verify_capture.py:15-35` checks presence + `not value.startswith('--')` only — no expected-value comparison. Confirmed against the real CLI (`tier_runner/cli.py:27-32`): actual flags are `--repo/--task/--files/--acceptance`, while the fixture checks `--task-text/--repo-path/--file-scope/--acceptance-command` — **the fixture's flag vocabulary does not match the production CLI at all.** This is live phase-1 code that already shipped and was already partially exercised, not speculative future work.
Repair: Capture the exact executable and argv vector, compare byte-for-byte against frozen expected argv+hashes, reject duplicates/extras, and switch to the production flag vocabulary. Add wrong-value, duplicate, reordered, injected, wrong-executable, shell-roundtrip witnesses.
Cost class: small-validator-change (pure-Python rewrite of `verify_capture.py`, $0, no live dispatch or daemon needed) — high priority; should close before any phase-1 retry is authorized, since a retry would otherwise inherit this defect unchanged.

### P1-26 — The self-test bypasses Gas Town entirely
DISPOSITION: ACCEPT
Verified: `phase1/selftest.py:21-30` invokes `capture_fixture.py` directly via `sys.executable`; no `gt` binary is ever invoked. Confirmed this proves only capture↔verify self-consistency.
Repair: Phase-1 acceptance must start at the pinned `gt` executable and end at the capture fixture; direct invocation may remain a unit test but cannot satisfy the gate. **Blocked**: routing through real `gt` today hits the same native-Dolt-daemon requirement that sealed phase 1 PARTIAL, per `PHASE1_SEAL_AMENDMENT_20260719.md`. The finding itself (bypass exists, is real) stands regardless; only the *proper* repair is scheduling-blocked on daemon resolution.
Cost class: new-machinery, blocked pending native-`gt`-daemon resolution (not smoke-phase-2 machinery — this is a phase-1 architecture gap, so it does not qualify for MOOT-BY-SEAL; it's just presently unfixable without the daemon).

### P1-27 — The capture fixture exports almost the entire environment
DISPOSITION: ACCEPT
Verified: `phase1/capture_fixture.py:9-14` — `re.compile(r'(KEY|TOKEN|SECRET)', re.IGNORECASE)` is the entire redaction rule. `PASSWORD`, `GH_AUTH`, `AWS_PROFILE`, `COOKIE`, or any non-matching variable name would be captured and serialized unredacted. Live phase-1 code, already shipped.
Repair: Capture an allowlisted environment projection instead of a redacted copy of everything; test with credential canaries under diverse non-keyword names.
Cost class: small-validator-change (rewrite the redaction logic in `capture_fixture.py`), $0, no live dispatch needed — should close before any retry.

### P1-28 — The nine-fact closure packet has no machine contract or trust root
DISPOSITION: PARTIAL-ACCEPT
Verified: `010.100.TASK.md:45-57` lists nine prose facts; crate contains only `PIN_LIST.draft.json`/`PIN_LIST.template.json`/`hand_receipt.json` — no packet schema, canonicalization rule, issuer, or trust-root file anywhere.
Mapping: old-pass P1-14 MATCHED here (v1: PARTIAL-ACCEPT, noting Beads atomic-claim machinery already works natively via `PHASE0_NATIVE_PROBE.md`, independent of the daemon blocker). Carried forward with a split: the **schema/manifest definition itself** (source/CLI-process/`tier run`-directory/receipt/patch/verifier-output/scheduler-transition binding format) can be authored today at $0 — it doesn't require a live run to define a format. But **populating and verifying** an actual closure packet requires artifacts (a real CLI process, a real `tier run` directory) that only exist after phase 2, which has never run — that half is MOOT-FOR-NOW.
Repair: Define the closure-manifest schema now (content-addressed, binding all nine facts, external root digest requirement, fail-closed verifier). Defer population/verification witnesses until a phase-2-capable protocol version is authorized.
Cost class: schema field / $0 (definition, now) + MOOT-FOR-NOW (population/verification, deferred).

### P1-29 — "One live invocation" does not bound actual provider calls or retries
DISPOSITION: MOOT-BY-SEAL
Verified: `010.100.TASK.md:97` ("One live model call TOTAL") is a policy statement only; no counting/receipt mechanism is defined or implemented anywhere in the crate.
Mapping: old-pass P1-15 MATCHED here alongside P1-30 (v1: DEFER-TO-OPERATOR). Refining v1's label: this pass's rubric provides MOOT-BY-SEAL specifically for smoke phase-2 live-dispatch machinery, which is more precise than DEFER here — same practical outcome (do not build this now), sharper reason (no live path exists to violate or verify it, not merely "awaiting an operator call").
Repair (deferred, not now): Define the counted event at the provider/CLI-receipt level, disable retries, require complete raw call telemetry. Specify before any Phase-2-capable protocol version is authorized — do not pre-build against machinery that hasn't run.
Cost class: new-machinery, MOOT while no live-dispatch path exists.

### P1-30 — Authentication custody is not established by the absence of one flag
DISPOSITION: MOOT-BY-SEAL
Verified: `PHASE1_SEAL_AMENDMENT_20260719.md:43-44` itself states custody reduces to "assert the launched command line is flag-free... remains mandatory in any retry" — the amendment confirms, in its own words, that this is the full extent of the custody check today.
Mapping: old-pass P1-15 MATCHED here alongside P1-29 (v1: DEFER-TO-OPERATOR). Same refinement as P1-29 — MOOT-BY-SEAL is the sharper label under this pass's rubric.
Repair (deferred, not now): Define custody observably — only the official CLI may open the credential path or receive the secret handle; wrappers/Gas Town receive no credential bytes. Use unique canary credentials + file/process access tracing, specified before any phase-2 authorization.
Cost class: new-machinery, MOOT while no live-dispatch path exists.

### P1-31 — Accepted receipt not cryptographically/atomically coupled to Bead closure
DISPOSITION: PARTIAL-ACCEPT
Verified: `010.100.TASK.md:47,56` mention "atomic claim" and "receipt path and digest as closure evidence" as prose facts only — no compare-and-set operation (bead id + claim generation + attempt id + terminal state + receipt digest + scheduler revision) is defined anywhere.
Mapping: old-pass P1-14 MATCHED here alongside P1-28 (v1: PARTIAL-ACCEPT, citing `PHASE0_NATIVE_PROBE.md` — Beads' atomic claim/ready-computation already works natively with embedded Dolt, no daemon, no `gt`, no live dispatch). Carried forward directly: unlike P1-29/P1-30 (which need an actual model dispatch to exercise), the CAS/closure witnesses here (close-then-reopen-before-capture, close-with-wrong-receipt-then-replace-digest, manual-close-then-attach-digest) are testable against real `bd` today, independent of the daemon/phase-2 blocker.
Repair: Require an atomic closure operation conditioned on bead ID, claim generation, attempt ID, terminal state, verified receipt digest, and current scheduler revision. Build the bd-only witnesses now — they don't wait on phase 2.
Cost class: small-validator-change / new bd-only witnesses, $0, buildable now (not MOOT).

### P2-6 — The provider-free negative run is under-specified
DISPOSITION: PARTIAL-ACCEPT
Verified: `010.100.TASK.md:59-64`'s loose "REJECTED or ERROR, preserve diagnostics" text is unchanged by `PHASE1_SEAL_AMENDMENT_20260719.md` (confirmed no mention of the negative-run clause in the amendment); the negative run itself has never executed either way.
Mapping: old-pass P1-13 PARTIAL-matched here (v1: PARTIAL-ACCEPT, noting `referee_kernel_contract_v1`'s `w5_acceptance_failed_rejected` witness already proves the specific `REJECTED`/`acceptance.returncode != 0`/preserved-diagnostics standard the smoke card should require — confirmed independently by the referee-crate verification pass this round). Carried forward unchanged: the fix is purely tightening the smoke card's prose to require w5's existing standard rather than accepting bare `ERROR`; no new referee-kernel fixture is needed, and this doesn't wait on phase 2.
Repair: Tighten card text: "The negative run must terminate REJECTED with acceptance.returncode != 0 and preserved stdout/stderr; ERROR is a FAILED gate requiring adjudication, not an acceptable negative witness, per referee_kernel_contract_v1 w5/w6."
Cost class: $0 card-text change, buildable now.

### P2-7 — Vendored external-belief excerpts lack a frozen manifest
DISPOSITION: ACCEPT
Verified: `010.100.TASK.md:69-71` instructs vendoring "the exact preset bytes AND excerpts" but specifies no manifest format; no such binding file exists in the crate.
Mapping: old-pass P2-06 MATCHED here alongside P1-25 (v1: ACCEPT). Carried over cleanly.
Repair: Freeze a manifest — source URL/release, document path, exact byte range or full file, SHA-256, retrieval evidence, preset hash, root digest committed before phase 1. Buildable today at $0 (vendoring/hashing documentation is a desk task, not a live-dispatch task) — should land before any phase-1 retry, since phase 1 already vendors preset bytes today without this binding.
Cost class: schema field / $0-fixture.

### P2-8 — "No automatic apply or merge" can be satisfied by apply-then-revert
DISPOSITION: PARTIAL-ACCEPT
Verified: `PHASE1_TRANSPORT_VERDICT.md:54-57` — the only instrumentation found is one ad hoc `git status --porcelain` check before deleting a stray file; not systematic Git/worktree/remote mutation-event instrumentation.
Repair: Instrument Git/worktree/remote mutation events; use a protected disposable repository rejecting writes outside `tier run`; record append-only refs before/after. The **instrumentation design** (protected repo, append-only ref log) can be specified now at $0. **Exercising** the apply-then-revert / push-then-delete witnesses requires actual Gas Town automation runs against real `gt`, which are blocked by the same native-daemon issue sealing phase 1 PARTIAL — that half is effectively moot until the daemon blocker resolves.
Cost class: $0 (spec, now) + new-machinery blocked pending daemon resolution (witness execution).

### P2-9 — "Substantive wrapper logic" has no adjudicable boundary
DISPOSITION: ACCEPT
Verified: `010.100.TASK.md:21-22` — the phrase "without substantive wrapper logic" appears once, entirely undefined; no objective test separates a preset from a custom worker framework.
Repair: Freeze an allowlisted adapter shape — exact executable plus static argv substitution only, no loops/retries/scheduler writes/receipt adjudication/persistent state. Hash and inspect the complete invoked program closure (whatever preset/adapter files exist today).
Cost class: $0 card-text definition + $0-fixture (hashing already-existing files) — buildable now, no live dispatch needed.

## Old-pass-only finding (41st row)

### Old P2-02 — Determinism and temporal canonicalization are internally ambiguous
DISPOSITION: ACCEPT
Mapping: cross-pass mapping found no counterpart in the new 40-finding pass — stays live from pass 1, carried forward as-is per the desk's mapping note.
Verified (re-confirmed independently this round via the policy-kernel verification pass): `validate.py:191-200` — `if all([task_hash, cartridge_hash, tank_hash])` gates exact `decision_id` derivation checking; `validate.py:203-242`'s `validate_decision` defaults `verify_decision_id_with_inputs=False`, so the default entry point never supplies the three hashes and skips exact verification, falling back to format-regex + timestamp-pattern rejection only (lines 180, 186). No canonical JSON profile (Unicode normalization, number encoding, key ordering) or policy-implementation-hash binding exists anywhere in `schema.json` or `validate.py`.
Repair: Freeze a canonical serialization profile before hashing; make `decision_id` verification against input hashes mandatory (not optional) at referee time; bind a `policy_impl_sha256` field. Add a fixture showing the current validator accepts a `decision_id` it cannot actually verify when hashes aren't supplied.
Cost class: small-validator-change (flip default + audit callers that don't supply hashes) + schema field.

## Summary Table

| # | Finding | Disposition | Repair cost class |
|---|---|---|---|
| 1 | P1-1 | ACCEPT | small-validator-change + $0-fixtures |
| 2 | P1-2 | ACCEPT | schema field + small-validator-change |
| 3 | P1-3 | ACCEPT | schema field + small-validator-change |
| 4 | P1-4 | ACCEPT | small-validator-change |
| 5 | P1-5 | PARTIAL-ACCEPT | $0-fixture + small-validator-change |
| 6 | P1-6 | ACCEPT | schema field + small-validator-change |
| 7 | P2-1 | ACCEPT | small-validator-change (shared w/ P1-1) |
| 8 | P2-2 | ACCEPT | new-machinery ($0 interim tripwire) |
| 9 | P1-7 | ACCEPT | new-machinery |
| 10 | P1-8 | ACCEPT | new-machinery |
| 11 | P1-9 | ACCEPT | new-machinery |
| 12 | P1-10 | ACCEPT | new-machinery ($0 witness first) |
| 13 | P1-11 | ACCEPT | new-machinery |
| 14 | P1-12 | ACCEPT | new-machinery |
| 15 | P1-13 | PARTIAL-ACCEPT | small-validator-change + new-machinery |
| 16 | P1-14 | ACCEPT | new-machinery |
| 17 | P1-15 | ACCEPT | new-machinery |
| 18 | P2-3 | ACCEPT | small-validator-change + $0 card fix |
| 19 | P1-16 | ACCEPT | small-validator-change + $0-fixtures |
| 20 | P1-17 | ACCEPT | new-machinery |
| 21 | P1-18 | ACCEPT | new-machinery |
| 22 | P1-19 | ACCEPT | new-machinery |
| 23 | P1-20 | ACCEPT | schema field + small-validator-change |
| 24 | P1-21 | ACCEPT | small-validator-change |
| 25 | P1-22 | ACCEPT | small-validator-change |
| 26 | P1-23 | ACCEPT | small-validator-change |
| 27 | P1-24 | ACCEPT | small-validator-change |
| 28 | P2-4 | ACCEPT | schema field + small-validator-change |
| 29 | P2-5 | ACCEPT | schema field + small-validator-change |
| 30 | P1-25 | ACCEPT | small-validator-change ($0) |
| 31 | P1-26 | ACCEPT | new-machinery, blocked on daemon |
| 32 | P1-27 | ACCEPT | small-validator-change ($0) |
| 33 | P1-28 | PARTIAL-ACCEPT | $0 (spec) + MOOT-FOR-NOW (population) |
| 34 | P1-29 | MOOT-BY-SEAL | new-machinery, moot |
| 35 | P1-30 | MOOT-BY-SEAL | new-machinery, moot |
| 36 | P1-31 | PARTIAL-ACCEPT | small-validator-change ($0, bd-only) |
| 37 | P2-6 | PARTIAL-ACCEPT | $0 card-text |
| 38 | P2-7 | ACCEPT | schema field / $0-fixture |
| 39 | P2-8 | PARTIAL-ACCEPT | $0 (spec) + new-machinery blocked on daemon |
| 40 | P2-9 | ACCEPT | $0 card-text + $0-fixture |
| 41 | old P2-02 | ACCEPT | small-validator-change + schema field |

## Counts by disposition

- ACCEPT: 33
- PARTIAL-ACCEPT: 6
- MOOT-BY-SEAL: 2
- REJECT: 0
- DEFER-TO-OPERATOR: 0
- Total: 41

Every implementation-level claim across all 40 findings plus old P2-02 was independently confirmed TRUE or PARTIAL against the actual committed code (validate.py/core.py/schema.json/witnesses/fixtures) by four parallel read-only verification passes — none were refuted. Zero REJECT. The two MOOT-BY-SEAL rows (P1-29, P1-30) are the only findings genuinely gated on a live-dispatch path that has never run and remains unauthorized per `PHASE1_SEAL_AMENDMENT_20260719.md`; everything else is buildable, at least in part, today.

Highest-leverage single repair: wiring `work_receipt_contract_v1/schema.json` into `validate.py` (currently absent entirely) — it is the root cause of 6 of the 11 work-receipt findings failing to enforce structure that is already correctly defined in the schema file.

END-DISPOSITION-V2
```