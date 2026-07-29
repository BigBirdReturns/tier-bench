# AXM Interaction Floor Governance

## Mission

The floor exists to reduce integration burden across projects that should remain independent. It provides a stable protocol and public evidence surface. It does not centralize product architecture or create a committee that can grant domain authority.

## Maintainer powers and limits

Maintainers may publish specifications, schemas, vectors, starter kits, verifier implementations, registries, errata, and migration guidance. They may accept or reject conformance submissions according to public rules. They may revoke a registry entry when the bound artifact is unavailable, compromised, mislabeled, or no longer reproduces its submission.

Maintainers may not certify semantic truth, physical safety, human consent, legal compliance, deployment readiness, accessibility in use, project priority, or supplier fitness outside the tested boundary. A conformance mark cannot be used to imply those conclusions.

## Change classes

A patch change corrects prose, diagnostics, or non-normative tooling without changing accepted or rejected objects. A minor change adds optional profiles, bindings, or fields while preserving all prior vectors and identities. A major change alters canonicalization, required fields, authority law, identity projections, refusal behavior, or the meaning of an existing profile.

Every normative change includes:

1. the exact object being changed;
2. the actors affected;
3. the mechanism and rationale;
4. new positive and negative vectors;
5. compatibility and migration analysis;
6. authority and security review;
7. deprecation or refusal behavior;
8. a clean implementation test.

## Vector discipline

A published vector is append-only within a major version. A mistaken vector is deprecated through errata and a replacement vector; it is not silently edited. The repository retains the original bytes and explains which verifier versions recognized the correction.

Passing and failing vectors are equally normative. A verifier that accepts a prohibited mutation is non-conformant even when it accepts every positive example.

## Extension namespaces

Core `axm.*` extension names are assigned through reviewed changes. External extensions use a reverse-domain prefix controlled by the author. An extension declaration states its schema, compatibility rule, retention behavior, and authority exclusions.

Extensions may add observations, transport metadata, device capabilities, presentation hints, or narrower constraints. They may not redefine core fields, change semantic digests, grant authority, broaden a mandate, advance ownership, convert telemetry into truth, or upgrade a conformance tier.

## Registry governance

The normative registry is a deterministic projection of admitted submissions. Each entry binds adapter ID, version, descriptor ID, submission ID, profiles, tier, and badges. The registry does not rank projects by popularity and does not infer quality from stars, downloads, funding, or institutional affiliation.

A revocation is append-only and names the prior entry, reason, evidence, reviewer, and effective time. Mirrors reproduce registry and revocation identities. A hosted registry outage must not prevent detached verification of retained submissions.

## Certification marks

Bronze through platinum marks are computed from verified profiles and external evidence. Marks must link to a submission ID. A product may state “passes Interaction Floor gold profile” but may not state that the floor certifies safety, correctness, or endorsement.

Platinum requires an independent verifier and substitution receipt. Commercial support, membership, or sponsorship may fund the program but may not waive tests or purchase a tier.

## Security and disclosures

Security reports should identify the affected format, vector, adapter, verifier, or registry object. Maintainers preserve a private disclosure path and publish an advisory, fixed vectors, affected versions, and residual risk after coordinated repair.

The protocol security model must address confused-deputy operation, replay, stale ownership, identity collision, extension abuse, command injection, descriptor path traversal, resource exhaustion, malicious observations, privacy downgrades, and supply-chain substitution.

## Deprecation

Deprecation is versioned and time-bounded. A deprecated binding or profile remains verifiable for retained historical submissions. New submissions may be refused after the published cutoff. The registry and verifier never relabel an old submission as if it passed a newer profile.

A retired dependency remains recorded in the commodity ledger with its reason. Reconsideration requires new evidence rather than rediscovery by a later maintainer.

## Community submission path

A third-party author should be able to:

1. generate or write an adapter without private instructions;
2. validate its descriptor locally;
3. run the complete public vectors;
4. inspect failures and exact receipts;
5. submit the descriptor and conformance bundle;
6. receive review against published rules;
7. reproduce registry admission or refusal.

The project has not completed this public contribution workflow until an unaffiliated implementation reaches registry admission without maintainer-authored code.

## Durability

The floor must be reimplementable from frozen prose, schemas, and vectors using UTF-8, strict JSON, and SHA-256. OCI, Git, package registries, hosted CI, Sigstore, and the Python verifier are conveniences rather than permanent trust roots.

A stranded implementer should be able to reconstruct request, event, response, adapter, submission, and registry identities without network access. An independent verifier and resurrection kit remain open gates before the floor can claim long-term durability.

## Control question

Can the program accept an external implementation, reject a prestigious but non-conformant implementation, survive maintainer and hosting replacement, and preserve every historical submission without allowing governance to acquire domain authority?
