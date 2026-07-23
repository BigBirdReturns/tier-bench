# CART0-BOUND-1 result — PARTIAL

`CART0-BOUND-1` completed its four preregistered provider calls, but it did not
measure task fidelity. Every exact provider result was wrapped in a Markdown
`python` fence despite the frozen bare-file output contract. The unchanged
grader therefore rejected all four candidates at compilation before task
semantics were exercised. The no-retry/no-normalization rule is binding, so the
official disposition is `PARTIAL`, not a repaired PASS/FAIL comparison.

## Frozen administration

- Queue claim: `d5672dd`
- B1 preregistration/profile: `04584f4`
- Anchor budget repair before disclosure: `489ba8f`
- Exact provider-input commit: `8ec9db3`
- Provider/model: Anthropic `claude-haiku-4-5-20251001`, effort `low`
- Surface: Claude Code print mode, safe mode, no persistence, zero tools
- Calls: four unique fresh sessions, one per task/arm, zero retries
- Maximum authorized ceiling: USD 0.15/call and 0.60 total
- Cost basis: `subscription-derived`
- Hidden graders and task manifests: unchanged from the hashes in
  `preregistration.json`; each candidate was graded twice after all four raw
  provider responses and candidates were sealed.

The strict anchor used 233/256 proxy tokens. Anchor plus four selected cards was
648 proxy tokens. The complete project-state context was 19,436 proxy tokens
before the identical task prompt was appended.

## Descriptive telemetry

| Task | Arm A provider input | Arm B provider input | B reduction | A/B hidden grade |
|---|---:|---:|---:|---|
| `t3_null_filter_001` | 23,262 | 2,218 | 90.4651% | fail / fail — fenced transport |
| `t3_accrual_crossover_001` | 23,073 | 2,029 | 91.2062% | fail / fail — fenced transport |

Across the two descriptive pairs, provider-reported total input was 46,335 for
A and 4,247 for B, a 90.8341% reduction. Output tokens were 5,526 for A and
6,836 for B, so B used 23.7061% more output. Summed provider-call wall time was
47,400.820 ms for A and 40,694.941 ms for B. The provider-reported cost metric
was USD 0.167427 for A and 0.043454 for B, 74.0460% lower in B; it is not
asserted to be a bill or billing savings.

These input savings are demonstrated provider telemetry. Usable-token savings
are **not** demonstrated because neither arm produced an admissible candidate.
The baseline failing identically also means this run supplies no evidence that
CART0 caused the failure.

## Sealed receipts

- Dispatch manifest SHA-256:
  `ec70105c6cfd28f81b8e66ec830576d0c1816b32894227667f8f59f38f79be31`
- Grade manifest SHA-256:
  `fbbe0fa134955f6044751caf9c35ce6efd65ad61fc3ef7061cd5e33e62f5bfdb`
- Comparison SHA-256:
  `c2b4de21ff2145631a0ce5ee55df5933493788bf01a46c7b75758c688ff8e8ff`
- Complete checksum manifest SHA-256:
  `69c3bd65c02afece7d006e7ee75fc83673e20e0be56d0138159ce933b3e00aeb`

`scripts/cart0_bound1.py verify` reproduced all 25 input, 20 provider, 24
grade, and four sealed-candidate checks plus the 80-entry complete manifest.
The deterministic comparison remains `operational_narrow_win: false`.

## Exact next gate

A rerun would require a separately versioned queue row and newly frozen output
transport (for example, provider-enforced structured output whose decoded field
is the candidate). The historical fenced candidates and grades must remain
unchanged. No such rerun, B2 causality experiment, production integration, or
broader claim is authorized by this partial result.
