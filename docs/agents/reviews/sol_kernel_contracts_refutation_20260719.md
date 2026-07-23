# Sol refutation — kernel-contract cards (2026-07-19)

*Authored by gpt-5.6-sol via codex exec (read-only sandbox, stdout transport). Bytes committed verbatim (surviving portion) by the Claude desk with attribution.*

*TRANSPORT DEFECT, recorded honestly: the dispatching desk piped codex stdout through tail -N, truncating the head of this review. What follows is the SURVIVING portion; the beginning is lost and NOT reconstructed. Severity counts at the end are Sol's own and cover the full original. Future stdout-transport dispatches capture to file, never through tail.*

Required fields: successor-policy hash, derivation rule/version, effect namespace, terminal-state-to-effect mapping, causal decision/referee receipt hashes, and an explicit `NO_EFFECTS` default.

## P1-11 — runtime and referee evidence can be self-asserted inside a valid receipt

The minimum work-receipt fields include opaque `runtime_evidence` and embedded `referee_result`; only `referee_spec_sha256` is named. There is no mandatory referee-receipt hash, candidate-tree hash, acceptance-output binding, runtime manifest, raw provider result, validator identity, or work-receipt self-hash.

A hostile implementation can use:

```json
{
  "runtime_evidence": {"telemetry_complete": true},
  "referee_result": "ACCEPTED",
  "terminal_state": "DONE"
}
```

while supplying valid hashes for unrelated or synthetic bytes. The receipt is structurally complete without portable proof of execution or verdict.

Required negative witness: self-reported runtime evidence and an unbacked embedded `ACCEPTED` must fail.

Required bindings include dispatch receipt, call ledger, raw provider result or explicit absence class, runtime/adapter identity, candidate patch and tree, referee receipt, acceptance stdout/stderr/exit, cleanup receipt, validator implementation, and canonical work-receipt digest.

## P1-12 — the one-call authorization is not bound to the dependency bytes selected after authorization

Smoke lines 3–7 record broad operator authorization, while lines 9–13 and 97 require the executor to choose and pin `gt`, `bd`, model CLI, adapter, preset, task, and acceptance bytes later.

A hostile administrator can select a modified but version-labelled dependency or permissive preset, hash it, and claim it falls under the earlier authorization. Pinning after selection proves identity, not prospective approval of that identity.

Required witness: substitute different dependency or preset bytes under the same displayed version and require phase 2 to remain unauthorized.

Before the live call, an authenticated operator/adoption record must bind one complete execution manifest: exact source/package hashes, resolved executable hashes, adapter source hash, preset, task, acceptance, repository, environment policy, and call ceiling.

## P1-13 — `ERROR` can satisfy the negative run without proving rejection semantics

Smoke lines 59–64 allow the intentionally failing acceptance run to return either `REJECTED` or `ERROR`. An adapter crash before acceptance, missing executable, malformed receipt, or cleanup failure can therefore satisfy the stated terminal-class requirement while proving nothing about failed-acceptance behavior.

The prose says phase 2 must not spend a token if rejection semantics are broken, but the machine predicate permits exactly that uncertainty.

Required witness: force an adapter error before acceptance and confirm phase 2 remains blocked.

A passing negative gate must prove the frozen acceptance command actually ran, returned the intended nonzero status, preserved diagnostics, yielded the specific `REJECTED` reason, and caused no closure. `ERROR` is useful evidence but must be a failed gate/no-go, not an acceptable negative witness.

## P1-14 — the smoke can reconstruct a passing final snapshot without proving causal closure

The nine facts do not specify an append-only event chain, transition IDs, compare-and-swap values, or a closure-packet schema. Final state alone cannot prove ordering or causality.

A compliant-looking run can close the Bead on process exit, reopen it before inspection, then close it again manually after attaching the accepted receipt. The final Bead retains the path and digest, and prose can say the receipt “authorized” closure. The premature-closure no-go is hidden by the reconstructed final state.

Required witnesses:

- close then reopen before evidence capture;
- close using the wrong receipt and later replace the digest;
- attach the correct digest after an unrelated manual close;
- mutate the Bead between atomic claim and dispatch.

Required evidence: raw scheduler events with before/after state hashes, monotonic sequence, claim token, actor/surface, exact receipt digest in the closure transition, and a verifier that replays the transition. The closure packet itself needs a closed schema, artifact manifest, canonical hash, and independent verifier result.

