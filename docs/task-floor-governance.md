# Task Floor governance and conformance claims

## Open floor

Task Floor is part of the MIT-licensed Tier Bench repository. The specification, schemas, TCK, reference driver, registry, protocol exports, and fixtures are intended to be usable without a proprietary service or model.

The reference implementation has no privileged claim. A conforming external runtime can reach the same profile by producing the same evidence. Project-specific cartridges may be private while their schema, conformance result, and bounded claim scope remain portable.

## Change process

A proposal that changes hashing, required fields, effect semantics, authority semantics, admission rules, or conformance requirements must:

1. Open a public issue describing the interoperability problem.
2. Provide at least two implementation examples or one implementation and one test vector.
3. Include migration and downgrade behavior.
4. Add or update JSON Schema and executable validators.
5. Add positive, negative, tamper, and cross-version tests.
6. Use a new schema identifier when old documents would change meaning.

Optional exports and extension namespaces may evolve without changing core schemas when they preserve canonical identities and do not weaken lower-profile requirements.

## Registry method

Registry entries require primary sources and conservative classifications. `documented` means the project explicitly specifies the complete axis within its scope. `partial` means it contributes a meaningful primitive but does not close the complete contract. `not_core` is not a criticism. It means the project intentionally delegates the axis elsewhere. `not_assessed` means evidence was insufficient.

Coverage changes require resealing `registry_sha256`. The generated gap report is derivative and should be regenerated in the same change.

## Claim review

A conformance claim must include the report and bundle digests and a bounded scope. Synthetic fixtures may support development-profile claims but cannot establish production qualification. A claim should be withdrawn or superseded when a critical vulnerability, dependency drift, schema incompatibility, or falsified artifact invalidates its evidence.

## Security disclosures

Security reports should identify the affected schema, profile, runtime, effect, and evidence boundary. High-priority classes include approval replay, stale-state execution, identity confusion, secret inclusion, artifact substitution, idempotency failure, prompt-injection privilege escalation, takeover bypass, false acceptance, and overclaimed production status.
