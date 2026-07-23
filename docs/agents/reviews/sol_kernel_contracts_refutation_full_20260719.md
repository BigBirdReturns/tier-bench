<!-- Authored by gpt-5.6-sol via codex exec (read-only sandbox, --output-last-message file transport, complete — no truncation). Bytes committed verbatim below by the Claude desk with attribution. Dispatch: SOL-REFUTATION-RECOVERY-1, 2026-07-19. Formed BLIND to the surviving fragment of the first pass (docs/agents/reviews/sol_kernel_contracts_refutation_20260719.md) per the recovery brief; this full pass ALSO read the committed implementations (validators/fixtures), which the first pass did not. Cross-pass consistency and old-fragment-to-new mapping are desk follow-ups under KERNEL-REFUTATION-DISPOSITION-1. -->

# Fresh adversarial refutation of the four frozen kernel-contract cards — 2026-07-19

Scope: fresh read-only review of the four cards, their crate-local schemas, validators, fixtures, witnesses, and the relevant `tier_runner` source. No material under `docs/agents/reviews/` was consulted.

Fresh in-memory probes against the current validators confirmed acceptance of: a `measured` policy decision backed only by a hypothesis reference; an unlabeled decision with no supplied snapshot age; credential-shaped data hidden from the lexical scanner; a work receipt missing most required context; `ERROR` paired with `PASS`; and an external scheduler override encoded as ordinary text.

## Policy kernel contract

### P1-1 — A syntactically valid hash can turn invented or hypothesis evidence into `measured`

- **Claim:** The validator never opens the evidence index or verifies that the selected cartridge has measured evidence at the task tier.
- **Hostile scheme:** Submit `capability_basis: "measured"` with `evidence_refs: ["hypothesis:invented"]` and arbitrary 64-hex input hashes. The current validator accepts it because `reject_hypothesis_as_measured` examines references only when the declared basis is already `hypothesis` or `unmeasured`.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:37-41` — “absent evidence index entry for the selected cartridge at the task's tier” and “no code path may emit `measured` from a hypothesis or unmeasured input.”
- **Required witness or repair:** Pass the sealed evidence-index bytes and task tier into validation; hash them; resolve the selected cartridge/tier record; reject `measured` unless that exact record is measurement-class. Add negative witnesses for invented refs, wrong-tier measurements, wrong-cartridge measurements, and hypothesis-only evidence carrying `capability_basis: measured`.

### P1-2 — The fourth sealed input, the evidence index, is absent from the decision’s content binding

- **Claim:** A decision can remain byte-valid after its evidence index is replaced because no `evidence_index_sha256` is required or included in the deterministic identifier.
- **Hostile scheme:** Reuse the same task, manifest, and tank hashes while supplying two different evidence indexes that imply opposite routes. Emit the same `decision_id` and whichever `evidence_refs` are convenient. The output has no binding that lets a verifier identify which index was used.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:10-15` — “provides four sealed inputs” and “returns exactly one hash-bound routing decision”; `:65-67` — “`decision_id` derives from input hashes.”
- **Required witness or repair:** Require `evidence_index_sha256`; define canonical byte serialization for all four inputs; derive `decision_id` from a domain-separated tuple of all four digests and the policy version. Mutating only the evidence-index bytes must change both the binding and identifier.

### P1-3 — `NO_DECISION` is an unbound, replayable assertion rather than a receipt

- **Claim:** Refusals carry no task, manifest, tank, evidence, policy-version, or deterministic identifier binding.
- **Hostile scheme:** Mint one plausible `NO_DECISION` object and replay it against every task and cartridge. A host cannot distinguish a genuine refusal for task A from a substituted refusal suppressing task B.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:62-64` — “refusal is a `NO_DECISION` terminal object carrying its reason — refusals are receipts too.”
- **Required witness or repair:** Give refusals the same four input digests, policy digest/version, deterministic `decision_id`, structured closed reason code, and operator-gate state as positive decisions. Add a cross-task replay witness.

### P1-4 — Staleness is controlled by an omitted validator argument and a kernel-selected threshold

- **Claim:** The normal validator invokes staleness checking with an implicit age of zero, while `snapshot_max_age` is supplied by the decision being judged.
- **Hostile scheme:** Route from a month-old tank snapshot, emit any large `snapshot_max_age`, omit `label`, and invoke the normal CLI. The validator has neither the snapshot observation time nor an independently frozen maximum age and therefore treats the snapshot as current.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:42-44` — “a tank snapshot older than `snapshot_max_age` may support an explicitly ADVISORY decision; it may never be represented as current headroom.”
- **Required witness or repair:** Bind the snapshot’s observation instant and an operator-owned maximum-age policy in the sealed inputs. The verifier must receive an explicit adjudication instant. Add boundary witnesses for age equal to, one second below, and one second above the frozen maximum, plus a hostile decision that enlarges its own maximum.

