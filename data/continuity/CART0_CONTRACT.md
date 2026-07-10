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

## Addendum (same steering exchange): actor-relative projection + causal design

- **The position fix is actor-relative** (inside element 3, not a sixth
  element): it binds `{principal, role, lane, knowledge_boundary,
  authorized_transition, authority}`. The same repo state permits different
  actions for different entrants; a map that prescribes a globally valid action
  to a locally disqualified actor has failed. Known hidden-gradable episode: a
  repo-aware session grading SOL-1 is contaminated even if every score is
  substantively correct.
- **Causal design before the headline sweep** — hold the map constant, vary
  only the decision boundary: A boot-only (neutral equal-length transition
  message) · B applicable residue constraint resurfaced · C equal-length
  irrelevant-but-valid constraint (recency control). Fresh sessions, same
  model/effort, two-turn protocol, distinct isomorphic edge-family items,
  hidden grader sees candidates only after sealing. Then the 2x2 factorial
  (resolution 256/4096 x delivery boot/resurfaced). Prediction: resolution
  helps reconstruction; resurfacing dominates residue-consequence accuracy.
- **Constraint dispatch is mechanical**: the transition class
  (`capture_closure`, `candidate_sealing`, `blind_grading`, …) deterministically
  selects the bound gates and residue constraints. The model receives the
  result; it never decides what deserves remembering.

> The mechanism, stated finally: a compact constraint map remains operational
> only when the system binds each consequential transition to the applicable,
> version-pinned gate and resurfaces that constraint for the authorized actor
> at the moment of action. The model does not have to keep remembering; the
> protocol has to keep refusing to forget.

## Placement

CART0 is a cross-cutting continuity protocol, not an AXM spoke.

- **Research and validation:** Tier Bench owns the experimental corpus, reducers,
  projections, gates, receipts, and hidden grading until the minimum sufficient
  continuity residue is empirically established.
- **Normative custody contract:** once stable, canonical serialization, identity,
  sealing, and conformance requirements may graduate into an AXM Genesis profile.
  Genesis verifies the artifact; it does not determine the lawful next action.
- **Runtime:** reusable reduction, retrieval, and projection machinery may live in
  AXM Core, while project-specific transition rules and gates remain project-local.
- **Instances:** each project stores its own continuity event ledger and projections
  beside the work they govern.
- **Spoke relationship:** AXM spokes, including axm-hinge, emit consequential state
  transitions that CART0 may preserve. They do not contain CART0, and CART0 does
  not replace their domain objects.

> Correction on record (2026-07-10): do NOT put the reducer into Genesis merely
> because the artifact is Genesis-shaped. The reducer is epistemic authority; Genesis
> is custody. Genesis owns the sealable wire format (a `continuity-event@1` / `cart0@1`
> profile: canonical serialization, identifiers, projection-digest construction,
> conformance vectors, seal/verify rules). The reducer/projection runtime is Core or
> project-local. Conflating them makes the custody kernel the universal project-state
> interpreter — the centralization CART0 exists to refuse.
