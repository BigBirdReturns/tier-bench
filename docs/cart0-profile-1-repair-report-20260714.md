# CART0-PROFILE-1 deterministic repair report — 2026-07-14

Status: local driver-lane proposal and receipts. Zero model/provider calls. No
hidden grader, benchmark criterion, task definition, ledger closure, or cost
accounting was changed. No production Genesis custody is claimed.

Implementation commit tested: `7805ec5671046d72da1fdf8c16460ef6d0d7dfcf`.
Queue-claim commit: `b9c128e6d39c4d70517c62118440fc238eb0083e`.

## Exact commands and results

From the isolated worktree, with bundled Python:

```powershell
$py='C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m py_compile scripts/cart0_anchor.py experiments/cart0_anchor_prototype/run_profile_conformance.py tests/test_cart0_anchor.py tests/test_cart0_catalog_attack_receipt.py
& $py tests/test_cart0_anchor.py
& $py tests/test_cart0_catalog_attack_receipt.py
& $py experiments/cart0_anchor_prototype/run_profile_conformance.py --out experiments/cart0_anchor_prototype/run_profile_conformance_20260714
& $py scripts/cart0_anchor.py ab-demo --repo . --spec experiments/cart0_anchor_prototype/task_state.json --catalog experiments/cart0_anchor_prototype/cards.json --profile experiments/cart0_anchor_prototype/transition_profile.json --out experiments/cart0_anchor_prototype/run_profile_b0_20260714 --boundary implementation_start --task 'Repair and independently verify the strict CART0 B4 conformance rung without model dispatch or gated changes.'
& $py scripts/cart0_anchor.py verify --repo . --bundle experiments/cart0_anchor_prototype/run_profile_b0_20260714/bundle
git diff --check
```

Results: compile PASS; bridge/profile tests PASS; repaired conformance 12/12
with reject-all guard PASS; historical receipt verification PASS at 4/10 safe,
6/10 gaps; fresh B0 build/verify PASS; zero model calls.

## Before/after B4 matrix

| Frozen vector | Before | After | Repaired mechanism |
|---|---|---|---|
| missing necessary card | PROCEED | REFUSE | external required-card dispatch |
| stale correctly hashed card | PROCEED | REFUSE | compiled project-event-head binding |
| semantically bad summary | PROCEED_UNREVIEWED | REQUEST_REVIEW | strict admission state |
| wrong actor/lane | PROCEED | REFUSE | external actor/role/lane allowlist |
| conflicting revision | REFUSE | REFUSE | unique contiguous revisions |
| malicious source instruction | PROCEED_UNQUARANTINED | PROCEED_QUARANTINED | non-authoritative evidence envelope |
| unavailable evidence pointer | REFUSE | REFUSE | source must bind at event head |
| overbroad wrong transition | PROCEED | REFUSE | card self-selection fields forbidden |
| tampered projected card | REFUSE | REFUSE | byte comparison/hash binding |
| inactive lookup | REFUSE | REFUSE | active-set lookup only |

Two positive vectors also pass: a lawful strict build/verify/resurface proceeds,
and an admitted semantically false summary proceeds only with
`semantic_truth_proven=false`. Together with quarantined rehydration, these
three positive cases prevent a reject-all verifier from passing.

The threat model was corrected, not erased: cryptography cannot detect a false
summary once an authorized reviewer/publisher admits it, and cannot guarantee a
later LLM ignores malicious source text. The strongest mechanical outcomes are
review gating before admission, explicit residual-risk flags, evidence
quarantine, and consumer runtime policy.

## Fresh B0 payload measurement

| Measure | A full context | B strict anchor + cards | Saved |
|---|---:|---:|---:|
| UTF-8 bytes | 51,392 | 2,837 | 48,555 |
| `ceil(bytes/4)` proxy | 12,848 | 710 | 12,138 |
| whitespace tokens | 6,793 | 298 | 6,495 |

Payload reduction: **94.4797%**. Anchor alone: **982 bytes / 246 proxy
tokens**. Selected cards: four. Wall time: **6,320.206 ms**, covering build,
verify, A/B projection and raw writes, plus two refusal probes. Model calls: 0.

The earlier B0 was 50,320 vs 2,623 bytes (94.7874%), with a 231-token anchor.
The repaired payload is slightly larger because it exposes strict profile,
admission, authority, and quarantine state. The demonstrated saving remains a
prompt-payload saving only; provider token billing, output tokens, task quality,
and cross-session fidelity were not measured.

## Receipt hashes and residual bounds

- repaired B4 receipt SHA-256:
  `f101c6e6721b5de63254a8887d3db0cd65938024c31c84f794654e77b4f6b199`;
- fresh B0 receipt SHA-256:
  `0d6c8f02dbf9b0cd085c99a01ec18bc347a4915647742a1bba96bfb55b81fe46`;
- fresh bundle receipt SHA-256:
  `2724498cc9c46fb239b624c846b9b4c1c1e00113d423abaa09d9fabea839f464`.

Residual boundaries: admitted false summaries remain possible; malicious source
instructions remain possible; `driver-reviewed` is not production approval;
the receipt is Git/SHA-bound, not Genesis-signed; project-local policy decides
the lawful next action; no model-quality claim follows.

The next lawful gate before B1/model dispatch is a separately committed
provider/model experiment row with frozen model/provider/effort, subject-lane
packets, eligibility manifest, analysis rule, unchanged grader path, and
explicit operator authority. B1 remains forbidden until that row exists.