## P1-15 — authentication custody and the one-dispatch ceiling are labels, not measured boundaries

“Official model CLI retained custody of authentication” does not establish that Gas Town, the preset, child environment, logs, crash dumps, or scheduler never observed credentials. Running the official CLI while copying its token from the environment still satisfies the literal wording.

Likewise, one Gas Town launch can trigger CLI retries, multiple provider requests, resumed sessions, or wrapper-level redispatch. “One live model dispatch” is not tied to provider request IDs or a complete attempt ledger.

Required negative witnesses:

- plant credential canaries in environment/config and prove they do not reach Gas Town, preset logs, argv, receipts, or model context;
- force a retryable provider failure and verify no second provider attempt;
- attempt session reuse/resume;
- make Gas Town launch the configured command twice.

Required fields: sanitized environment manifest, credential-owner process identity, resolved executable chain, per-request IDs and timestamps, fresh session ID, retry count, total provider-attempt count, raw CLI result hash, and a fail-closed equality check against the authorized ceiling of one.

# P2 findings

## P2-01 — “scan all string values” is neither a credential type system nor a complete witness

Policy lines 45–46 allow string scanning to carry the no-credentials invariant. Credentials can be split across fields, encoded, placed in byte arrays, represented as a file/secret-store locator, hidden in error output, or passed through ambient state. Pattern scanners also risk rejecting harmless hashes while missing novel token formats.

Add structured secret-bearing-field prohibition, taint-aware fixtures, nested/encoded/split-token witnesses, and scans over diagnostics and serialization outputs. Secret references should be typed, non-dereferenceable identifiers if they are allowed at all.

## P2-02 — determinism and temporal canonicalization are internally ambiguous

Policy lines 35–36 say byte-identical modulo `decision_id`, although `decision_id` is itself deterministic. Lines 65–67 detach `observed_at`, creating a second implicit exception. Canonical JSON, Unicode normalization, number encoding, key order, schema version, and policy implementation identity are not frozen.

The same four semantic inputs can therefore acquire multiple byte encodings, or a changed policy can emit a different route under the same input-derived ID.

Bind canonicalization profile, schema hash, policy implementation hash, full output digest, and an explicit list of non-authoritative display fields. Prefer no determinism exceptions in the authority-bearing object.

## P2-03 — a closed reason enum can still conceal the controlling failure

The referee card requires specific closed reason codes but does not define state/reason compatibility, multi-fault precedence, or whether all detected failures must be preserved.

A candidate with scope escape, telemetry loss, and failed acceptance can be reported only as a benign acceptance failure, hiding the authority-relevant scope violation while remaining inside the enum.

Freeze ordered precedence, require `primary_reason` plus complete `reasons[]`, bind each reason to evidence paths, and add multi-fault witnesses. `ACCEPTED` must require an empty reason set; `REJECTED` and `ERROR` should have disjoint controlling classes.

## P2-04 — `external_refs` uses a field-name blacklist where a closed descriptive type is required

Work-receipt line 68 rejects an external reference carrying a `verdict` field. A hostile reference can carry `status: ACCEPTED`, `result`, `closure_instruction`, a verdict in a URL query, or prompt-injection text later rendered into a model/chat surface.

Define a closed tagged union containing only system kind, opaque identifier, immutable locator/digest where available, and display-safe metadata. Reject free-form instructions and verdict synonyms. Adapters must treat references as quarantined data and never render them as authority-bearing prompts.

## P2-05 — task, attempt, repository, time, and path identities are not portable namespaces

`task_id` and `attempt_id` can collide across repositories. `base_commit` does not state repository/authority domain. `created_at` is self-asserted. Receipt paths retained by Beads can be relative, host-local, mutable, or later point to different bytes.

Add authority namespace, repository identity/object format, content-derived attempt identity, receipt digest, issuer, observed/recorded times with source, and immutable artifact-store identity. Paths remain display locators only.

## P2-06 — phase 1 lacks the hostile transport matrix needed to prove “no shell reinterpretation”

One friendly argument capture does not establish the line-30 guarantee. The dynamic task and path fields need fixtures containing spaces, quotes, newlines, leading dashes, Unicode, CRLF, shell metacharacters, percent expansion, empty strings, duplicate flags, and oversized values.

The smoke also leaves “substantive wrapper logic” undefined and permits selectively vendored documentation excerpts. Freeze the exact argv array, resolved executable, cwd, environment allowlist, encoding, duplicate-flag policy, wrapper boundary, upstream source URL/version/hash, and relied-upon document spans. A doc excerpt should preserve its surrounding constraints, not only the favorable sentence.

