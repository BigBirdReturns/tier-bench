# SOL-FRONTIER-FINGERPRINT-1

```yaml
id: SOL-FRONTIER-FINGERPRINT-1
owner: sol
lane: driver
state: claimed
authorized_by: operator
authorized_at: 2026-09-01
branch: codex/frontier-fingerprint-20260901
scope:
  - deterministic provider request construction
  - Claude Messages and OpenAI Responses adapters
  - cache, context, transcript, identity, drift, serialization, effort, and tool probes
  - hash-chained receipts, replay verification, summaries, and matched-cell comparison
planned_evidence:
  - scripts/frontier_fingerprint.py
  - tests/test_frontier_fingerprint.py
  - experiments/frontier_fingerprint/
  - schemas/frontier-fingerprint-*.schema.json
  - .github/workflows/frontier-fingerprint.yml
live_provider_dispatch: prohibited_until_explicit_operator_run
benchmark_verdict_authority: none
```

The operator directly authorized construction of a frontier-model fingerprinting harness after the public release of Claude Fable 5.1 and the announcement of OpenAI Astra. This is driver-lane instrumentation work. It does not modify hidden graders, standing pass criteria, task definitions, ledger closure rules, or any existing benchmark verdict.

A local prototype was assembled during the interactive dispatch before this repository claim could be committed. That prototype made no live provider request, minted no provider receipt, and produced no comparative model claim. Only provider-free mock observations may be used while the implementation is under review. Any later Fable, Astra, or other paid run requires an explicit manifest enablement, environment-provided credential, and operator-controlled execution.

The measurement boundary is binding. Provider-reported cached-token counts, cache-creation counts, model identifiers, system fingerprints, output behavior, latency, and manifest-bound prices are observable. Physical KV-cache size, compression method, memory representation, fleet topology, provider cost, and margin are not observable through these APIs and must remain `UNMEASURED`.
