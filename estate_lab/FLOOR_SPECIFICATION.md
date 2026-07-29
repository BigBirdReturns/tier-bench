# AXM Interaction Floor Specification 1.0

## Classification

The AXM Interaction Floor is a portable interoperability protocol for semantic actions that may enter through software, human, agent, XR, game-controller, embedded, industrial, or physical-device surfaces. It defines the narrow waist between a source embodiment and a domain authority. It does not define the domain action, decide whether the actor is entitled to perform it, certify a physical device, accept a human decision, schedule work, or determine whether an observation is true.

An implementation is conformant when it preserves the request, event, authority, response, identity, refusal, replay, and lifecycle rules in this document and passes the public vectors. An implementation may be written in any language and may operate without Estate Lab or any other AXM repository.

The normative machine-readable specification is `fixtures/floor/floor.example.json`. The normative schemas are the `floor-*.schema.json` files. The normative executable behavior is the vector set under `fixtures/floor/vectors/`. Prose explains the law but may not override those artifacts.

## Actors and authority

The domain authority defines the meaning of a semantic action and decides the resulting state transition. An adapter author implements one transport, device, application, or product boundary. A source principal may be a human, agent, service, controller, or device. A verifier executes public conformance vectors. A registry admits passing submissions. A deployer decides whether a conformant adapter is suitable for a real system.

The floor owns only the portable envelope and its conformance law. An adapter consumes four authority fields:

```text
actor
role
mandate
ownership_epoch
```

An adapter may reject an incomplete or incompatible claim. It may not grant a role, broaden a mandate, advance an ownership epoch, relabel the actor, or treat receipt of a command as authority. A source that loses ownership must obtain a new epoch through the owning domain authority. A stale packet remains stale even when its value appears reasonable.

## Canonicalization and identities

Version 1 uses `utf8-sorted-json-sha256-v1`:

1. Values must be valid finite JSON. NaN and Infinity are refused.
2. Duplicate object keys are refused before interpretation.
3. Object keys are sorted lexicographically.
4. Identity-bearing JSON uses UTF-8 and compact separators with no insignificant whitespace.
5. SHA-256 produces the content digest.
6. Namespaced identifiers prefix a bounded digest fragment.

The frozen identifier families are:

```text
floor1_<32 hex>          floor specification
flooradapter1_<32 hex>   adapter declaration
floorreq1_<32 hex>       interaction request
floorevent1_<32 hex>     semantic event
floorres1_<32 hex>       interaction response
floorconf1_<32 hex>      conformance submission
floorregistry1_<32 hex>  adapter registry
floorgaps1_<32 hex>      gap ledger
```

A future move to another canonicalization scheme changes the protocol major unless every existing identifier remains byte-identical. RFC 8785 is retained as the principal cross-language comparator, but it is not silently substituted for the frozen version 1 algorithm.

## Adapter declaration

An adapter declaration uses `axm-interaction-adapter/1`. It names:

- stable adapter identity and semantic version;
- supported floor versions and profiles;
- bindings and command entrypoint;
- source and target directions;
- supported semantic operations and modalities;
- determinism, replayability, locality, and network requirements;
- authority consumption and exclusions;
- health, snapshot, and reset behavior;
- trace, privacy, accessibility, and delegation behavior;
- license expression and exact implementation-byte digests.

The declaration is self-identifying through `descriptor_id`. Any identity-bearing edit changes the expected ID. A declaration may claim profiles, but claims do not become verified profiles until the public conformance suite passes.

The command reference binding uses an argv array containing `{request}` and normally `{response}`. It may also use `{python}`, `{descriptor}`, and `{adapter_dir}`. The verifier executes the argv with `shell=False`. Scenario text and event values never become shell code.

## Interaction request

A request uses `axm-interaction-request/1` and carries:

```json
{
  "format": "axm-interaction-request/1",
  "request_id": "floorreq1_...",
  "floor_version": "1.0.0",
  "target_adapter_id": "org.example.adapter",
  "kind": "execute",
  "phase": "source",
  "sequence": 1,
  "event": {},
  "context": {}
}
```

`kind` is one of `describe`, `health`, `execute`, `snapshot`, or `reset`. `phase` is `source` or `target`. `sequence` is monotonic within a declared run when the host supplies an ordered stream. `context` carries privacy class, deadline, correlation ID, optional W3C trace context, and optional delegation.

The request ID is derived from the complete request with `request_id` omitted. A mismatched request ID is refused. An expired deadline is refused before side effects. An unknown major version is refused. An unknown extension is preserved or explicitly reported as unsupported and is never silently reinterpreted.

## Semantic event

An execute request carries `axm-semantic-event/1`:

```json
{
  "format": "axm-semantic-event/1",
  "event_id": "floorevent1_...",
  "semantic_id": "engineering.coolant_bypass.set",
  "subject": "engineering.coolant_bypass",
  "operation": "set",
  "state_path": "/engineering/coolant_bypass",
  "value": true,
  "authority": {
    "actor": "human:captain",
    "role": "engineering",
    "mandate": "ship.engineering.control",
    "ownership_epoch": 7
  },
  "causality": {
    "run_id": "run-001",
    "correlation_id": "incident-004",
    "parent_event_ids": []
  },
  "semantic_digest": "..."
}
```

Version 1 supports bounded `set`, `increment`, `append`, `remove`, and `toggle` operations. The floor does not execute those operations against domain state. The domain authority interprets the semantic action. The semantic digest covers `semantic_id`, `subject`, `operation`, `state_path`, `value`, and `authority`. An adapter may add observations around those fields but may not change them.

The event ID covers the semantic projection and causality. The same event ID with the same canonical bytes is an idempotent duplicate. The same event ID with different bytes is an identity collision and must refuse. Retries may not double-apply a side effect.