### P1-5 — The credential prohibition is a bypassable keyword filter, not a secret-custody control

- **Claim:** Only selected substrings in string values are scanned; object keys, non-string values, encodings, and secrets lacking words such as `token` or `key` pass.
- **Hostile scheme:** Put `sk_live_abcdef123456789` in `route_reason`, or add `password_blob: 12345` under the permissive `operator_gate` object. Both passed the fresh in-memory validator probe. Base64, JWT-shaped data without the literal `jwt`, cookies, authorization headers, and provider-specific credential formats can likewise evade the scanner.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:45-46` — “No credentials anywhere: schema-level rejection of any field carrying key/token/credential material; validator scans all string values.”
- **Required witness or repair:** Do not permit free-form secret-bearing fields at this boundary. Close the nested schema, scan keys as well as values, impose length/character constraints, and use allowlisted reference formats instead of arbitrary strings. Add witnesses for secret values without keywords, encoded secrets, suspicious keys with numeric/list/object values, and provider-specific credential formats.

### P1-6 — `operator_gate` lets the policy kernel award its own authority

- **Claim:** A bare boolean or self-authored `{approved, approver}` object is accepted without binding an operator instruction or approval artifact.
- **Hostile scheme:** The routing implementation emits `operator_gate: true` or `{approved: true, approver: "system"}` for a route the operator never approved. A downstream executor sees an apparently open gate with no independently verifiable authority.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:10-13` — “The host (operator, drainer, Desk client) provides four sealed inputs” and the kernel “never modifies scheduler state”; `:28-29` requires `operator_gate` in the output.
- **Required witness or repair:** Make the kernel report gate requirements, not grant approval. If approval is an input, bind an operator-authored approval receipt digest, subject, scope, expiry, and decision predicate. Add a witness in which the kernel fabricates approval without a matching operator receipt.

### P2-1 — Fallback cartridges escape the evidence and gate rules

- **Claim:** Only `selected_cartridge` receives even nominal evidence scrutiny; `fallback_order` is an arbitrary string array with no basis, tier, quota, or gate binding.
- **Hostile scheme:** Select a harmless cartridge but place an unmeasured, over-quota, or operator-forbidden cartridge first in `fallback_order`. A downstream executor follows the fallback after a transport failure and performs a route the decision could not have emitted directly.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:23-29` — “selected_cartridge,” “capability_basis,” “quota_basis,” “fallback_order,” and “operator_gate”; `:51-53` — “emit a decision another system can execute.”
- **Required witness or repair:** Represent each fallback as a complete, independently justified route entry with evidence, quota, and gate basis, or state explicitly that fallback entries are non-executable suggestions requiring a new kernel decision. Add a hostile-fallback witness.

### P2-2 — The process-spawn witness does not establish purity or absence of external effects

- **Claim:** Intercepting `subprocess/exec` alone leaves in-process network clients, native libraries, direct filesystem mutation, and scheduler/database calls unobserved.
- **Hostile scheme:** A kernel implementation calls an HTTP model API through an in-process library or writes scheduler state through a database client. It spawns no process, so the specified spawn harness stays green while the function is not pure and authority separation is lost.
- **Card span:** `policy_kernel_contract_v1/010.100.TASK.md:10-13` — “pure decision function” and “never invokes a model… never modifies scheduler state”; `:47-49` — “No process spawning… any subprocess/exec attempt = FAIL.”
- **Required witness or repair:** Run the kernel in an OS-level capability sandbox with no network, no writable filesystem, no credentials, and no scheduler handles. Treat any external I/O as failure, not only process creation.

## Referee kernel contract

### P1-7 — Preflight failures do not emit a terminal receipt or machine-readable reason

- **Claim:** Several failures occur before `receipt` exists; the CLI prints prose to stderr and returns exit code 2. The reason-code enum is a separate substring classifier, not a field emitted by `tier_runner`.
- **Hostile scheme:** Supply an uncommitted manifest, invalid repository, unsafe scope, or nonempty output directory. `run_task` raises before terminal receipt construction. A host receives an undifferentiated process failure and can relabel or discard it.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:13-14` — “emits exactly one terminal class”; `:26-30` — “specific machine-readable reason, never an undifferentiated exit code” and “Reason codes are a CLOSED enum.”
- **Required witness or repair:** Create the terminal envelope before all fallible preflight work; emit `ERROR` with a schema-enforced closed reason code for every refusal. Integrate codes into production receipts. Add witnesses for every pre-receipt failure path and assert that no prose classifier is needed.

### P1-8 — There is no external freeze authority for base, task, scope, or acceptance