# Missing negative-witness inventory

The current cards should not be considered adversarially closed until fixtures cover at least:

1. Unauthorized local commit as the authority root.
2. Evidence-index substitution under an unchanged policy decision.
3. Self-graded, mismatched, partial, contaminated, stale, and K-insufficient “measurement.”
4. Unmeasured fallback execution and unsatisfied operator gate.
5. In-process network/model/environment/file access by the policy kernel.
6. Kernel-selected staleness window or observation time.
7. Post-authorization task/acceptance substitution.
8. Candidate modification of verifier dependencies.
9. Verifier network, model, scheduler, or out-of-evidence writes.
10. Acceptance depending on an ignored file omitted from the patch.
11. Contradictory terminal receipts validated in separate presented subsets.
12. Terminal authority or scheduler effects with `UNVERIFIED_PREDECESSOR`.
13. Unrelated unlock/block injection and effects from rejected/error receipts.
14. Self-reported runtime/referee success without underlying receipts.
15. Same displayed external version with substituted executable/preset bytes.
16. Adapter failure incorrectly satisfying the provider-free negative gate.
17. Close/reopen/reclose and post-hoc receipt attachment.
18. Credential canaries reaching child environment, argv, logs, receipt, or prompt.
19. Hidden retry, double launch, or session resume under the one-dispatch budget.
20. Shell/argv transport metacharacter and encoding cases.
21. Multi-fault referee failures with deterministic reason precedence.

# Evidence-laundering fields missing across the cards

At minimum, the combined chain lacks mandatory, consistently defined fields for:

- authority namespace and authenticated adoption/authorization receipt;
- authoritative repository identity and approved commit;
- producer/kernel/referee/validator implementation hashes;
- complete four-input policy binding, especially `evidence_index_sha256`;
- evidence-entry disposition, K, task/runtime/referee bindings, independence, and expiry;
- per-fallback capability/quota basis and gate receipt;
- freeze receipt for task, scope, acceptance, and transitive referee closure;
- candidate-tree hash and clean-base patch-replay result;
- referee receipt and acceptance stdout/stderr/toolchain/environment bindings;
- receipt-set coverage/history root and verified-predecessor closure;
- successor-policy hash and terminal-to-effect derivation;
- work-receipt self-digest, issuer, and verification receipt;
- closure-transition event ID, before/after scheduler hashes, claim token, and actor;
- sanitized environment/authentication-custody evidence;
- complete provider-attempt ledger, request IDs, retry count, and session freshness;
- immutable artifact-store identity rather than a path alone.

# Epistemic and execution boundary

This review inspected the frozen cards and relevant existing runner source under a read-only mandate. It did not modify the worktree, create fixtures, run a provider, install Gas Town/Beads, or exercise scheduler state.

The ignored-file patch seam is a static source construction, not a reproduced execution. All other schemes are models of what the frozen words permit, not claims about an implementation’s observed behavior.

The correct failure default is therefore:

- contract review: complete;
- sufficiency claim: denied;
- kernel implementation authority: unchanged and still blocked by the queue;
- phase-2 smoke result: no PASS may be inferred from these cards;
- benchmark/capability verdict: none;
- remediation: proposal-only until operator disposition.

# Review burden packet

- requested outcome: find implementations that satisfy the four frozen cards’ letter while violating authority separation and evidence integrity
- claimant: Sol cross-engine adversarial reviewer
- authority: the four exact card blobs and source commit listed above; committed queue/protocol govern lane and scope
- predicates: inspect each card for authority leaks, hostile ambiguities, missing negative witnesses, and laundering-enabling omissions; do not write or dispatch
- burden holder: whoever implements the kernels, runs phase 2, or projects a verified receipt into scheduler state
- evidence: this review, cited card spans, and the source-inspected existing runner seam
- verifier: construct the listed negative witnesses prospectively and require named fail-closed results
- gap: no fixture was written or executed during this read-only pass; proposed repairs remain gated
- closure decision: adversarial review complete; contract sufficiency refuted pending per-finding disposition
- failure default: no implementation, scheduler authority, smoke PASS, or product-boundary claim follows from the frozen cards alone

# Severity counts

- **P0: 0**
- **P1: 15**
- **P2: 6**
- **Total: 21**
