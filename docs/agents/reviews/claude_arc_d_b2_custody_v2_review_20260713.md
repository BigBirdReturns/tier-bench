# Cross-engine adversarial review — PR #89 (ARC-D B2 custody-v2 components)

Reviewer: Claude lane (driver), 2026-07-13. Subject: `codex/arc-d-b2-custody-v2`
at exact head `cf9590a`. Method: full read of the validator (916 lines), auth
verifier, all schemas, runbook; executable witnesses run in a worktree at the
exact head against the PR's own functions; their suite re-run (10/10).
Disposition: **CHANGES_REQUESTED_BEFORE_READY** — no P0; two P1; one P2.

## P1 findings (both are named amendment requirements left unenforced)

**P1-1 — The preregistration→packet identity chain is unenforced end to end.**
The amendment's implementation_gate requires a "batch validator binding both
lanes to the parent charter's exact per-item prompt/response hashes and
identical packet hashes." Executable witness at `cf9590a`: a schema-conformant
3×2 batch whose grade_a receipts carry packet hash `aaa…` and grade_b receipts
carry `bbb…` for the SAME items **passes `validate_batch` with zero errors**.
Specifically missing:
- no code path compares receipt/manifest `packet_sha256` to the preregistered
  per-item `items.{item}.packet_sha256` (the preregistration schema carries it
  and even carries `same_packet_required_in_both_lanes` — the flag is never
  enforced against actual receipts);
- `validate_batch` never checks per-item cross-lane packet identity;
- `validate_batch` never checks receipts' prompt/response hashes against the
  parent charter (only attempt-level `common` keys are compared).
Fix: batch mode takes the preregistration (bytes it already binds by hash) and
enforces, per item: receipt.packet == prereg.packet (both lanes), and
receipt.prompt/response == charter's sealed values.

**P1-2 — Dispatch-ledger canonicality: forked revision chains validate, and
commit bindings are decorative.** Witnesses at `cf9590a`:
- two DIVERGENT revision-1 children of the same revision-0 (one cell COMPLETED
  vs REFUSED) — **both validate**; nothing establishes a unique successor, so
  an operator could fork, dispatch twice, and later present the favorable
  chain (dispatch-shopping through the append-only letter of the law);
- `previous_ledger_commit` set to an arbitrary 40-hex — **accepted**; the
  validator never verifies the commit contains the previous ledger bytes;
- `preregistration_commit` likewise never content-verified.
The hash chain is genuinely append-only pairwise; the gap is fork-choice and
commit-content binding. Fix: verify `previous_ledger_commit:path` bytes equal
the provided previous ledger via git; require each revision to reach the
default branch before the next dispatch (runbook states the chain lives
publicly — make the validator check ancestry: previous commit must be an
ancestor of the current ledger's commit), and document that exactly one child
per revision is lawful with any second observed child voiding the attempt to
PARTIAL_UNPAIRED.

## P2

**P2-1 — `activation --official` trusts the local remote.** The official gate
compares HEAD to local `refs/remotes/origin/main` and the branch name; a
checkout whose `origin` points at a doctored fork satisfies every check and
reaches `ACTIVE_FOR_FRESH_V2_GRADING`. Mitigations that fit the design: bind
the canonical repository identity (allowlisted remote URL, or tie official
mode to the OIDC `--source-digest` path so activation is attested by the
GitHub-hosted workflow), or state in the runbook that official mode is valid
only as executed by the named CI workflow.

## Verified sound (the other named gates)

- **Exact private Git objects, no checkout substitution**: `git_bytes` demands
  a full 40-hex commit and `cat-file blob commit:rel` with NO working-tree
  fallback; `_safe_rel` blocks traversal/absolute/backslash; artifact escape
  from the bundle directory is caught. (The CRLF working-tree fallback exists
  only for PUBLIC component refs when `ref=None`, which the CLI cannot reach.)
- **Terminal-cell immutability within a chain**: rewriting a non-NOT_DISPATCHED
  cell errors; sealed ledgers are terminal; SEALED_COMPLETE requires six
  COMPLETED; sealed attempts cannot retain NOT_DISPATCHED; empty revisions
  rejected.
- **Role/venue inequality**: custodian≠verifier, coordinator≠verifier, lane
  venues distinct, preflight venue/profile match, readback==sentinel.
- **Auth delegation is real and fail-closed**: `gh attestation verify` with
  main-branch cert identity + `--deny-self-hosted-runners` + optional source
  digest; signed-commit path pins VALIDSIG fingerprint and verifies the commit
  contains the exact audit bytes.
- **No public-only admission**: every public success string is a
  COMMITMENT_SHAPE state; `ADMITTED` appears nowhere; audit PASS requires
  raw_bytes_accessed and the empty error commitment; public receipts' forbidden
  key walk extended with private_path/credential/token.
- Their suite: 10/10 at head; witnesses were run against the same modules.

## Conflict disclosure

Unchanged from #85/#88: this lane runs grade_b under the resulting law; the
stricter the admission chain, the more work my lane redoes. All findings push
toward stricter.
