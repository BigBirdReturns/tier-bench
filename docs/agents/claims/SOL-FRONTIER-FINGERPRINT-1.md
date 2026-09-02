# SOL-FRONTIER-FINGERPRINT-1

```yaml
id: SOL-FRONTIER-FINGERPRINT-1
owner: sol
lane: driver
state: implementation_in_reachable_custody
authorized_by: operator
authorized_at: 2026-09-01
branch: codex/frontier-fingerprint-20260901
implementation:
  - frontier_fingerprint/
  - scripts/frontier_fingerprint.py
  - scripts/frontier_qualification.py
  - tests/test_frontier_fingerprint.py
  - tests/test_frontier_qualification.py
  - experiments/frontier_fingerprint/
  - schemas/frontier-fingerprint-manifest.schema.json
  - schemas/frontier-fingerprint-receipt.schema.json
  - schemas/frontier-fingerprint-summary.schema.json
  - schemas/frontier-fingerprint-qualification.schema.json
  - schemas/frontier-fingerprint-qualification-index.schema.json
  - .github/workflows/frontier-fingerprint.yml
qualification_authority:
  source_binding: exact_source_head
  receipt_schema: tier-bench/frontier-fingerprint-qualification@1
  publication_index_schema: tier-bench/frontier-fingerprint-qualification-index@1
  workflow: .github/workflows/frontier-fingerprint.yml
  pr_comment_marker: frontier-fingerprint-qualification
manual_closure_ledger: prohibited
live_provider_dispatch: prohibited_in_committed_manifests
benchmark_verdict_authority: none
```

The first branch head, `94851d5`, contained only this claim path. The previously reported harness files and dedicated green workflow were not in reachable custody. The standing repository workflows passed a documentation-only diff, so they did not qualify the observatory. Any session-local test, file, artifact, comment, or status assertion attached to that head had no standing outside its session workspace.

The implementation and its closure mechanism are separate controls. The observatory rebuilds exact requests from the frozen manifest and generator, authenticates retained request and response bodies, and rederives usage, identity, stopping state, and exact synthetic-anchor results. The qualification control checks out the exact pull-request source head, inventories the base-to-head path set, discovers the full committed manifest set by schema, derives test counts from the emitted unittest ledger, reconciles all campaign counts, rejects public-text canaries, checks a declared provider-credential environment set, and emits a hash-bound qualification receipt.

The workflow uploads only the public-safe receipt, plan, run record, verification, summary, passive observations, receipts, and test ledger. It then publishes or updates a marker-bearing pull-request comment from the receipt, records the returned GitHub comment identity with the evidence artifact identity in a second machine-readable index, replaces the comment with a final rendering that names both artifacts, and reads the comment back from GitHub for byte-for-byte comparison. Raw request and response bodies remain inside the ephemeral private run directory and are not placed in the public-safe workflow artifacts.

This claim document carries no PASS count, current head, workflow-run ID, artifact ID, or comment ID. Those values change when the branch changes and therefore belong only to the generated receipt, returned Actions artifact objects, workflow log, and verified GitHub comment. Network egress is explicitly `UNMEASURED`. Live provider behavior, frontier capability, live cache behavior, provider cost, and routing remain `UNMEASURED` until separately authorized evidence exists.