- **Claim:** `run_task` samples `HEAD` and accepts task, files, and acceptance strings at invocation time; it receives no operator-frozen envelope or expected base digest.
- **Hostile scheme:** A compromised host substitutes a different task, scope, acceptance command, or newer `HEAD` immediately before invoking `tier run`. The runner faithfully binds the substituted values and calls them frozen. Witness 3 tests an uncommitted manifest, not drift from an independently supplied frozen base.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:11-12` — “Before dispatch the operator freezes: base commit, allowed scope, task bytes, acceptance command”; `:37` — “Changed base bytes (repo drifted from frozen commit).”
- **Required witness or repair:** Accept one immutable operator-authored envelope digest containing all four values and require the current repository to match it. Add independent substitution witnesses for base, task, scope, and acceptance between freeze and dispatch.

### P1-9 — Hashing command text does not freeze acceptance semantics

- **Claim:** The receipt binds only the shell-command string, not the executable, scripts, PATH resolution, environment, dependencies, network resources, or interpreter bytes used by that command.
- **Hostile scheme:** Freeze `python verify.py`, then replace `verify.py`, alter `PATH`, change an imported package, or make the command query a mutable service before evaluation. The command hash remains unchanged while its predicate changes.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:11-12` — “freezes… acceptance command”; `:21` — “acceptance command cannot silently author the result”; `:35` — “Acceptance-command mutation between freeze and evaluation.”
- **Required witness or repair:** Freeze an executable acceptance specification: argv without shell reinterpretation, executable hash, script/dependency closure, controlled environment, network policy, and working-tree base. Add a witness that mutates a referenced script while preserving the command bytes.

### P1-10 — A verifier may mutate, test, and restore the candidate without detection

- **Claim:** Read-only verification is inferred from equality of the Git diff before and after acceptance, not from prevention or observation of writes.
- **Hostile scheme:** Acceptance saves `app.py`, writes a passing implementation, runs the test, restores the original candidate bytes, and exits zero. The before/after patch is identical, so the runner emits `ACCEPTED` even though the frozen candidate never passed. The existing witness leaves a persistent mutation and misses this scheme.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:21-22` — “acceptance command cannot silently author the result” and “exact candidate tree tested”; `:40` — “Candidate modified BY the verifier → refusal (verifier is read-only).”
- **Required witness or repair:** Execute acceptance over a read-only mounted candidate or instrument all writes, including transient writes, and reject on the first attempted mutation. Add a mutate-test-restore witness.

### P1-11 — Ignored or untracked test inputs can make the tested tree differ from the emitted patch

- **Claim:** `_changed_files` excludes ignored files, and the patch is produced by `git diff HEAD`; an ignored file can affect acceptance without appearing in the patch.
- **Hostile scheme:** The backend changes the scoped source file and creates an ignored configuration or data file needed by acceptance. Tests pass in the worktree; the emitted patch omits the ignored dependency and fails when applied elsewhere.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:22` — “The emitted patch represents the exact candidate tree tested.”
- **Required witness or repair:** Inventory all filesystem entries visible to acceptance, reject undeclared ignored/untracked dependencies, then apply the emitted patch to a fresh detached worktree and rerun acceptance there. Add an ignored-file dependency witness.

### P1-12 — The “restricted packet” is not a security boundary

- **Claim:** The adapter process receives a packet cwd but is not sandboxed. It inherits almost the full environment and can read or write arbitrary filesystem paths, the operator checkout, Git common directory, credentials, or network services.
- **Hostile scheme:** A malicious adapter reads the repository outside declared scope using an absolute path, copies a credential from the environment into model input, and writes the operator checkout directly while still returning a compliant result and scoped packet edit.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:19-20` — “operator checkout remains untouched” and “candidate sees a restricted packet (declared scope only).”
- **Required witness or repair:** Place the adapter/model process in an enforceable sandbox: packet-only readable/writable filesystem, no operator checkout or Git metadata visibility, scrubbed allowlist environment, bounded network, and process containment. Add read-escape and write-escape canaries outside the packet.

### P1-13 — Telemetry and session freshness are self-attested by the backend being judged

- **Claim:** A backend can report arbitrary nonnegative telemetry, set `telemetry_complete: true`, invent a new UUID, and claim the frozen tool versions. The session registry tracks only that reported string.
- **Hostile scheme:** Reuse one long-lived model session for many runs while returning a fresh UUID each time, fabricated token counts, and a passing outcome. The current fixture backend demonstrates that structurally compliant telemetry can be minted without a model.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:23-24` — “Missing telemetry… or reused sessions CANNOT produce `ACCEPTED`.”
- **Required witness or repair:** Require provider/CLI-owned raw receipts or independently captured process evidence bound to the dispatch. Verify actual session creation and telemetry against that source. Add a backend-lies witness for both reused session and fabricated telemetry.

### P1-14 — `tier verify` has no external trust anchor and accepts coherent rewrites

