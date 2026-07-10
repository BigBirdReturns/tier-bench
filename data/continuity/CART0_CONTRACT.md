# CART0 — the contract (operator-ratified doctrine, 2026-07-10)

*Evidence preservation of a steering exchange — not a schema, not a reducer.
CART0 build work remains postponed until ARC-C closes. This file exists because
briefing-by-conversation evaporates (EP-005); the contract below was ratified
in-session and must survive it.*

**CART0 is the zero-resolution map that still preserves control** — the
irreducible state required to continue without unlawfully rewriting what the
expedition has already learned. It is not a memory document. It is a minimal
deontic control surface with two coupled parts:

```text
CART0 projection:  minimum state required to orient the entrant
CART0 gate:        reassert the applicable constraints before consequential transitions
```

## The projection (five elements)

1. **Objective + current interpretation** — kept distinct, so mission
   continuity and plan adaptation cannot be conflated.
2. **Prohibitions + harvested constraints** — the operational value of dead
   branches (residue) and GATED machinery.
3. **Position fix** — current branch, its state, the one presently authorized
   transition, and the authority that permits it.
4. **Freshness commitment** — prevents a stale projection from impersonating
   current authority.
5. **Retrieval index** — full-resolution history available without keeping it
   in the cognitive foreground.

## Precision adjustments (part of the contract)

- **Gate binding.** "Enforced by a validator" only permits dropping the prose
  when invocation is deterministic and mandatory. The projection stays bound to
  the gate, e.g. `{"gate": "scripts/validate_capture_ledger.py",
  "gate_version": "<digest>", "required_before": ["capture_closure"]}`.
  The system remembers the constraint by making circumvention structurally
  unavailable, not by re-explaining the rule. The gate digest doubles as
  tamper evidence: editing the gate is a detectable state change, never a
  silent reinterpretation.
- **Freshness beyond HEAD.** A projection is semantically stale when the
  reducer changes even if history did not:
  `projection_digest = hash(event_head || reducer_digest || projection_profile)`.
  Distinguishes "new terrain exists" from "same terrain, different
  authoritative reduction machinery". (Genesis conformance: identity derived,
  never stored.)

## The execution finding (replay04)

Transfer at boot does not guarantee retention under load: the rule was present
and lost competition for attention. CART0 must test **availability and
effective reactivation** separately. Decision-point resurfacing is not a sixth
map element; it is the execution contract around the map.

## The research hypothesis

> Continuity depends less on how much prior context is retained than on
> whether the operative constraints are deterministically resurfaced at the
> transitions where violating them would change project state.

Falsifiable first test: `256-token projection + decision-boundary resurfacing`
vs `4,096-token projection loaded once` — prediction: the first wins
specifically on residue-consequence tests, while the larger map may improve
narrative reconstruction yet still allow an absorbing task to suppress a
prohibition at the moment it matters.
