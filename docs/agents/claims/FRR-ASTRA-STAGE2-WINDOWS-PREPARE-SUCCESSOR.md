# FRR-ASTRA-STAGE2-WINDOWS-PREPARE-SUCCESSOR — convergence candidate

```yaml
id: FRR-ASTRA-STAGE2-WINDOWS-PREPARE-SUCCESSOR
state: CONVERGENCE_CANDIDATE_QUALIFICATION_PENDING
date: 2026-09-04
qualified_binder_parent: dbb44b7efca1b04f2ed2d8c127af653b278909e4
qualified_binder_tree: 2671247337030d9c8e281393103104f7436d2800
qualified_portability_parent: 0e790fea09668e5f537bdd00fcb2bdb3364855c3
qualified_portability_tree: 5a95423cc5dee0fa7ffc893fb3f41634ef735b3f
qualified_portability_carrier: f558ab3ff48ff85d1358d57468ea359608e9f1d5
qualified_portability_run: 33899335376
law_head: c36c35bf9b70d879e1e1c9ee2f0296879442df3e
law_blob: 77abe4e177fc61e4f52f56ea64494b113f9662fc
convergence_qualification: STILL_PENDING
actual_executable_identities: UNBOUND
physical_prepare: NOT_RUN
model_calls: 0
provider_calls: 0
calibration: NOT_RUN
numeric_freeze: NOT_ISSUED
checkpoint_succession: NOT_ISSUED
merge_authority: NONE
```

## Classification and lineage

This tree is a convergence candidate derived from two separately qualified
parents. `dbb44b7` is the qualified binder product and supplies the active
binder implementation, schemas, law binding, and complete 34-test core
witness. `0e790fea` is the qualified portability repair and supplies the
WinError-1314-only symlink behavior plus the retained release surfaces.

The commit `f558ab3` is an audit-only hosted carrier for the portability
subject. It is evidence about `0e790fea`; it is not a parent, implementation,
or release candidate. The B353 execution record remains immutable historical
fail-closed evidence and is not evidence that this convergence tree has run a
physical Prepare.

The earlier native-Windows binder lineage is superseded history, not the
active implementation or active law of this candidate. The active coordinates
are the qualified binder and law coordinates in the ledger above.

## Candidate contract

The candidate preserves the qualified binder's typed platform and topology
evidence. A Windows probe is restricted to one selected device and records
`NOT_APPLICABLE_SINGLE_SELECTED_DEVICE` with
`PLATFORM_LIMITATION_SINGLE_DEVICE`, without claiming inter-device topology or
implicit pooling. A Linux probe records an observed `NVIDIA_SMI_TOPO_MATRIX`
and does not claim implicit pooling. The dormant Prepare source binds the
probe receipt, all three evidence-file digests, the topology-evidence digest,
the selected-device singleton, and the canonical payload digests.

The release workflow is a provider-free convergence qualification surface. It
parses both PowerShell execution surfaces, exercises the complete 43-test
denominator on Windows and Linux, tests digest refusal and Git byte custody,
and applies the observed-privilege rule to the sole portable symlink witness.
It does not execute Preflight, Prepare, Bind, or checkpoint Retry.

## Pending gate and authority

Convergence qualification is **STILL PENDING** until the eventual exact
release head and tree complete the hosted Windows and Ubuntu workflow. No
qualification, publication, checkpoint succession, physical Prepare,
calibration, numeric freeze, or executable identity follows from construction
of this local tree.

At this gate the actual executable identities remain **UNBOUND**, physical
Prepare is **NOT_RUN**, model calls are **0**, provider calls are **0**,
calibration is **NOT_RUN**, numeric freeze is **NOT_ISSUED**, checkpoint
succession is **NOT_ISSUED**, and merge authority is **NONE**.
