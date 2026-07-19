<!-- Authored by a claude-haiku hand ($0.10, 3 turns) under KERNEL-REFUTATION-DISPOSITION-1. Cross-pass consistency map: truncated first Sol pass (surviving 11) vs complete second Sol pass (40). Desk-adjudicated: 10/11 recurrence accepted; only old P2-02 (canonicalization ambiguity) has no fresh counterpart and stays live from the first pass. -->

# Cross-pass mapping — Sol refutation passes 1 (truncated) vs 2 (full), 2026-07-19

| Old ID | Old Claim | Best-Match New ID(s) | Strength | Note |
|--------|-----------|-------------------|----------|------|
| P1-11 | Runtime/referee evidence self-asserted in receipt | P2-5 | MATCHED | Both address unauthenticated self-reported runtime evidence in work receipt |
| P1-12 | Authorization not bound to post-selected dependency bytes | P1-8 | PARTIAL | Both cover values not frozen before selection; first is Gas Town-specific, second is general referee freeze |
| P1-13 | ERROR satisfies negative gate without proving rejection semantics | P1-7 | PARTIAL | Both about incomplete terminal classification and missing machine-readable reason codes; different contract scope |
| P1-14 | Smoke reconstructs final snapshot without proving causal closure | P1-31, P1-28 | MATCHED | P1-31 covers close/reopen/reclose race; P1-28 covers closure packet lacking trust root |
| P1-15 | Authentication custody and one-dispatch ceiling are labels, not boundaries | P1-30, P1-29 | MATCHED | P1-30 on custody observation; P1-29 on dispatch not bounding retries |
| P2-01 | String scanning is incomplete credential filter | P1-5 | MATCHED | Both identify bypassable keyword scanning; secrets encoded, object-keyed, or ambient-state-passed |
| P2-02 | Determinism and canonicalization internally ambiguous | — | UNMATCHED | No second-pass finding addresses decision_id determinism or canonical JSON ambiguity |
| P2-03 | Reason enum conceals controlling failure; no precedence defined | P1-7 | PARTIAL | Both cover closed-enum insufficiency and failure classification; first specific to referee verdict |
| P2-04 | external_refs field-name blacklist insufficient | P1-23 | MATCHED | Exact same scheme: verdict field blacklist bypassed by string encoding and alternate keys |
| P2-05 | Identity fields not portable (task/attempt/repo collisions; mutable paths) | P1-20 | MATCHED | Both address repository identity, scope binding, and portable namespace requirements |
| P2-06 | Phase 1 lacks hostile transport matrix; documentation excerpts not frozen | P1-25, P2-7 | MATCHED | P1-25 on argv/executable verification; P2-7 on manifest-frozen documentation |

---

## Net-new implementation findings (second pass, no surviving-fragment counterpart)

**Policy kernel:**
- P1-1: Measured basis can accept hypothesis-only evidence without cartridge/tier validation
- P1-2: Evidence index absent from decision_id binding; substitution leaves hashes intact
- P1-3: NO_DECISION carries no task, manifest, tank, or deterministic ID
- P1-4: Staleness validated with implicit zero age; snapshot_max_age supplied by self-judging decision
- P1-6: operator_gate permits self-authored approval without operator receipt binding
- P2-1: Fallback cartridges escape evidence, quota, and gate scrutiny
- P2-2: Process-spawn witness insufficient; in-process network/database calls unobserved

**Referee kernel:**
- P1-9: Command hash does not freeze executable, script, PATH, dependencies, or network resources
- P1-10: Verifier mutate-test-restore undetected; only diff equality before/after is checked
- P1-11: Ignored/untracked files can affect acceptance without appearing in emitted patch
- P1-12: Adapter not sandboxed; inherits environment, can read/write operator checkout and credentials
- P1-14: tier verify has no external trust anchor; receipt hashes self-validate against mutable receipt
- P1-15: Directory deletion alone does not prove process termination or credential release
- P2-3: Rejected receipt may omit stdout, stderr, acceptance record, and acceptance object

**Work receipt:**
- P1-16: Production validator never loads schema.json; checks only selected fields
- P1-17: Orphan check neither receives nor hashes decision bytes; any 64-hex accepted
- P1-18: No task envelope, cartridge manifest, patch, or referee-spec bytes required; format-only hash check
- P1-19: No receipt issuer, signer, referee identity, or independently published digest
- P1-21: Predecessor check is dictionary-key lookup; no recompute, cycles not rejected
- P1-22: Duplicate detection depends on caller-supplied all_receipts_for_attempt; defaults empty
- P1-24: Scheduler effects permit same task in both unlocks and blocks; self-effects and rejected-state unlocks pass
- P2-4: ERROR may carry either PASS or FAIL; contradiction check constrained to ACCEPTED/REJECTED only

Consistency: **10/11** surviving findings recur in the fresh pass.

END-MAPPING