# Surface Interop security policy

## Supported software line

The production line is `1.x`. Security fixes are applied to the latest minor release. A protocol-major change receives a separate support declaration because canonical identities, refusal behavior, and compatibility rules may change. Historical conformance submissions remain verifiable against their bound floor and verifier identities.

## Trust model

Surface Interop verifies protocol behavior. It does not authenticate the actor named by a request, grant a role or mandate, approve a deployment, certify device safety, or accept a domain outcome. The domain runtime remains responsible for authentication, authorization, semantic meaning, safety, and final state mutation.

The hardened runner treats every adapter descriptor, command, request, response, observation, archive, and registry submission as untrusted input. Production execution is disabled until the operator supplies `--allow-exec`. Once admitted, it uses an argv array with `shell=False`, a secret-minimizing environment, a closed stdin, a separate process group, bounded time and output, response-size limits, strict duplicate-key JSON, same-directory atomic publication, supply-pinned local entrypoints, and path-containment checks.

## Default refusals

The runner refuses implicit adapter execution, malformed or oversized JSON, duplicate keys, unknown protocol majors, identity drift, semantic-digest mutation, incomplete authority envelopes, expired requests, unpinned local entrypoints, artifact digest mismatch, path traversal, symlinks in release source, subprocess timeout, bounded-output overflow, nonzero adapter exit, malformed response output, duplicate archive paths, archive traversal, missing checksums, and tampered release bytes.

Network isolation cannot be inferred from `network_required=false`. That field is a declaration. Deployments that require enforced isolation must execute the runner inside an operating-system sandbox, container, virtual machine, or network namespace whose policy is held outside the adapter. A conformance report must not be described as proof of network containment unless the containment receipt is separately retained.

## Secret handling

Adapter subprocesses receive only an allowlisted set of operating-system variables. Common token, credential, authorization, cookie, password, and private-key names are removed. Support bundles contain hashes, counts, versions, and check results. They exclude environment values, request and response bodies, absolute source paths, credentials, and user content.

## Supply-chain controls

Every locally executed adapter entrypoint must be listed in the descriptor supply artifacts and match its declared SHA-256 digest. A production release is deterministic, contains a file-level SPDX 2.3 inventory, a release manifest, checksums, a validation receipt, and a detached archive digest. L4 substitution claims still require a supplier-independent replacement or rip-out receipt. Registry presence does not waive supply review.

## Vulnerability reporting

A report should name the affected format, profile, binding, vector, verifier version, adapter version, and the smallest reproducer that demonstrates the failure. Do not include live credentials or private user data. Until a private disclosure address is published, use a GitHub security advisory for the repository rather than a public issue. The repair record must identify affected versions, corrected bytes, new negative vectors, compatibility impact, and residual risk.

## Security invariants

A security repair is incomplete unless the old failure is represented by a permanent negative test. The control question is whether an untrusted adapter can cause semantic mutation, authority expansion, hidden code execution, resource exhaustion, evidence laundering, or supply substitution without producing a deterministic refusal and inspectable receipt.