## Interaction response

A response uses `axm-interaction-response/1`:

```json
{
  "format": "axm-interaction-response/1",
  "response_id": "floorres1_...",
  "request_id": "floorreq1_...",
  "adapter_id": "org.example.adapter",
  "kind": "execute",
  "accepted": true,
  "reason": null,
  "outcome": "accepted",
  "semantic_digest": "...",
  "observations": {}
}
```

The response binds the request, adapter, kind, acceptance state, reason, outcome, and semantic digest. Accepted execute responses must reproduce the request event’s semantic digest exactly. Refusals use stable reason identifiers. The response ID is content-derived with `response_id` omitted.

An accepted adapter response proves only that the adapter accepted the envelope under its declared contract. It does not prove that the domain authority committed a state transition, that a physical actuator moved, that an external service accepted the operation, or that a human accepted an outcome. Those claims require separate receipts owned by the appropriate authority.

## Lifecycle

A conformant lifecycle adapter exposes:

- `health`, returning `ready`, `degraded`, or `unavailable`;
- `snapshot`, returning a deterministic bounded snapshot;
- `reset`, returning an explicit reset outcome;
- refusal rather than fabricated success when a dependency is absent.

Reconnect behavior must re-establish current state from an authoritative snapshot. A stale handle, old ownership epoch, or remembered analog value may not be treated as current state. Desired state and reported state remain distinguishable.

## Replay and ordering

Replayable adapters declare `deterministic=true`, `replayable=true`, and `idempotency_key=event_id`. Repeating a request in the same declared environment must produce byte-identical responses unless the descriptor explicitly declares a non-deterministic observation outside the identity projection. Version 1’s public replay profile permits no such exception.

A conformance submission records the response hash for every vector. The verifier reruns repeated vectors and compares canonical response bytes. A domain system may attach richer state and causal receipts, but those receipts remain outside the adapter’s authority.

## Observability

The observability profile carries W3C Trace Context through `context.traceparent` and structured response observations. Trace IDs correlate evidence but do not authenticate the actor, grant a role, prove semantic truth, or authorize a deployment. An implementation must preserve the distinction between telemetry and authority.

OpenTelemetry semantic conventions may be used as a projection for traces, metrics, and logs. The normative floor record remains the request, response, conformance submission, and domain-owned receipts.

## Privacy

Version 1 defines `public`, `internal`, `confidential`, and `restricted` classes. An adapter declaration states supported classes and retention behavior. An adapter may refuse a class it cannot protect. It may not silently downgrade a class or retain content contrary to its declaration.

The privacy profile is a declaration and vector boundary, not a complete privacy certification. Production adoption still requires a data-flow model covering collection, storage, export, redaction, deletion, logging, crash reports, and cross-boundary movement.

## Accessibility

The accessibility profile declares input modalities, output modalities, and fallbacks. A fallback must preserve the semantic action and authority fields. An accessible route is not permitted to become a lower-authority or lower-evidence side path.

Passing the profile proves declaration completeness. User-tested system accessibility remains a separate profile because a machine-readable claim cannot establish that real users can complete the task.

## Human and agent delegation

A delegated request may carry:

```json
{
  "delegation_id": "delegation-001",
  "principal": "human:operator",
  "delegate": "agent:assistant",
  "scope": "fixture.control",
  "may_escalate": false
}
```

The adapter preserves the delegation ID and may refuse an unsupported delegate. It may not set `may_escalate=true`, broaden scope, replace the human principal, or infer that a successful tool call authorizes a later action. Agent protocols such as MCP or A2A may transport requests, but the floor envelope remains the authority-bearing execution boundary.

## Supply evidence

The supply profile binds a license expression and exact artifact digests in the adapter declaration. Optional SBOM and provenance references may point to SPDX, CycloneDX, SLSA, in-toto, or Sigstore products. Those products supplement the floor declaration. They do not replace the descriptor ID or conformance submission.

A supplier enters production only after acquisition, semantic-conformance, substitution, and rip-out tests. A passing adapter descriptor does not establish that the upstream runtime is maintained, secure, fast enough, legally usable in a particular deployment, or safe for physical operation.

## Binding model

`command-json@1` is the normative reference binding. Other bindings are projections over the same core envelopes:

- CloudEvents supplies common event metadata.
- AsyncAPI describes channels and message schemas.
- MQTT 5 supplies asynchronous topics, correlation data, and sessions.
- WebSocket carries one JSON envelope per message.
- OSC carries media-oriented addresses with authority in a companion envelope.
- WIT exposes a sandboxed Component Model interface.
- W3C WoT Thing Descriptions expose device affordances without becoming authority.

A binding may change transport mechanics. It may not change semantic identifiers, authority, identity, or refusal law. Each production binding requires its own conformance cell and replacement test.

## Versioning and migration

The floor follows semantic versioning. The same major is potentially compatible, but each claimed minor must pass the applicable vectors. A breaking field, identity, canonicalization, authority, refusal, or profile change requires a new major. Additive optional fields require extension preservation and compatibility vectors.

A migration publishes:

1. the new specification and schemas;
2. old and new vector sets;
3. an explicit compatibility statement;
4. a migration function or refusal path;
5. an authority review;
6. a deprecation schedule;
7. a resurrection test.

## Evidence boundary

A floor conformance pass proves that the named adapter bytes and declaration passed the named profiles and vectors. Registry admission proves that a passing bronze-or-higher submission was structurally admitted. Neither proves domain correctness, product quality, physical safety, accessibility in use, legal compliance, supplier security, operational readiness, or deployment authority.

The control question is whether an external implementation can accept the same semantic action through a different embodiment, preserve the actor and authority envelope, survive refusal and replay, and return a verifiable response without importing another project’s law.
