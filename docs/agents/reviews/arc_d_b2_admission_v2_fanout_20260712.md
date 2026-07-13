# ARC-D B2 admission-v2 fan-out review

Date: 2026-07-12
Scope: governance/specification only; no grader response or grade payload was
opened for this review.

Three independent read-only lanes reviewed the proposed next boundary:

- governance/state-machine design;
- exporter, schema, validator, and test mapping; and
- adversarial custody/blindness/public-verifiability analysis.

## Converged findings

1. Private custody plus public hashes can provide tamper-evident public
   commitments and an independently audited result. It cannot provide public
   reproducibility while the raw bytes remain unavailable.
2. Result-aware v2 work may change only custody/admission administration. The
   v1 rubric, authority, disagreement rule, B4 rule, and grader-visible packet
   format remain unchanged. Prior Grade A/B attempts cannot be grandfathered.
3. Both grading lanes must rerun all three items after activation. The original
   sealed ARC-D subject responses do not rerun.
4. Admission needs more than hash-shaped JSON: separate immutable lane venues,
   a default-branch activation receipt, public six-cell preregistration and an
   append-only dispatch ledger, exact private Git object validation, an
   authenticated signed-commit or OIDC audit receipt, and deterministic
   private-to-public derivation.
5. A public-only validator may report only
   `PUBLIC_COMMITMENT_SHAPE_VALID`. It may never report semantic admission.
6. Comparison remains closed until one atomic merge admits all six audited
   receipts. B2 still cannot emit HARVEST; the unchanged B3/B4 ladder applies.

## Defects caught during implementation review

The first implementation draft was rejected before commit because its private
validator accepted a hand-built minimal packet and its public receipts could
self-assert audit success. Review also found incomplete nested schema checks,
syntactic activation, unbounded public strings, duplicate-key JSON ambiguity,
no A/B packet parity, and an overclaim that hashes restored public
reproducibility.

The final branch removes every operational admission mode. The merged result,
if accepted, is deliberately `SPECIFICATION_ONLY_NOT_OPERATIONAL` and
`ADOPTED_PENDING_CUSTODY`. Critical amendment sections are canonical-digest
frozen, operational companion schemas are explicitly drafts, unknown CLI modes
fail closed, and queue rows block custody activation, both fresh grading lanes,
and comparison in sequence.

## Review disposition

`READY_AS_SPECIFICATION_ONLY`

This disposition does not authorize a grading dispatch, admit an old or new
grade, run comparison, bind B2, create B3, or emit HARVEST.
