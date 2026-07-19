# MONSTER-WRANGLER-1 claim

- **Owner:** sol
- **Lane:** driver
- **Claimed:** 2026-07-19
- **Authority:** direct operator instruction in the connected GitHub session
- **Branch:** `codex/monster-wrangler-v1`

Build the repository-custodied Monster Wrangler application as the human-facing control plane for durable, resumable, evidence-judged agent work. The intended product includes a persistent task DAG, operator approvals, scheduling, bounded concurrency, spend controls, cartridge selection, sealed `tier run` execution, receipt verification, crash recovery, emergency stop, and a local browser interface that can be closed without losing work.

This claim does not authorize benchmark task disclosure, grader or pass-criterion changes, pilot activation, automatic merge, credential custody, provider OAuth extraction, or a model call during implementation tests. Runtime execution remains delegated to committed backend manifests and the existing fail-closed `tier run` contract. A run is successful only when its emitted receipt verifies.

The implementation is a first production-capable vertical slice on the path to the complete application, not a disposable demonstration. The evidence target is deterministic tests plus CI-green review on this branch.
