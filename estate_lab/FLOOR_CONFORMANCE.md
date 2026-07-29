# AXM Interaction Floor Conformance

## Purpose

The conformance program turns interoperability from a compatibility claim into a reproducible submission. A project may implement the floor in any language and may use any internal architecture. The verifier observes only the public descriptor, command binding, request and response envelopes, static profile declarations, and exact test results.

Conformance is intentionally narrower than deployment qualification. It establishes protocol behavior. Supplier Foundry, system-level laboratories, physical commissioning, accessibility trials, and domain authorities remain responsible for their own burdens.

## Profiles

### `core@1`

The core profile validates descriptor identity, command binding, request identity, adapter targeting, deadline refusal, required authority fields, semantic-digest preservation, explicit refusal, and supported request kinds. It includes positive describe, health, and execute vectors and negative format, target, digest, authority, deadline, and kind vectors.

### `replay@1`

The replay profile requires deterministic and replayable declarations, `event_id` idempotency, and byte-identical responses over repeated requests. A duplicate may not cause a second side effect. An altered request under the same identity must refuse.

### `lifecycle@1`

The lifecycle profile requires health states, a deterministic snapshot, reset behavior, and visible degraded or unavailable states. A missing dependency cannot be represented as success.

### `observability@1`

The observability profile requires W3C Trace Context carriage and structured observations. Trace context is correlated evidence and never authority.

### `supply@1`

The supply profile validates license metadata and exact adapter artifact digests. Optional SBOM and provenance references remain external products whose own verification is required.

### `privacy@1`

The privacy profile validates supported data classes and a declared retention policy. It includes a restricted-envelope vector. Production certification still requires a data-flow and threat model.

### `accessibility@1`

The accessibility profile validates declared input modalities, output modalities, and fallbacks. System-level user testing is deliberately outside this profile.

### `agent-delegation@1`

The agent-delegation profile preserves principal, delegate, scope, and delegation ID while forbidding authority escalation. It depends on core and observability.

## Quality tiers

| Tier | Required proof | Meaning |
|---|---|---|
| Declared | Descriptor parses | No execution claim. |
| Bronze | `core@1` | The portable semantic boundary passes. |
| Silver | Bronze plus replay and lifecycle | Retries, snapshots, reset, and failure states pass. |
| Gold | Silver plus observability, supply, and privacy | Operational evidence, exact bytes, and data-class declarations pass. |
| Platinum | All profiles, independent verifier, and substitution receipt | Compatibility is independently verified and a replacement transaction has been demonstrated. |

Accessibility and agent-delegation produce badges below platinum when verified, but platinum requires both because the top tier represents a broadly usable and governed boundary. A project cannot self-award a tier. The verifier computes the highest tier whose requirements are satisfied.

## Adapter command contract

The reference runner invokes an argv declared by the adapter. `{request}` identifies a JSON request file. `{response}` identifies the response file. `{descriptor}` identifies the declaration. `{adapter_dir}` identifies the declaration directory. `{python}` resolves to the verifier’s interpreter for the starter implementation.

The runner does not use a shell. A missing executable, timeout, nonzero exit, missing response, malformed JSON, identity mismatch, semantic mutation, or unexpected acceptance becomes a failed vector.

## Submission

A submission uses `axm-interaction-conformance/1`. It binds:

- floor ID and version;
- adapter ID, version, and descriptor ID;
- declared and verified profiles;
- computed tier and badges;
- every static and dynamic test result;
- request, response, and response hashes;
- floor, descriptor, and vector-set digests;
- verifier identity and non-authoritative environment metadata.

`submission_id` excludes machine-local environment fields and is content-derived from the normative results. Repeating the same conformance run on another machine should reproduce the same submission ID when adapter behavior is deterministic.

A bundle contains:

```text
submission.json
floor.snapshot.json
adapter.snapshot.json
SUMMARY.md
CHECKSUMS.sha256
```

The bundle is detached-verifiable with the public schemas and identity rules. Signing and transparency evidence may be layered over the bundle but may not change its internal identity.

## Registry admission

A registry uses `axm-interaction-registry/1`. It admits only passing bronze-or-higher submissions for the same floor ID. Adapter ID and version pairs are unique. A failed, declared-only, duplicate, or wrong-floor submission refuses admission.

Registry presence means that a named submission passed. It does not mean the adapter is endorsed, secure, maintained, fast enough, physically safe, legally suitable, accessible in use, or approved for a deployment. Registries must display that limit.

## Independent verification

The Python runner is the reference implementation for version 1. Platinum requires an independent implementation that accepts every valid vector and rejects every invalid vector. Independence is implementation-level, not merely a second invocation of the same package.

An independent verifier submission names its implementation and binds the same floor, descriptor, vectors, tests, and results. The conformance program should maintain at least one non-Python implementation before declaring the floor durable.

## Substitution and rip-out

Platinum also requires a content digest for a substitution receipt. The receipt must demonstrate that one supplier or adapter was removed and replaced while preserving the semantic request, authority result, committed domain state where applicable, desired outputs, causal debrief, and verification path.

A mock adapter replacing another mock is insufficient for a production supplier claim. The receipt states the exact tested version, environment, fallback, known omissions, and evidence tier.

## Public commands

Validate the retained floor, reference adapter, and gap ledger:

```bash
python -m estate_lab floor validate
```

Run the reference conformance suite:

```bash
python -m estate_lab floor test \
  --adapter estate_lab/fixtures/floor/reference-adapter/adapter.json \
  --output .floor-conformance
```

Generate a starter:

```bash
python -m estate_lab floor init-adapter ./my-adapter \
  --adapter-id org.example.my-adapter \
  --name "Example Adapter"
```

Build a registry from passing submissions:

```bash
python -m estate_lab floor registry \
  --submission .floor-conformance/floorconf1_.../submission.json \
  --output registry.json
```

Verify detached products:

```bash
python -m estate_lab floor verify-submission submission.json
python -m estate_lab floor verify-registry registry.json
```

## Failure ledger

The conformance suite preserves negative results. It does not discard a refusal because a fallback later succeeds. The result identifies the first failing boundary and retains the request and response identities when available. Public submissions should include all claimed profile results rather than cherry-picking successful vectors.

## Control question

Can a new implementation pass the public vectors, produce the same identities, fail the same negative controls, and be replaced without requiring access to AXM private state, reference implementation internals, or a vendor service?
