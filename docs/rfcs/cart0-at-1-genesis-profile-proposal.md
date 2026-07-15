# RFC proposal: `cart0@1` Genesis profile

Status: proposal in Residue only. This document does not modify or claim
acceptance by the separate `axm-genesis` repository.

## Decision

Define `cart0@1` as a Genesis domain profile. Genesis remains the custody
kernel: it canonicalizes, seals, signs, and verifies exact inputs/outputs.
`cart0@1` adds frozen domain checks for a CART0 projection. The lawful next
action, actor/head comparison, reducer, selector, and transition policy remain
AXM Core or project-local code.

Following the accepted RFC 0008/profile pattern, a conforming verifier must:

1. run the ordinary Genesis kernel verifier;
2. resolve the declared `cart0@1` input/profile and canonical project inputs;
3. rerun the version-pinned project-local deterministic reducer/selector;
4. byte-compare the recomputed anchor, cards, bindings, and trust labels with
   the sealed projection;
5. add `cart0@1` to `profiles_checked` only after every check passes; otherwise
   fail with profile-owned error codes; unsupported profiles remain in
   `profiles_unchecked`;
6. permit consumers to rely on a CART0 projection only when kernel status is
   PASS and `cart0@1` appears in `profiles_checked`.

## Canonical profile inputs

- profile ID/revision and digest;
- independent boundary-to-required-card/authority dispatch table;
- allowed principal, role, and lane sets;
- expected project event head, reducer digest, and policy/profile digest;
- accepted admission/review states and their canonical receipts;
- evidence quarantine label, non-authority flag, and runtime policy;
- card data with stable ID, revision, supersession, token budget, summaries,
  exact source pointers, and source/span hashes.

Cards may not contain actor authorization, transition applicability, gate
status, review status, or freshness authority. Those are profile/admission
facts. Any selected transition absent from the external dispatch table fails.

## Required failure codes

- required card or GATED authority missing;
- actor/role/lane mismatch;
- project event head, reducer, policy, or profile drift;
- rejected/unreviewed/missing admission in strict mode;
- unavailable or changed evidence/source span;
- projection byte mismatch;
- dishonest `profiles_checked`/`profiles_unchecked` state.

## Security boundary

Genesis signatures prove integrity and publisher identity. They do not prove
source truth, extraction truth, or instruction safety. A signed shard can
faithfully preserve a false human-reviewed summary. A quarantined source can
still contain prompt injection, and cryptography cannot guarantee an LLM will
ignore it. `cart0@1` requires review/admission evidence, source-span validation,
freshness, quarantine, and consumer runtime policy while recording
`semantic_truth_proven=false` and `instruction_safety_proven=false`.

## Admission path

Before implementation in Genesis: obtain explicit authority in that repository,
freeze independent positive/negative vectors, implement a second verifier that
recomputes and byte-compares, and require kernel PASS plus honest profile-check
state. This Residue harness and its SHA-256 receipts are conformance evidence,
not production Genesis custody.
