# The distinctions the machinery forced out

*Harvested 2026-07-11. The recurring pattern across tier-bench + axm-hinge: the
running machinery kept refusing to stay honest without a distinction we had not
yet enforced. Each row below is a pair that looks identical until a gate makes
them different — with where it bit and where it is now enforced in code. This is
residue: seal it so the next builder inherits the distinction instead of
rediscovering it by shipping the collapsed version.*

| Distinction | The collapse (what looked equal) | Where it bit | Where it's enforced now |
|---|---|---|---|
| **integrity ≠ truth** | a signed/hash-bound artifact must be correct | provenance can prove *which bytes*, not that the claim is right | Genesis seals bytes only; axm-hinge impact `SCOPE:` refuses semantic proof; capture ledger separates `real-billed` from claim |
| **measured ≠ hypothesis** | a number on a page is a fact | every tier_ceiling was an unmeasured guess | HANDOFF constitution §2; `known_corner.jsonl` states evidence class; breadth reports tag measured vs hypothesis |
| **admission ≠ activation** | a human accepting a hinge means the break occurred | an `admitted` + `hypothetical` hinge could invalidate a baseline | `impact.py`: invalidating impact requires `evidence_state ∈ {observed, triggered}`; `observed` must preserve its custody limitation |
| **attribution ≠ authority** | `reviewed_by: "jonathan"` proves who was *allowed* | any string (`intern`, `gpt-9`, `banana`) satisfied "human authority" | `impact.py` reviewer seam: principal/role/scope bound to an authority artifact by hash; docs downgraded to "attribution" without it |
| **risk ≠ model invalidation** | a risk-register entry captures an invalidator | the register named "imbalanced cells"; the hinge ledger had no hinge for it (A4 uncovered) | axm-hinge requires a hinge to break a *named assumption* with observable+trigger; the comparator surfaced the gap → H3/A4 |
| **a named action ≠ a justified action** | writing down "required: redesign" proves it follows | free-text action was never entailment-checked against the consequence | `impact.py` proves structural linkage only; semantic necessity is an explicit reviewer question, not machine-checked |
| **schema-valid ≠ executable-valid** | JSON-Schema pass means the validator passes | `{"ref": "x"}` passed schema, failed runtime hash binding | `bound_ref` (ref+sha256 required) aligns the wire contract with `validate_impact` |
| **presentation ≠ gate** | rendering a record is a read-only view | `impact render` labeled "authority" on a record that would fail `impact validate` | `impact render` runs the validator first; `render_impact` labels authority only when `authority_verified` |
| **local-green ≠ CI-green** | "my test suite passes" means the gate passes | a workflow's inline ROI assertion (and the P1 masquerade) were invisible to the local suite | reproduce every CI step locally before trusting; a gate is not closed without its negative control (EP-008) |
| **reference ≠ identity** | two files with identical bytes are the same object | an impact could bind a ledger built against a different baseline of equal bytes | v0.1 baseline identity requires reference **and** hash |
| **collection-state ≠ performance-state** | "1 of 3" reads as "1 pass, 2 fail" | a cross-engine "disagreement" that was a units mismatch | EP-006 correction layer; separate observations-collected / passes / required-K / broker decision |
| **observed ≠ triggered** | either you have evidence or you don't (binary) | the CART0 confound was witnessed but transcripts weren't preserved | evidence states distinguish `observed` (constrains interpretation) from `triggered` (byte-replayable); H1 observed, H3 triggered |
| **capture ≠ amortization** | expensive cognition sealed once is "paid off" | a capture claimed `amortized` after 1 of a projected 4 replays | capture ledger: closure requires `unique_validated_replays ≥ computed break-even`, distinct hash-bound events (EP-001/EP-008) |
| **transport defect ≠ integrity defect** | different bytes = tampering | CRLF vs LF forked a declared digest on a clean checkout | digests defined over canonical bytes; `.gitattributes` evidence-scoped `-text`; adjudicated as transport (EP-004) |

## The one-line thesis

Every row is the same failure: **stable knowledge kept living inside fallible
attention (or a persuasive artifact) instead of becoming an external control
structure.** The machinery is honest only where a gate makes the collapsed pair
distinguishable — and each gate needs its own negative control, or "green" just
means the distinction was never tested.

See `docs/THE-RECURRING-DEFECT.md` for the twenty-defect narrative and
`data/continuity/EPISODES.md` for the raw episode corpus.
