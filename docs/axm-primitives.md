# AXM primitives — the registry (readable view)

**Non-normative.** `data/primitives/axm_primitives.v0.1.json` is the source of
truth; `scripts/validate_primitives.py` enforces it. This page is the human view.
If the two disagree, the JSON wins — regenerate your understanding from it.

Every row below carries a full source trail (`source_basis` → `derived_claim` →
`not_source_claim`). See [`provenance.md`](provenance.md) for the law and the
anti-laundering rule.

## Registry v0.1 — 7 primitives

| Primitive | Status | Rests on (source_basis) | Derived claim (AXM synthesis) |
|---|---|---|---|
| **black_letter_axm** | derived | Cornell Wex black-letter *(direct_fact)*; FRE 901 *(baseline)* | Start where the rule is settled, the record exists, and the answer is not allowed to drift. |
| **waterline** | derived | measured waterline registry + 51 result rows *(repo_evidence)* | Routing authority is the cheapest model **measured** to clear a task under hidden grading; unmeasured cells answer "unmeasured", never a guess. |
| **hidden_grading** | derived | `harness/attempt.py` hidden-file mechanism *(repo_evidence)* | A capability measurement is valid only if the deciding tests were never visible to the solver. |
| **proof_knot** | synthesis | Merkle 1987, Genesis paper *(external_evidence)*; Inca quipu *(analogy)* | A sealed, independently verifiable unit of recorded fact — checkable from the bytes alone, offline. |
| **capture_ledger** | synthesis | result-row costs *(repo_evidence)*; Genesis cost-shift *(external_evidence)* | Frontier cognition is justified only when converted into reusable machinery; record what was captured, its cost, and its break-even. |
| **axm_provenance_layer** | synthesis | Genesis §8.3 + provenance ledger §0 *(external_evidence)* | Every primitive must carry a source trail, a stated synthesis, and explicit guards, enforced by a verifier that rejects unsourced primitives. |
| **axm_ontology** | synthesis | provenance ledger + spectra origin *(external_evidence)* | The AXM vocabulary is a **starting ontology** under revision, not fixed truth; each term earns its place only by carrying provenance. |

## The guards that matter most

Two primitives record the provenance of the model-authored work this whole
program rests on, so it can never be mistaken for established fact:

- **axm_ontology** / **axm_provenance_layer** carry the `not_source_claim`:
  *"This ontology was authored with gpt-5.5-high (and 'Spectra' with gpt-4o); it
  is a starting ontology, not revealed truth."*
- **capture_ledger** carries: *"No break-even is proven yet — this names the
  object PR #48 builds; it is captured-not-yet-amortized."* Naming a primitive is
  not building it.
- **proof_knot** carries: *"The quipu is an analogy for the name, not a technical
  specification. The integrity guarantee comes from BLAKE3 Merkle + ML-DSA-44,
  not from the metaphor."*

## Sources cited

10 sources in `data/sources/source_ledger.v0.1.json` — legal (Cornell Wex,
FRE 901), repo artifacts (waterline, result rows, the harness), academic
(Genesis paper, Merkle 1987), external (Inca quipu), and **2 `model_synthesis`
sources, each with a named author**: the provenance ledger (gpt-5.5-high) and
the Spectra concept (gpt-4o).
