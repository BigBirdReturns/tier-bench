# SOL-FRONTIER-FINGERPRINT-1

```yaml
id: SOL-FRONTIER-FINGERPRINT-1
owner: sol
lane: driver
state: implemented_pending_exact_head_ci
authorized_by: operator
authorized_at: 2026-09-01
branch: codex/frontier-fingerprint-20260901
implementation:
  - frontier_fingerprint/
  - scripts/frontier_fingerprint.py
  - tests/test_frontier_fingerprint.py
  - experiments/frontier_fingerprint/
  - schemas/frontier-fingerprint-manifest.schema.json
  - schemas/frontier-fingerprint-receipt.schema.json
  - schemas/frontier-fingerprint-summary.schema.json
  - .github/workflows/frontier-fingerprint.yml
live_provider_dispatch: prohibited_in_committed_examples
benchmark_verdict_authority: none
```

The first branch head, `94851d5`, contained only this claim path. The previously reported harness files and dedicated green workflow were not in reachable custody. The standing repository workflows passed a documentation-only diff, so they did not qualify the observatory. The local-session test ledger attached to that head had no evidentiary standing outside the session workspace.

This successor materializes the implementation bytes. The verifier rebuilds every exact request from the frozen manifest and generator, authenticates the retained provider-response bodies, then rederives normalized usage, identity, stopping state, and exact synthetic-anchor results from those bodies. Rewriting the receipt envelope and recomputing its chain cannot substitute for the evidence body. Missing or altered bodies fail closed.

Cache latency is an interleaved repeated measure and remains corroborating evidence. Provider-reported cache-read and cache-creation counters are primary when present. Identity strength is reported per adapter. A backend fingerprint is strong, a response-side model string alone is weak, and absent response identity is none. Every response-side model string is compared with the resolved manifest binding on every call.

The passive lane retains structural marker paths and numeric accounting only. It does not retain transcript text, prompt text, response text, quoted excerpts, source paths, session identifiers, or free-form marker values. Provider API contracts and usage semantics are hash-bound per campaign, and token-accounting comparisons are refused when those contracts differ.

No PASS statement attaches to this claim merely because local tests ran. Qualification requires the dedicated `frontier-fingerprint` workflow to execute from the exact reachable candidate head containing the implementation and workflow bytes. Live provider calls remain disabled in every committed example and require a separately priced private manifest plus all three dispatch gates.