- **Claim:** Artifact hashes are stored in the same mutable receipt they protect; neither the receipt nor its root digest is signed, committed, or supplied independently.
- **Hostile scheme:** Rewrite the receipt, dispatch, prompt, manifest copy, ledger, and patch together; recompute every internal hash; then run `tier verify`. Witness 7 corrupts only one field and proves accidental tamper detection, not resistance to adversarial resealing.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:41` — “Deliberately corrupted receipt → `tier verify` refusal naming the binding.”
- **Required witness or repair:** Publish the closure root digest through an operator-controlled append-only channel or signature before downstream use. `tier verify` must require that external root. Add a coherent full-packet rewrite witness.

### P1-15 — Directory deletion is treated as cleanup even if spawned work survives

- **Claim:** Cleanup checks only whether the packet and worktree paths disappeared; it does not prove termination of descendants, release of credentials, or absence of delayed external writes.
- **Hostile scheme:** The adapter or acceptance command starts a detached child, returns success, and lets cleanup remove both directories. The child later modifies the operator checkout, scheduler, or remote state while the receipt remains `ACCEPTED`.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:23-24` — “failed cleanup… CANNOT produce `ACCEPTED`.”
- **Required witness or repair:** Own the full process/job tree, deny detachment, terminate and verify all descendants, and prove no writable external capabilities remain. Add a detached-child witness with a delayed write canary.

### P2-3 — Verification does not require rejected-run diagnostics to survive

- **Claim:** `verify_run` applies most completeness requirements only to `ACCEPTED`. For `REJECTED`, the entire `acceptance` object and its streams may be deleted without a specific completeness error.
- **Hostile scheme:** Remove failed-acceptance stdout/stderr and the acceptance process record from a rejected receipt, update remaining hashes, and present it as valid negative evidence.
- **Card span:** `referee_kernel_contract_v1/010.100.TASK.md:39` — “Failed acceptance → `REJECTED` with the acceptance output preserved.”
- **Required witness or repair:** Define terminal-class-specific required artifacts and validate them for every state. Add a witness deleting each diagnostic artifact from a rejected run.

## Work receipt contract

### P1-16 — The production validator does not enforce its schema

- **Claim:** `WorkReceiptValidator` never loads `schema.json`; it checks only selected fields and supplies permissive defaults for others.
- **Hostile scheme:** Remove `schema`, `task_id`, `attempt_id`, `predecessor_receipts`, `scope`, `runtime_evidence`, `unlocks`, `blocks`, `external_refs`, and `created_at` from a nominally accepted receipt. The fresh in-memory probe returned `valid: true`.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:14-18` — “binds… the exact task and repository state… execution evidence… resulting state transition”; `:73-76` — “JSON Schema, fail-closed validator.”
- **Required witness or repair:** Run draft-2020-12 schema validation first and fail closed if the dependency is unavailable. Add one missing-field witness for every required property and one unknown-property witness.

### P1-17 — “Known decision” is reduced to 64 lowercase hex characters

- **Claim:** The orphan check neither receives known decisions nor hashes decision bytes; any formatted digest is accepted.
- **Hostile scheme:** Invent `decision_receipt_sha256: "a"*64` with no decision document in the validation packet. The receipt is treated as authorized.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:55-58` — “validator must REJECT… An orphaned decision (receipt citing no known decision hash).”
- **Required witness or repair:** Require the cited decision document in the presented verification set, recompute its canonical digest, validate the decision, and cross-check task, cartridge, and gate bindings. Add absent, wrong-byte, and wrong-task decision witnesses.

### P1-18 — “Unverifiable” content bindings are accepted when their strings look like hashes

- **Claim:** Every `*_sha256` check is format-only; no task envelope, cartridge manifest, patch, or referee specification bytes are required.
- **Hostile scheme:** Populate every hash field with invented 64-hex strings and claim `ACCEPTED`. The supplied “valid” fixtures already use non-resolved hashes and therefore demonstrate syntax, not content binding.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:57-59` — “Missing content binding (any `*_sha256` absent or unverifiable).”
- **Required witness or repair:** Define a verification packet mapping each digest to bytes, recompute all digests, validate each artifact’s own schema, and reject missing objects. Add forged-format-correct hashes for every binding.

### P1-19 — Anyone who can write JSON can mint terminal authority

- **Claim:** There is no receipt issuer, signer, referee identity, append-only root, or independently published receipt digest.
- **Hostile scheme:** A scheduler fabricates an `ACCEPTED/PASS` receipt with plausible hashes, then consumes its own fabrication to close work. The validator cannot distinguish it from a receipt emitted by the referee kernel.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:39-49` — “Committed task envelopes and kernel receipts are AUTHORITATIVE” and scheduler state “may NEVER rewrite… terminal verdict.”
- **Required witness or repair:** Bind receipt issuer and referee identity to a trusted key or operator-controlled append-only log. Verification must start from an external trusted root. Add an unauthorized-issuer witness.

### P1-20 — `scope` does not bind repository identity or allowed paths

