# AXM provenance layer

*The anti-vibes layer.* AXM coins vocabulary quickly — black-letter AXM,
waterline, capture ledger, proof knot, terrain-divergence knot. Coined fast,
these blur together into persuasive prose, and prose repeated often enough starts
to read as fact. This layer makes that impossible to do silently: **every
primitive carries a source trail, and a verifier rejects any primitive that
doesn't.**

It is the tier-bench-side implementation of two things we already committed to:

- the operator's provenance ledger, section 0 — *"Nothing below should be treated
  as revealed truth. It is a starting ontology."*
- the AXM Genesis paper, section 8.3 — language models are useful **at compile
  time** (extract, summarize, propose), where their output "can be reviewed,
  corrected, rejected, signed, and frozen." They must not be the **runtime
  authority**. Provenance is how we keep compile-time synthesis labeled as such.

## The law

Every primitive walks the same trail. This is the same shape the provenance
ledger uses and the same shape the paper's kernel instantiates for a knowledge
claim:

```
primitive
  -> source_basis      (what real sources it rests on, and how)
  -> derived_claim     (the AXM synthesis drawn from them)
  -> not_source_claim  (explicit guards: what the sources do NOT say)
  -> verifier          (the command/artifact that checks it)
  -> failure_mode      (how it degrades if unpoliced)
  -> next_baseline     (optional: the measurement that would sharpen it)
```

`status` records how far a primitive is from raw source:

| status | meaning | example |
|---|---|---|
| `settled` | rests on a directly-cited external authority | (reserve for black-letter facts) |
| `derived` | an architectural **mapping** from sources to an AXM claim | `black_letter_axm`, `waterline`, `hidden_grading` |
| `synthesis` | AXM-native, resting on repo evidence or analogy only — **most guarded** | `proof_knot`, `capture_ledger`, `axm_provenance_layer`, `axm_ontology` |

## Sourced fact vs. AXM synthesis

The point of the split is that a reader can always tell which is which.

- **Sourced fact** lives in the **source ledger** (`data/sources/`). Cornell's
  definition of black-letter law is a fact about Cornell. FRE 901 is a fact about
  the Federal Rules. The 51 measured rows are a fact about this repo. Each is an
  entry with a `kind`, a `locator`, and a `basis_class`.
- **AXM synthesis** lives in the **primitive registry** (`data/primitives/`) as
  `derived_claim`. "AXM should start where the rule is settled" is *our* mapping
  onto black-letter law — not something Cornell says. The `not_source_claim`
  list states that boundary out loud ("Cornell does not define AXM").

## The anti-laundering rule (model-authored sources)

A source of `kind: model_synthesis` **must** name its `author` model. This is not
bookkeeping — it is the rule that keeps model-generated vocabulary from acquiring
false authority. Two such sources are recorded, on purpose, because the layer
would be dishonest without them:

- `axm_provenance_ledger` — authored with **gpt-5.5-high**. The document that
  *defines* this provenance discipline is itself model synthesis; it says so.
- `spectra_origin` — the "Spectra" runtime concept was born on **gpt-4o**. The
  name is a coinage; the deterministic-query guarantee comes from the
  `axm-verify` hard gate, not from the word.

The registry eats its own dog food: `axm_ontology` cites both, and its
`not_source_claim` states plainly that the ontology "was authored with gpt-5.5-high
(and 'Spectra' with gpt-4o); it is a starting ontology, not revealed truth."

## What the verifier enforces

`scripts/validate_primitives.py` (stdlib-only) implements
`schemas/primitive.schema.json` and `schemas/source_ledger.schema.json` in code,
plus three rules a plain schema check can't express:

1. **Referential integrity** — every `source_basis.source_id` must resolve to an
   entry in the source ledger. A dangling citation *is* an unsourced primitive.
2. **Anti-laundering** — `model_synthesis` sources must name an `author`.
3. **Analogy discipline** — a `support_type: analogy` basis (e.g. the quipu →
   proof-knot naming) requires at least one `not_source_claim`, so a metaphor can
   never be read as a guarantee.

It exits non-zero on any failure, so CI (`.github/workflows/breadth-durability.yml`)
fails the build. `tests/test_validate_primitives.py` proves each rule bites.

## Adding a primitive

1. Add any new sources to `data/sources/source_ledger.v0.1.json` first (a
   primitive can only cite sources that exist).
2. Add the primitive to `data/primitives/axm_primitives.v0.1.json` with all
   seven required fields. Be honest about `status`: if it rests only on repo
   evidence or analogy, it is `synthesis`, not `derived`.
3. Write the `not_source_claim` guards *before* the `derived_claim` reads
   persuasive — they are the check on your own prose.
4. `python scripts/validate_primitives.py` must pass; `python
   tests/test_validate_primitives.py` must stay green.

## What this layer does and does not prove

It proves **attribution** and it separates **fact from synthesis**. It does **not**
prove that any sourced claim is correct, and it makes **no benchmark or capability
claim** — those live in the waterline and the community-result rows, measured
separately. Provenance is necessary for an honest record; it is not sufficient for
a true one. (Same discipline as the paper's section 9: a signature proves
integrity and publisher identity, not that the source is true.)

See [`axm-primitives.md`](axm-primitives.md) for the readable registry;
`data/primitives/` is the normative source of truth.
