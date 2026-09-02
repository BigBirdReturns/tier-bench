# Interaction Floor Binding Guide

The core floor is transport-neutral. A binding carries the same request and response objects and may add transport-specific correlation, addressing, delivery, or session metadata. It may not alter semantic fields, authority, identities, or refusal behavior.

## Command JSON

`command-json@1` is the normative reference. The verifier invokes an argv with request, response, and descriptor paths using `shell=False`. It is suitable for local processes, CI, scripting languages, and wrappers around vendor SDKs.

## CloudEvents JSON

A structured CloudEvents mapping uses:

```text
id          request_id
source      adapter or host URI
specversion CloudEvents version
type        semantic_id or request kind
subject     semantic subject
datacontenttype application/vnd.axm.interaction-request+json
data        complete floor request
```

The CloudEvents envelope is transport metadata. The complete floor request remains the normative payload.

## AsyncAPI

The floor provides a deterministic AsyncAPI 3 projection with request and response channels and references to the JSON schemas. Generated AsyncAPI documents are derived products. Manual edits do not change the floor specification.

Render the projection:

```bash
python -m estate_lab floor describe --format asyncapi --output interaction-floor.asyncapi.yaml
```

## MQTT 5

A default mapping uses request and response topic families, `Response Topic`, `Correlation Data`, content type, message expiry, and retained lifecycle topics. MQTT delivery QoS does not replace event idempotency. Broker authentication does not grant a floor role or mandate.

## WebSocket JSON

Each frame carries one complete request or response object. The connection may carry session health and backpressure, but reconnection requires an authoritative snapshot and cannot revive stale ownership.

## OSC and OSCQuery

OSC addresses may mirror semantic identifiers for low-latency show and media control. OSC values alone do not carry the complete authority envelope. A companion floor envelope or trusted session binding is mandatory for authority-bearing actions. OSCQuery may expose discoverable controls and ranges, but discovery metadata does not grant permission to operate them.

## WebAssembly Component Model

`wit/interaction-floor.wit` defines a strict component world. A component receives a portable request and returns a response. The host supplies only explicit imports. The WIT projection is a sandbox and language-binding surface, while JSON vectors remain the frozen cross-language ground truth.

## W3C Web of Things

A Thing Description projection maps properties, actions, events, and forms to adapter capabilities. Thing metadata improves discovery and interoperability. Floor requests still carry actor, role, mandate, ownership, privacy, deadline, and causality.

## Binding conformance

The current public executable reference covers command JSON. CloudEvents, MQTT, WebSocket, OSC, WIT runtime, and WoT bindings are specified mappings that still require live conformance cells. A binding reaches production status only after two independent implementations round-trip the complete vector set and pass a supplier substitution test.
