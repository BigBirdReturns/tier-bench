# Continuity episodes — raw corpus for CARTO-0 (evidence preservation ONLY)

*No schema, no reducer, no projections yet — per the operator's steering
(2026-07-10), CARTO-0 stays at the evidence-preservation stage until ARC-C
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
