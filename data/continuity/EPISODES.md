# Continuity episodes — raw corpus for CART0 (evidence preservation ONLY)

*No schema, no reducer, no projections yet — per the operator's steering
(2026-07-10), CART0 stays at the evidence-preservation stage until ARC-C
closes. This file preserves episodes in the triple form the future consequence
tests will grade against. Append; never rewrite.*

## EP-001 — replay count could be manufactured by path references (ARC-A P1)

```
failure:  duplicate path references could manufacture replay count
residue:  closure requires unique hash-bound replay identities
future consequence test: duplicated evidence must fail to buy amortization
```

**What actually happened (do not sanitize):** the replay claim was
substantively true — the crossing-event replay was real, distinct, and
hidden-graded — but its *representation* could not prove distinctness. The
validator counted evidence-list references and trusted the row's own
`validated_replays` and `break_even_reuse_count` integers; two labels on one
receipt, or one receipt copied to two paths, would have counted twice, and one
replay could have closed a four-replay projection. No false claim was ever
recorded (the ledger honestly read 1-of-4), but the closure *path* was unsafe:
the current representation could have overwritten the actual event history.

**Remediation (PR: capture-ledger-p1-hardening):** replay evidence became
structured hash-bound events (unique `work_item_id`, unique receipt bytes,
candidate/grader/packet/artifact hashes verified against committed bytes);
`validated_replays` demoted to a redundant assertion validated against the
count of unique verified events; break-even computed from cost evidence by one
shared function (`scripts/capture_math.py`) used by both the validator and the
ROI report; closure requires `unique_validated_replays >= computed break-even`.

**Sibling episodes preserved for the same corpus** (each already documented at
its source; listed here so the corpus knows where its receipts live):

- EP-002 PR-number prediction collided with a shared counter → content-keyed
  ARC identifiers (`ROADMAP.md` STATE note, Jul 9–10).
- EP-003 blind packet v1 bytes irreproducible from committed state → superseded
  not contradicted; reproducibility predicate for evidence artifacts
  (`docs/agents/BLIND_CONTROL_V2.md`, `BLIND_CONTROL_V2_VERIFICATION.md`).
- EP-004 CRLF rendering forked a declared digest from committed bytes →
  transport adjudication, not integrity failure; digests must be defined over
  canonical bytes (`BLIND_CONTROL_V2_VERIFICATION.md`, axm-genesis §5–6).
