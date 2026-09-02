# Frontier fingerprint observatory

This observatory measures externally reachable signatures of provider prefix caching, client transcript compaction, retained-context behavior, request serialization, tool-schema placement, effort settings, and response-side identity. It does not infer physical KV-cache bytes, tensor representation, compression, eviction policy, fleet topology, provider cost, or margin.

The active lane writes exact request and response bodies only under a private run directory. Each receipt hashes those exact bytes. `verify` rebuilds every request from the frozen generator and manifest, then rederives normalized usage and identity objects from the retained response body. Recomputing the receipt chain after altering a usage field is insufficient because the verifier compares the rewritten envelope against the independently hashed provider body.

Cache latency is designed as an interleaved within-block comparison. Each block primes one unique prefix, then alternates the order of the exact-prefix warm request and an early-prefix mutation. Summaries report median, range, interquartile range, and paired sign counts. Latency remains corroborating evidence. Provider-reported cache-read and cache-creation counters remain the primary cache signal.

Identity evidence is adapter-specific. A returned backend or system fingerprint is classified as strong. A response-side model string without a backend fingerprint is classified as weak. No response identity is classified as none. Every call compares the response-side model string, when present, with the manifest-resolved model binding and marks a mismatch in the receipt itself.

The passive lane retains source-file and source-record hashes, numeric usage, known model fields, backend fingerprints, and structural compaction-key paths. It never retains prompt text, response text, quoted excerpts, source paths, session IDs, or free-form marker values. Abrupt context-drop candidates are derived from token-count discontinuities only.

Example release manifests remain live-disabled. `TIER_FABLE_51_MODEL` and `TIER_ASTRAL_MODEL` are bindings, not assertions that a marketing label is callable. A live run requires a private manifest with a pinned price table and positive ceiling, `execution.allow_live: true`, the `--live` CLI gate, the exact `TIER_FRONTIER_LIVE` acknowledgement, and the provider credential. No retries occur inside a measurement cell.

## Provider-free qualification

```bash
python -m py_compile \
  frontier_fingerprint/*.py \
  scripts/frontier_fingerprint.py \
  scripts/frontier_qualification.py \
  tests/test_frontier_*.py
python -m unittest discover -s tests -p 'test_frontier_*.py' -v

run_dir="$(mktemp -d)/frontier-run"
python scripts/frontier_fingerprint.py plan \
  --manifest experiments/frontier_fingerprint/mock-smoke.json \
  --out "${run_dir}.plan.json"
python scripts/frontier_fingerprint.py run \
  --manifest experiments/frontier_fingerprint/mock-smoke.json \
  --out "$run_dir"
python scripts/frontier_fingerprint.py verify --run-dir "$run_dir"
python scripts/frontier_fingerprint.py summarize \
  --run-dir "$run_dir" \
  --out "${run_dir}.summary.json"
```

The dedicated GitHub workflow performs the provider-free sequence from the exact pull-request source head. A green standing repository workflow over a documentation-only diff is not evidence that this observatory passed. Qualification attaches only to a reachable source head containing the implementation, the closure script, the schemas, the adversarial tests, and the dedicated workflow.

## Machine-derived closure custody

`scripts/frontier_qualification.py` derives the closure ledger from Git, unittest output, campaign JSON, the public receipts file, passive observations, and every committed manifest carrying schema `tier-bench/frontier-fingerprint-manifest@1` under `experiments/frontier_fingerprint`. It refuses a source-head mismatch, missing or ambiguous test counts, disagreement among planned, executed, authenticated, and rederived counts, identity or provider errors, an enabled committed live manifest, a recognized provider credential in the runner environment, a forbidden public-text marker, or a mismatched receipt payload hash.

A passing run uploads a public-safe evidence artifact containing the machine receipt and its supporting files. The workflow uses the artifact ID, artifact URL, and upload digest returned by GitHub to render a pull-request comment. It records the returned comment ID and evidence artifact identity in a publication-index object, uploads that index as a second artifact, renders the final comment with both artifact identities, and reads the comment back from GitHub for exact comparison. The pull-request body and this README intentionally contain no current test count, receipt count, head SHA, run ID, comment ID, or artifact ID because those fields must be re-derived after every source-head change.

The closure receipt qualifies implementation custody and provider-free conformance. Its measurement authority leaves live provider behavior, frontier capability, live cache behavior, cost, and routing as `UNMEASURED`; it also records network egress as `UNMEASURED`. Opaque provider request identifiers remain hash-only in public receipts. Contract-version headers, rate-limit or processing telemetry, and request identifiers are summarized separately so volatile transport metadata cannot masquerade as an API revision.
