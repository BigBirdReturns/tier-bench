# CLAUDE-FRR-ASTRA-PREREG-1

```yaml
id: CLAUDE-FRR-ASTRA-PREREG-1
owner: claude
lane: driver
state: prereg_stage1_in_reachable_custody
authorized_by: operator
authorized_at: 2026-09-02
branch: claude/astra-kxr-prereg-20260902
supersedes: CLAUDE-ASTRA-KXR-PREREG-1 (campaign-design scope only)
program: Frontier Residue Refinery
doctrine_lineage: agent/frontier-residue-refinery-v1 @ 57bf971d (2026-07-26)
qualified_observatory_head: 18e511d7203bec5cc681204e9401f2cdfc0f94ab
surface:
  - experiments/astra_kxr/FRR-ASTRA-1.md
  - experiments/astra_kxr/FRR_ASTRA_1_RULES.json
implementation: none_yet
stage_2_required_before_any_subject_call: true
live_provider_dispatch: prohibited
subject_model_binding: none
benchmark_verdict_authority: none
manual_closure_ledger: prohibited
```

FRR-ASTRA-1 re-registers the Astra campaign as a Frontier Residue Refinery
amendment. It supersedes exactly one thing in ASTRA-KXR-1: the unconditional
72-call K×R lattice sentinel, which contradicted the waterline-before-
geometry order stated two sections above it. Spend authority moves to the
waterline runtime; geometry becomes sidecar telemetry on justified calls,
with an operator-gated optional instrumentation block (max 24 calls,
disabled by default). Terminals, gates, analyses, the reporting-truthfulness
condition, the shape-invariant classifier, both disclosures, and the
publication rule carry forward unmodified from the ea451a9 freeze, which
remains in custody as a receipt.

The Sol-lane observatory is unmodified; this branch merges its qualified
head 18e511d7 (runs 33601616541, 33601620383) without touching Sol custody.
No test counts, run conclusions, or head assertions in this document outrank
the machine-derived receipts at exact source heads.