- EP-005 Sol woke without assignment context → auto-loaded bootstrap
  requirement (`AGENTS.md`, PR #62).
- EP-006 a cross-engine "disagreement" that was a units mismatch (1-of-3
  collected read as 1-pass-2-fail) → correction layer appended, originals
  retained (`known_corner.jsonl` k3-floor-almanac-20260710-correction1).

## EP-007 — planning self-resurfaced the target constraint across all treatment arms

```
failure: the CART0 A/B/C run became causally non-discriminating when every
planner restated the boot-loaded target constraint before the registered
decision-boundary treatment; 6 of 15 administrations also aborted on provider
credit exhaustion, leaving imbalanced cells A=5, B=3, C=1
residue: a resurfacing experiment must preserve common boot exposure while
preventing uncontrolled pre-boundary articulation of the target constraint;
administrations must run in balanced blocks, and aborted or contaminated trials
mint neither pass nor fail
future consequence test: the applicable constraint may appear before the
decision boundary only where the frozen treatment manifest permits it; any
unregistered target-rule articulation invalidates that administration for the
causal comparison
```

Nine candidates were produced and deterministically graded 10/10. This is
candidate-performance evidence under repeated pre-boundary activation, not
evidence that boundary resurfacing outperforms boot-only exposure. The run is
incomplete and confounded; no comparative conclusion is sealed.

Disposition: NOT sealed. Common boot exposure of the target rule in all arms was
the **registered control, not the confound** — the sole confound was the
planning turn's uncontrolled articulation. Receipt (9 graded candidates, 6
aborts, corrected causal analysis, the clean rerun that preserves common boot)
preserved at `experiments/breadth/run/cart0_abc_20260710/` on the
driving-assistance branch (PR #65).

## EP-008 — a file with a unique hash was accepted as a replay receipt (EP-001 not yet closed)

```
failure: EP-001's hardening bound each replay to evidence hashes but never
verified that receipt_path resolved to a RECEIPT — any committed file with a
unique hash (grader output, packet, candidate, artifact) could pose as an
independent receipt and buy replay credit; the test suite had no negative
control, so CI was green over a live masquerade exploit
residue: a receipt must be a structured object that RE-ATTESTS the binding
(schema tier-bench/replay-receipt@1), parsed and cross-checked field-for-field
against the ledger event, with a path DISTINCT from every evidence file; and the
suite must carry the exact adversarial control (four arbitrary unique files must
not buy closure)
future consequence test: replay credit requires a parseable, distinct,
field-agreeing receipt whose verdict is pass; anything that is merely a unique
committed file mints zero events, and "green CI" without the negative control
does not count as closed
```

Fix (PR #64): structured `replay-receipt@1` object; validator parses + cross-checks
work_item_id / administration_id / grader_id / packet / candidate / candidate-set /
grader-output / artifact hashes and verdict, and rejects a receipt path that reuses
an evidence file; adversarial regression test `test_four_arbitrary_files_as_receipts_cannot_buy_closure`.
This is what actually closes EP-001. "CI green" earlier meant "no negative control
existed" — itself an instance of the recurring defect.

## EP-009 — the CI workflow carried its own inline assertion the local suite could not see

```
failure: PR #65 passed the entire local test suite but failed GitHub CI, because
the durability workflow hardcoded an inline ROI check (validated_replays==1)
invisible to any local runner; "local green" was mistaken for "the gate passes"
residue: reproduce EVERY workflow step's literal command locally before declaring
ready — a check that lives only in the YAML is still part of the gate, and the
local suite is a subset of it, never the whole
future consequence test: a change that alters a ledger quantity must update the
inline workflow assertion in the SAME diff, and the exact `python -c` one-liner
from the YAML must be run locally and shown green before the PR is called ready
```

Fix (PR #65): edited `.github/workflows/breadth-durability.yml`'s inline ROI
assertion to `validated_replays==2` and reran the literal one-liner locally.
Distinction: local-green ≠ CI-green (`docs/DISTINCTIONS.md`).

## EP-010 — a render path labeled authority it never validated

```
failure: axm-hinge `impact render` printed an authority label whenever a reviewer
dict was merely present, without running the validator — presentation could
assert a seam the gate had not checked, so a schema-shaped record rendered as
authoritative regardless of whether the authority binding held
residue: a render/presentation path must run the fail-closed validator FIRST and
exit nonzero on any error; the authority label is gated behind an explicit
authority_verified flag (default false), so a reviewer dict's mere presence never
produces the label
future consequence test: rendering an impact record with an unverified reviewer
must exit nonzero and must NOT emit the authority label; only a bytes-bound,
validated reviewer seam earns it
```

Fix (axm-hinge PR #2): `render_impact` gained `authority_verified` (default
false); `cli.py impact render` runs `validate_impact` first and exits nonzero on
error. Distinctions: presentation ≠ gate; attribution ≠ authority
(`docs/DISTINCTIONS.md`).

## EP-011 — a frozen manifest nothing checks drifts into prose (schema-valid ≠ executable-valid)

```
failure: the CART0 v2 design was frozen as Markdown (PR #66) with no machine
check; a human-authored freeze can silently drift — a control arm could acquire
the target rule, the READY gate could be dropped, the blocks could unbalance —
and nothing would bite, exactly the A=5/B=3/C=1 imbalance a prose freeze once hid
residue: a frozen experimental design must have an executable manifest and a
fail-closed validator asserting its invariants (three arms, boundary message as
the ONLY manipulation, B resurfaces / A,C do not, READY first-response and no
planning turn, balanced blocks K>=1, mandatory preservation set, gated grading),
plus a keyless runner that captures custody and refuses a verdict on incomplete
or contaminated blocks
future consequence test: `validate_manifest.py` must reject a control arm that
resurfaces the rule, a dropped READY gate, K=0, and a missing preservation field;
the runner must contaminate (mint neither) a rehearsed first turn without losing
the transcript, and return NO_VERDICT on any incomplete balanced block
```

Fix (this PR): `experiments/breadth/cart0_abc_v2/{manifest.json,validate_manifest.py,runner.py}`
plus `tests/test_cart0_v2_harness.py`, wired into CI. Distinction:
schema-valid ≠ executable-valid (`docs/DISTINCTIONS.md`).
