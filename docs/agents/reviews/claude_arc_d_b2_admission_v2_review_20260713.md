# Cross-engine adversarial review — PR #85 (ARC-D B2 private-custody admission v2)

Reviewer: Claude lane (driver), 2026-07-13. Subject: `codex/arc-d-b2-admission-v2`
at `7d5266f`. Method: full read of the amendment, all five schemas, validator,
and tests; executable witnesses run against the PR's own `schema_errors`
engine. Disposition: **CHANGES_REQUESTED_BEFORE_RATIFICATION** — no P0; two P1
admission loopholes in interfaces that the amendment's own versioning rule will
freeze at activation; four P2s.

Conflict disclosure: this reviewer's lane authored grade_b attempts 1–3. The
amendment kills the attempt-3 attrs receipt (no grandfathering). That is
against this lane's interest and is **endorsed** — it is the correct call.

## P1 findings

**P1-1 — The batch receipt schema cannot enforce 3×2 completeness.**
`receipts` is `minItems:6, maxItems:6` with per-entry lane/item enums, no
`uniqueItems`, and no per-combination constraint. Executable witnesses (run
against the PR's own engine):
- six copies of the SAME (grade_a, attrs) entry → **SCHEMA-VALID**;
- both lanes covering only attrs+3614 with doubled entries, ipv6 never graded
  → **SCHEMA-VALID**.
The prose says "One batch receipt proves 3×2 completeness"; the committed
interface proves count-is-six. The future batch validator is prose until it
exists, and `versioning.change_rule` makes these drafts immutable when the
activation receipt binds them. Fix in-PR: `uniqueItems: true` plus a keyed
structure (`receipts: {grade_a: {attrs…, httpx_3614…, httpx_3221…}, grade_b:
{…}}`) so the 3×2 grid is schema-enforced, not validator-promised.

**P1-2 — Packet-hash preregistration binds to nothing in any receipt.**
"Preregister one exact packet hash per item … use the same item hash in both
lanes" is the amendment's core anti-shopping control, but no field in the
public receipt, batch receipt, private manifest, or custody profile carries a
preregistration-manifest hash or its default-branch commit (witness: key-walk
over both public schemas finds zero `prereg*` fields). A receipt set built
around never-preregistered packets validates against every committed
interface. Fix in-PR: `preregistration_manifest_sha256` +
`preregistration_commit` required in the batch receipt (and echoed per public
receipt), so admission structurally binds to the preregistration event.

## P2 findings

**P2-1 — The bare-JSON "clarification" changes the acceptance predicate while
the doc claims "does not relax the bare-JSON rule."** Whitespace-only
stripping admits whitespace-padded replies that v1-strict enforcement flagged.
It happens that NO historical outcome would flip (all six inadmissible
grade_b replies were fenced/prosed — non-whitespace bytes), but the amendment
does not say so. State it explicitly in `scope`, or the clarification reads as
result-aware acceptance tuning — the exact appearance this amendment exists to
avoid.

**P2-2 — Verifier independence is attestation-only, and lineage is invisible.**
`roles.verifier_is_not_*` are const-true self-declarations over a free-string
`verifier_id`; nothing records or constrains the verifier's provider lineage,
and custodian == verifier is not forbidden. This repo already has the
precedent instrument: the control-set's `grader shares subject lineage` flag.
Require a `verifier_lineage` field plus a mandatory lineage-conflict flag when
the verifier shares a provider lineage with the lane it audits.

**P2-3 — Only success is publicly representable.** `audit.result: const PASS`,
`state: const PROPOSED_FOR_ATOMIC_ADMISSION`, `attempt_failures: const 0`: a
failed audit or failed attempt has no public artifact shape at all. Failure
visibility rests entirely on the future dispatch/failure ledger, which no
receipt references (see P1-2). Either add a content-free public
attempt-failure receipt schema, or bind receipts to the ledger so silence is
detectable.

**P2-4 — Validator fallbacks are quieter than the authority claim.** The doc
makes "the canonical Git blob of this amendment" the immutable authority, but
the validator reads the amendment from the working tree and freezes parsed
section digests (content-equivalent, mechanism-different), and `_git_blob`
silently falls back to CRLF-normalized working-tree bytes when `git cat-file`
fails. Tampering is still caught by the pinned digests; the gap is that a
degraded evidence source is never reported. Emit a warning (or fail in a
future `--official` mode) when the fallback path is taken, and state the
digest-based freezing mechanism in the doc.

## Verified sound

- Parent + amendment section digest freezing (tamper-tested here: mutated
  receipt/sections fail closed).
- Strict duplicate-key JSON parsing; `additionalProperties: false` at every
  root; operational modes hard-refuse (`rc=2`) pre-custody.
- Six-fresh-sessions / single-dispatch / no-grandfathering / no-retroactive
  reclassification — all schema- or digest-pinned.
- The one-object rule still rejects fences and prose; witnesses confirm no
  prior outcome depends on the whitespace clarification.

## Witness reproduction

```
python3 - <<'PY'
# (uses the PR's own schema_errors engine; see PR #85 comment for the script)
PY
```
Witness outputs at review time: W1 SCHEMA-VALID, W2 SCHEMA-VALID, W3
SCHEMA-VALID (honest grid — engine cannot distinguish), W4 zero
preregistration fields.