- **Claim:** The schema’s `scope` contains only `tier` and `task_type`; it cannot express the declared file scope, repository identity, task bytes, or base tree.
- **Hostile scheme:** Reuse an accepted receipt across two repositories sharing a 40-hex-looking commit or claim that a broad multi-file patch was within a T1 task. Nothing binds the actual allowed paths.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:16-18` — “exact task and repository state”; `:25-27` — “task_envelope_sha256,” “base_commit,” and “scope.”
- **Required witness or repair:** Add repository identity, object format, base tree digest, ordered allowed paths, and task-envelope cross-binding. Verify the patch touches only those paths. Add cross-repository replay and scope-escape witnesses.

### P1-21 — Predecessor membership is not hash linkage and cycles are not rejected

- **Claim:** The validator checks whether a predecessor string is a key in caller-supplied `known_receipts`; it does not recompute that receipt’s hash, validate its contents, establish successor semantics, or detect cycles.
- **Hostile scheme:** Map a demanded predecessor hash to unrelated bytes, or submit A keyed as B’s predecessor and B keyed as A’s predecessor. Both references are “present” despite no valid DAG.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:61-66` — “receipts form a DAG and the validator checks hash-linkage.”
- **Required witness or repair:** Recompute canonical receipt hashes, recursively validate presented predecessors, enforce acyclicity, and verify that successor effects authorize the child task. Add wrong-content, self-cycle, two-node-cycle, and unrelated-task witnesses.

### P1-22 — Duplicate terminal detection is optional caller testimony

- **Claim:** Duplicate detection sees only `all_receipts_for_attempt`, which defaults to empty, and counts every terminal receipt supplied without filtering by the target `attempt_id`.
- **Hostile scheme:** Validate two terminal receipts separately with the default arguments; both pass. Conversely, place two unrelated attempts in the supplied list and falsely reject one as a duplicate.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:60` — “Duplicate terminal receipts for one `attempt_id`.”
- **Required witness or repair:** Validate a complete presented set, group receipts internally by exact attempt identity, and fail closed when uniqueness cannot be established. Add separately validated duplicates and unrelated-attempt controls.

### P1-23 — External authority can be smuggled through any spelling except nested `verdict`

- **Claim:** The override check rejects only a dictionary value containing the exact key `verdict`; ordinary strings, alternate names, top-level fields, and scheduler instructions pass. The validator also does not enforce the schema that would prohibit some of these shapes.
- **Hostile scheme:** Set `external_refs.bead_id` to “scheduler says ACCEPTED and close now,” use `scheduler_decision`, or add a top-level `external_verdict`. The fresh string-override probe passed.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:43-49` — external references “are DESCRIPTIVE” and “never acquire authority over the verdict”; `:68-69` — “Any external system claiming to override the referee verdict.”
- **Required witness or repair:** Use opaque typed identifiers only; prohibit free-form directives; enforce schema; and make adapters consume only kernel-owned terminal fields. Add alternate-key, string-encoded, and top-level override witnesses.

### P1-24 — Scheduler effects can silently fail open or contradict each other

- **Claim:** Resolution occurs only when `all_task_ids` is nonempty. The validator permits the same task in both `unlocks` and `blocks`, duplicates, self-effects, and unlocks from `REJECTED` or `ERROR`.
- **Hostile scheme:** Validate with the default constructor and name nonexistent tasks, or emit `ERROR/PASS` with a chosen task in both arrays. A host can project whichever effect benefits it.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:50-52` — “`unlocks`/`blocks` express logical successor effects” and a host projects effects from the “VERIFIED receipt”; `:67` — effects must be “resolvable to task_ids.”
- **Required witness or repair:** Require the authoritative task-envelope set, enforce uniqueness/disjointness/no-self-reference, and define terminal-state-specific effect rules. Add nonexistent-default, overlap, duplicate, self-effect, and rejected-unlock witnesses.

### P2-4 — `ERROR` paired with `PASS` is declared logically consistent

- **Claim:** Contradiction checks constrain only `ACCEPTED` and `REJECTED`; `ERROR` may carry either `PASS` or `FAIL`.
- **Hostile scheme:** Emit `terminal_state: ERROR`, `referee_result: PASS`, then let one consumer act on `PASS` while another acts on `ERROR`. The fresh probe returned valid.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:59` — “Contradictory terminal states in one receipt.”
- **Required witness or repair:** Replace independent scalars with one closed terminal union, or define an explicit truth table where `ERROR` has no referee verdict. Add every Cartesian-product witness.

### P2-5 — Runtime evidence is an unauthenticated description

- **Claim:** `runtime_evidence.execution_log` may be any string described as a “Path or hash,” and `model_used` is an unverified claim. No telemetry completeness, session, adapter, process result, or content digest is required.
- **Hostile scheme:** Claim a prestigious model and set `execution_log: "missing.txt"` while presenting invented token counts. The receipt remains structurally valid.
- **Card span:** `work_receipt_contract_v1/010.100.TASK.md:16-18` — binds “cartridge execution evidence”; `:28-31` — “runtime_evidence,” “patch_sha256,” and “referee_spec_sha256.”
- **Required witness or repair:** Make runtime evidence a closed object of content-addressed artifacts with provider/adapter provenance and completeness predicates. Add missing-log, wrong-hash, false-model, reused-session, and fabricated-telemetry witnesses.

