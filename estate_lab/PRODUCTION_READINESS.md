# Surface Interop production readiness

## Release classification

Version `1.0.0` is the production software boundary for the public protocol and reference verifier. It freezes the protocol-major identity projections, strict JSON rules, semantic digest, authority envelope, command-json binding, conformance submission, registry projection, and release-verification format. Physical L5 commissioning remains an external evidence boundary and is not required for software release integrity.

## Acceptance gates

A release is admissible only when all of the following pass on a carrier-free source tree:

1. Python compilation and the complete unit suite on Linux, Windows, and macOS.
2. Python 3.10 through 3.13 compatibility on the declared matrix.
3. Floor specification, adapter descriptor, gap ledger, commodity ledger, and every JSON schema parse under strict duplicate-key handling.
4. Positive vectors and permanent negative vectors through the hardened runner.
5. Timeout, output overflow, secret-environment stripping, response-size refusal, entrypoint-pin mismatch, archive traversal, duplicate archive path, checksum tamper, and atomic-publication tests.
6. Repeated conformance with identical submission identities and response hashes.
7. Deterministic release builds with identical archive digests.
8. Clean-extract installation, doctor, reference conformance, detached report verification, and release verification.
9. A file-level SPDX inventory, release manifest, complete checksums, validation receipt, detached archive digest, build-provenance attestation, and SPDX SBOM attestation for tagged releases.
10. No one-shot transport payload, generated run directory, credential, local absolute path, or publication carrier in the review tree.

## Operational invariants

An adapter cannot grant authority or rewrite semantic fields. A request is applied at most once per event identity. An expired or stale request cannot regain control. A response must bind request, adapter, kind, and semantic digest. A local entrypoint must be pinned to declared supply bytes. A failure must be bounded by time, output, and file-size limits. Accepted reports and releases must be crash-safe, content-addressed, atomically published, complete-checksum covered, and independently verifiable offline. A verifier must reject unaccounted archive members and may not overwrite an existing conformance bundle.

## Compatibility policy

Patch releases may improve diagnostics and hardening without changing accepted protocol objects. Minor releases may add optional profiles, bindings, schemas, and vectors while preserving all `1.x` accepted and rejected objects. A change to canonicalization, required authority, identity projection, core refusal behavior, or existing field meaning requires `2.0.0` and migration vectors. Historical submissions are never silently upgraded.

## External evidence boundaries

The floor does not certify domain meaning, actor authentication, legal compliance, accessibility in use, network containment, physical safety, hardware calibration, or deployment approval. Those authorities may attach evidence to a conformance record, but the verifier cannot mint them. Production readiness requires that these boundaries remain visible rather than being converted into software checkboxes.

## Rollback

Every release retains the prior deterministic ZIP, manifest, SBOM, checksums, and conformance vectors. Rollback restores the prior package as a whole. Individual protocol files are not cherry-picked across release identities. A supplier rollback also restores the prior descriptor and artifact bytes and reruns the bound conformance suite.

## Control question

Can a clean machine install the released bytes, reject malicious or malformed adapters within bounded resources, reproduce every identity, verify the release without the network or original repository, and replace any supplier without changing semantic law or authority?
