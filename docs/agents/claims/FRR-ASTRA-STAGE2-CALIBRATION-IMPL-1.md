# FRR-ASTRA-STAGE2-CALIBRATION-IMPL-1

```yaml
id: FRR-ASTRA-STAGE2-CALIBRATION-IMPL-1
owner: connected-campaign-session
lane: driver
state: provider_free_closed_object_repair_candidate
coordination_issue: BigBirdReturns/tier-bench#172
initial_claim_comment: 5516162757
collision_resolution_comment: 5517243922
first_independent_audit_comment: 5518268907
first_repair_claim_comment: 5518704609
independent_reaudit_comment: 5519317271
closed_object_repair_claim_comment: 5519576043
branch: joint/astra-stage2-calibration-impl-20260902
joined_parent: 60bca963d63edca267106bc5c7725c2cc1df8dd7
first_repair_parent: 0359d1d7475bd5b1769c2568c318a1925d0aff79
closed_object_repair_parent: 51e09f567437e856ef7a6b5a707cffa52d843d4a
preserved_ancestry:
  substrate: e938bd92e81bb7abfd6e0009d0360c7764808be8
  stage_1: a855b1bcc871753e44b0a10acf5440ccf96fcffe
  first_freeze: ea451a9e6894c10b09666606d4a445d8cc2826e4
law_path_owner:
  claim: FRR-ASTRA-STAGE2-2-LAW
  comment: 5516294861
  path: docs/agents/claims/FRR-ASTRA-STAGE2-1.md
implementation_surface:
  - astra_stage2/**
  - experiments/astra_kxr/stage2/**
  - schemas/astra-stage2-*.schema.json
  - scripts/astra_stage2_calibration.py
  - tests/test_astra_stage2_calibration.py
  - .github/workflows/astra-stage2-calibration.yml
repair_controls:
  deterministic_answers: every planned answer must be accepted
  observation_properties: exact runtime property set before record hash acceptance
  result_properties: exact runtime property set before result hash acceptance
  generator_manifest_properties: exact top-level and case property sets before self-hash acceptance
  control_manifest_properties: exact manifest, control, and identity property sets before binding or self-hash acceptance
  calibration_plan_properties: exact top-level and row property sets before self-hash acceptance or derivation
  direct_derivation_binding: plan and control-manifest closed shapes are revalidated before observations contribute
  stage_1_identity: canonical Git HEAD blobs plus clean index and worktree
  derivation_stage_1_binding: every fixture or empirical result invokes Stage 1 verification
  windows_checkout: clean CRLF checkout must verify against committed LF blobs
live_provider_dispatch: prohibited
stage_2_numeric_freeze: prohibited
callable_astra_identity: unbound
optional_24_call_block: disabled
merge_authority: none
```

This claim implements only the provider-free calibration scaffold permitted by the amended path lease on issue #172. The Sol-law claim retains sole ownership of `docs/agents/claims/FRR-ASTRA-STAGE2-1.md`; this branch neither creates nor modifies that path.

The scaffold freezes a deterministic 108-case generator denominator, compiles the complete 648-observation calibration plan, verifies exact task reconstruction, ingests identity-bound local observations, derives normalized shape envelopes, and refuses incomplete, duplicated, route-drifted, contract-drifted, text-retaining, non-finite, incorrectly graded, or statistically overlapping evidence.

Audit comment `5518268907` demonstrated that the first qualified scaffold could admit one correctly marked wrong answer, accept an unknown observation property, and compute Stage 1 identities from CRLF worktree bytes without composing custody verification into empirical derivation. The first repair closed those routes. Re-audit comment `5519317271` then demonstrated that an unknown `notes` property inside an empirical control identity could still be bound, self-hashed, and carried into `EMPIRICAL_CALIBRATION_CANDIDATE`.

Closed-object repair claim `5519576043` therefore treats the committed schemas as declarations rather than runtime gates. Generator manifests and cases, control manifests, controls and identities, calibration plans and plan rows, observations, and results each have an explicit runtime property set. Unknown properties are rejected before the containing object is self-hash accepted or identity-bound. Direct derivation revalidates the closed plan and control-manifest shapes before any observation contributes.

Fixture evidence remains permanently classified `FIXTURE_CONFORMANCE_ONLY`. Empirical evidence may become only a candidate or an inconclusive calibration after all 648 observations pass the repaired contracts. The implementation contains no transition to `STAGE2_FROZEN`, no provider adapter, no credential path, no Astra identity, and no authority to activate the optional geometry block. A later runtime successor must bind the exact released Sol-law blob and independently qualify any authority-bearing change.