## Gas Town / `tier run` smoke contract

### P1-25 — Phase 1 can pass wrong values and does not target the real `tier run` CLI

- **Claim:** `verify_capture.py` checks only that four synthetic flags exist and are followed by a non-flag. It checks neither exact expected bytes nor the real `tier run` flag names.
- **Hostile scheme:** Deliver attacker-controlled values under `--task-text`, `--repo-path`, `--file-scope`, and `--acceptance-command`; duplicate flags; swap values; append shell payloads; or invoke an unrelated executable. The verifier prints PASS. Actual `tier run` uses `--task`, `--repo`, `--files`, and `--acceptance`.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:28-31` — “proves: task text, repository path, file scope, and acceptance command reach the intended `tier run` flags without shell reinterpretation or dropped fields.”
- **Required witness or repair:** Capture the exact executable and argv vector, compare byte-for-byte against frozen expected argv and hashes, reject duplicates/extras, and use the production flag vocabulary. Add wrong-value, duplicate, reordered, injected, wrong-executable, and shell-roundtrip witnesses.

### P1-26 — The self-test bypasses Gas Town entirely

- **Claim:** `selftest.py` directly invokes `capture_fixture.py`; it proves only that the capture and verifier scripts agree with themselves.
- **Hostile scheme:** Keep the Gas Town preset broken or unused while running the direct self-test and presenting `PHASE1-SELFTEST OK` as transport evidence.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:28-30` — “A local argument-capture fixture receives the Gas Town-generated invocation.”
- **Required witness or repair:** The phase-one acceptance command must start at the pinned `gt` executable and end at the capture fixture, preserving an independently recorded process chain. Direct invocation may remain a unit test but cannot satisfy the gate.

### P1-27 — The capture fixture exports almost the entire environment

- **Claim:** Redaction depends only on environment-variable names containing `KEY`, `TOKEN`, or `SECRET`; password, cookie, authorization, session, credential-file, and provider-specific variables can be serialized verbatim.
- **Hostile scheme:** Place a live credential in `PASSWORD`, `GH_AUTH`, `AWS_PROFILE`, `COOKIE`, or an innocuous variable name. Gas Town invokes the fixture, which writes it to the capture JSON while the run claims credential custody.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:50` — “official model CLI retained custody of authentication”; `:88-93` includes “credential exposure” as a no-go class.
- **Required witness or repair:** Capture an allowlisted environment projection, not a redacted copy of all variables. Use secret canaries under diverse names and inspect argv, environment, files, logs, and child processes for leakage.

### P1-28 — The nine-fact closure packet has no machine contract or trust root

- **Claim:** The card lists nine prose facts but defines no packet schema, canonicalization, required artifacts, issuer, external root digest, or verifier.
- **Hostile scheme:** Assemble screenshots and hand-written JSON asserting each fact, omit contradictory raw artifacts, and call the bundle one closure packet. Nothing determines whether all evidence belongs to the same invocation.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:45-57` — “Pass requires ALL NINE facts evidenced in one closure packet.”
- **Required witness or repair:** Define a content-addressed closure manifest binding the Bead claim, Gas Town launch, CLI process, `tier run` directory, receipt, patch, verifier output, and final scheduler transition to one attempt. Require an independently published root digest and a fail-closed verifier.

### P1-29 — “One live invocation” does not bound actual provider calls or retries

- **Claim:** Counting a Gas Town or model-CLI process launch does not prove only one subscription-backed model request occurred.
- **Hostile scheme:** Gas Town retries after a timeout, the CLI resumes or internally retries, or the adapter performs multiple API calls but returns one aggregate result. The outer command count remains one.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:3-4` — “authorized exactly ONE live model dispatch”; `:33-34` — “ONE live subscription-backed T1 invocation”; `:97-98` — “One live model call TOTAL.”
- **Required witness or repair:** Define the counted event at the provider/CLI receipt level, disable retries, require complete raw call telemetry, and stop on ambiguity. Add a fixture simulating two internal calls under one process.

### P1-30 — Authentication custody is not established by the absence of one dangerous flag

- **Claim:** A flag-free command line does not show who read, copied, injected, cached, or logged authentication.
- **Hostile scheme:** Gas Town reads the credential file or environment and forwards a token to a wrapper, while launching the official CLI without `--dangerously-skip-permissions`. The concrete check passes although custody was transferred.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:50` — “The official model CLI retained custody of authentication.”
- **Required witness or repair:** Define custody observably: only the official CLI may open the credential path or receive the secret handle; wrappers and Gas Town receive no credential bytes. Use unique canary credentials and file/process access tracing.

