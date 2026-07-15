# Post-seal comparison note — Claude delta retest vs remediation report

Written AFTER sealing
`claude_delta_retest_report_20260714.md`
(SHA-256 `70cc00b9c6f4cc0f74e4679e701f7764494f948eaabd9fd7edacae448cbfd6bc`)
and after first reading
`docs/cart0-profile-1-independent-review-remediation-20260714.md`.
The sealed delta report and the original sealed report/witnesses are unmodified.

## Comparison

No material discrepancies found. Point-by-point:

- Archive hash: remediation states
  `fb912f39d08681ff60108e0cf5ca7199f339de25bc36bfe1d1c5300602f66bdc` — matches
  my Step-1 measurement exactly.
- Verifier outcome: remediation claims exit-clean run ending
  `PORTABLE_CART0_PROFILE_1_VERIFIED` after tree comparison, both tests, fresh
  conformance, remediated B0, preserved historical B0 — reproduced identically
  in my run (exit 0, same marker, same tested/preserved commits
  `a30ca1a` / `133fdf1`).
- Fresh conformance 15/15, 10 negative / 5 positive, reject-all guard PASS,
  zero model calls — reproduced exactly (`passed_count: 15`,
  `reject_all_guard_passed: true`, `model_calls: 0`).
- TOCTOU (`rehydrate_head_drift`) emits `PROCEED_VERIFIED_BLOB` — reproduced,
  and independently re-executed with a different injection marker; injected
  bytes absent, verified blob emitted, identical rehydrated hash
  `7de99f43…3e424`.
- Unsafe paths: remediation claims six NUL/C0/DEL and nested-`.git` payloads
  cleanly refuse — reproduced, and extended to nine payloads (adding `\x02`,
  mixed-case `.gIt`, trailing `.git` component); all refused with exact type
  `AnchorError`, never bare `ValueError`; CLI emits `CART0_ANCHOR_REFUSED`
  with no traceback.
- Delimiter hardening: exactly one projection/card-bound begin/end pair with
  legacy delimiter text inert — reproduced, identical rehydrated hash
  `6adf2177…8a670`. The remediation's own wording ("projection/card-bound
  nonce") is consistent with my sealed observation that `BOUNDARY_ID` is
  deterministic (`sha256(projection_digest, card_id, revision)[:32]`), not a
  per-run random nonce.
- Historical attack receipt preserved at 4/10 safe, 6/10 gaps — reproduced
  verbatim in the bridge-test output.
- Bounds section matches the retest instruction's unauthorized-claims list; my
  sealed report asserts none of them.

## Residual notes (informational, not discrepancies)

- The remediation's receipt SHA-256 values (conformance `b0852cd1…`, B0 A/B
  `aae30833…`, bundle `47c5b844…`, portable output `01d55b0e…`) refer to its
  own sealed run artifacts; my fresh conformance run necessarily has a
  different receipt hash (wall-time field varies) but identical
  vectors/runner/reducer digests and identical per-vector results, which is
  the stronger equivalence.
- "Nonce" terminology could be read as per-run randomness; it is
  deterministic projection-binding. The security property claimed (source
  author cannot forge the bound pair) still holds.

Verdict: remediation report's delta-scope claims are confirmed by the
independent retest.