### P1-31 — An accepted receipt is not cryptographically or atomically coupled to Bead closure

- **Claim:** The card requires receipt-authorized closure and retained path/digest but does not define an atomic compare-and-set over Bead identity, claim owner, attempt, receipt digest, and current state.
- **Hostile scheme:** Close Bead B using Bead A’s accepted receipt, race a stale accepted receipt against a newer rejected attempt, or close after the verified artifact at the stored path has been replaced.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:54-56` — “The ACCEPTED RECEIPT… authorized the Bead closure” and “The Bead retains the receipt path and digest.”
- **Required witness or repair:** Require an atomic closure operation conditioned on bead ID, claim generation, attempt ID, terminal state, verified receipt digest, and current scheduler revision. Add wrong-bead, stale-attempt, replaced-path, and concurrent-closure witnesses.

### P2-6 — The provider-free negative run is under-specified

- **Claim:** The card does not freeze the injected failure, backend behavior, expected reason, or exact Bead transition.
- **Hostile scheme:** Run an obviously nonexistent command, receive a generic process error, leave an unrelated Bead open, and claim rejection semantics are proven without exercising failed acceptance after a real candidate patch.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:59-64` — “One run whose acceptance intentionally fails… preserve diagnostics, and leave the Bead open or explicitly blocked.”
- **Required witness or repair:** Freeze a provider-free backend that emits a real scoped patch and complete telemetry, then make only the acceptance predicate fail. Require a specific terminal class, reason, diagnostic hashes, and unchanged claimed Bead generation.

### P2-7 — Vendored external-belief excerpts lack a frozen manifest

- **Claim:** The card asks for exact preset bytes and documentation excerpts but does not require a canonical inventory binding every relied-upon excerpt, source location, and byte digest.
- **Hostile scheme:** Vendor favorable excerpts, omit conflicting surrounding text, or edit the excerpt after the run while retaining the preset hash. Later adjudication cannot prove what documentation set controlled the experiment.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:66-73` — “vendor into this crate the exact preset bytes AND excerpts… so a later pass/fail is adjudicated against what was believed at freeze time.”
- **Required witness or repair:** Freeze a manifest containing source URL/release, document path, exact byte range or complete file, SHA-256, retrieval evidence, preset hash, and a root digest committed before phase 1.

### P2-8 — “No automatic apply or merge” can be satisfied by apply-then-revert

- **Claim:** A final clean checkout or absent merge commit does not prove that automation never applied, pushed, or merged the patch transiently.
- **Hostile scheme:** Gas Town applies the patch, runs another action, then reverts it before evidence capture; or pushes and deletes a remote branch. Net-state inspection reports no patch applied or merged.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:57` — “No patch was automatically applied or merged.”
- **Required witness or repair:** Instrument Git/worktree/remote mutation events, use a protected disposable repository that rejects writes outside `tier run`, and record append-only refs before and after. Add apply-then-revert and push-delete witnesses.

### P2-9 — “Substantive wrapper logic” has no adjudicable boundary

- **Claim:** The integration seam permits fixed arguments and a dynamic task field but gives no objective limit separating a preset from a custom worker framework.
- **Hostile scheme:** Put parsing, retries, state management, receipt selection, and closure logic in a shell/Python command referenced by `settings/agents.json`, then claim it is merely a preset because Gas Town still launches it through the public CLI.
- **Card span:** `gastown_tier_run_smoke_v1/010.100.TASK.md:21-24` — “without substantive wrapper logic” and “not permission to build a custom worker framework.”
- **Required witness or repair:** Freeze an allowlisted adapter shape: exact executable plus static argv substitution only, no loops, retries, scheduler writes, receipt adjudication, or persistent state. Hash and inspect the complete invoked program closure.

## Missing negative-witness inventory

### Policy kernel

- Measured basis with hypothesis-only evidence.
- Measured basis with invented evidence reference.
- Measurement for the wrong task tier.
- Measurement for a different cartridge.
- Evidence-index bytes changed while all existing output hashes remain fixed.
- Cross-task replay of `NO_DECISION`.
- Snapshot age omitted from validator context.
- Kernel enlarges its own `snapshot_max_age`.
- Secret value with no credential keyword.
- Encoded or provider-specific secret.
- Credential-bearing object key with non-string value.
- Fabricated operator approval.
- Unmeasured or forbidden executable fallback.
- In-process network/model call with no subprocess.
- Direct scheduler or filesystem side effect with no subprocess.

### Referee kernel

- Every preflight failure must still emit a terminal receipt and closed reason code.
- Operator-frozen base replaced before invocation.
- Operator-frozen task, scope, or acceptance replaced before invocation.
- Referenced acceptance script changes while command bytes remain fixed.
- PATH/interpreter/dependency mutation.
- Acceptance mutate-test-restore.
- Acceptance uses an ignored file absent from the patch.
- Patch applied to a fresh clone and acceptance rerun.
- Backend reads outside packet scope.
- Backend writes the operator checkout directly.
- Credential/environment escape from backend sandbox.
- Backend fabricates telemetry.
- Backend reuses a real session while reporting a new identifier.
- Coherent rewrite of receipt and all bound artifacts.
- Detached child survives cleanup and performs a delayed write.
- Rejected receipt missing stdout, stderr, acceptance record, or patch diagnostics.

### Work receipt

- Missing each schema-required field.
- Unknown top-level and nested fields.
- Format-correct but absent decision hash.
- Decision bytes hash mismatch.
- Decision bound to a different task or cartridge.
- Format-correct but absent task, manifest, patch, or referee bytes.
- Unauthorized receipt issuer.
- Cross-repository receipt replay.
- Patch outside declared path scope.
- Predecessor key mapped to wrong bytes.
- Self-cycle and multi-node cycle.
- Predecessor unrelated to the successor task.
- Duplicate terminal receipts validated separately.
- Unrelated attempts supplied to duplicate detection.
- String-encoded, alternate-key, and top-level external overrides.
- Scheduler effects checked without a task registry.
- Overlapping, duplicate, self-referential, and rejected-state effects.
- Complete terminal-state/referee-result truth table.
- Missing or false runtime evidence.

### Gas Town smoke

- Wrong value under every expected transport flag.
- Duplicate, extra, reordered, shell-reinterpreted, and dropped flags.
- Wrong executable with superficially correct flags.
- Direct fixture invocation presented as Gas Town transport.
- Credential canaries under non-keyword environment names.
- Nine individually plausible artifacts from different attempts combined into one packet.
- Two provider calls hidden under one process invocation.
- Gas Town or wrapper reads credential bytes before official CLI launch.
- Wrong-Bead, stale-attempt, replaced-receipt, and concurrent closure.
- Negative run that fails acceptance only after producing a real candidate.
- Omitted or post-edited vendored documentation.
- Apply-then-revert and push-then-delete.
- Preset-referenced wrapper containing retry, state, or verdict logic.

## Review burden packet

```yaml
requested_outcome: "Reject promotion or implementation unblocking of all four frozen cards pending repair and hostile-witness closure."
claimant: "The driver or contract proponent asserting that the frozen cards and current crate implementations preserve authority separation, evidence integrity, custody, and fail-closed semantics."
authority:
  - "experiments/breadth/crates/policy_kernel_contract_v1/010.100.TASK.md"
  - "experiments/breadth/crates/referee_kernel_contract_v1/010.100.TASK.md"
  - "experiments/breadth/crates/work_receipt_contract_v1/010.100.TASK.md"
  - "experiments/breadth/crates/gastown_tier_run_smoke_v1/010.100.TASK.md"
  - "Their crate-local schemas, validators, fixtures, and witnesses"
  - "Relevant tier_runner production source and receipt schemas"
predicates:
  authority_separation: "Policy cannot award operator authority; schedulers cannot mint or override verdicts; verifier and executor remain distinct."
  evidence_integrity: "Every asserted digest resolves to exact presented bytes and to an independently trusted root."
  custody: "Restricted packets, credentials, sessions, receipts, and external beliefs remain under the authority named by the cards."
  fail_closed: "Every missing, ambiguous, stale, unverifiable, duplicated, contradictory, or escaped condition yields a terminal machine-readable refusal."
  exactness: "The emitted patch is the complete tree tested, and closure effects bind the same task, attempt, and receipt."
burden_holder: "Contract claimant; not the reviewer, scheduler, model, or downstream consumer."
evidence:
  source_review: "Fresh read-only inspection of the four cards, crate-local implementations, fixtures, seven referee witnesses, tier_runner/core.py, tier_runner/manifest.py, CLI, and receipt schemas."
  live_probe: "Read-only python -B in-memory validator calls."
  observed_probe_results:
    - "Policy measured decision with hypothesis-only evidence: accepted."
    - "Policy decision without supplied stale age: accepted."
    - "Policy credential-shaped bypasses: accepted."
    - "Work receipt missing most required context: accepted."
    - "Work receipt with ERROR/PASS: accepted."
    - "Work receipt with scheduler override encoded as text: accepted."
verifier: "Independent desk/operator rerunning each hostile witness from immutable inputs and requiring machine-readable outputs plus independently rooted artifacts."
gap: "Forty findings remain open: 0 P0, 31 P1, 9 P2. Existing positive fixtures and narrow negative witnesses do not close the listed hostile schemes."
closure_decision: "CHANGES_REQUESTED_BEFORE_PROMOTION; current cards are refuted as sufficient contracts."
failure_default: "Remain implementation-blocked; mint no PASS, ACCEPTED, capability verdict, scheduler transition, or retry authority from these cards."
```

## Severity counts

- P0: 0
- P1: 31
- P2: 9
- Total: 40

END-FULL-REFUTATION