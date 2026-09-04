# FRR-ASTRA-STAGE2-CONTROL-IDENTITY-1

```yaml
id: FRR-ASTRA-STAGE2-CONTROL-IDENTITY-1
owner: connected-campaign-session
lane: driver
state: IMPLEMENTATION_CANDIDATE
claim_comment: 5526608348
branch: joint/astra-stage2-control-identities-20260903
qualified_scaffold_parent: 9babad4631ef517485c56ea4906aab123e30fad7
released_law_parent: c36c35bf9b70d879e1e1c9ee2f0296879442df3e
released_law_blob: 77abe4e177fc61e4f52f56ea64494b113f9662fc
stage1_join_head: 60bca963d63edca267106bc5c7725c2cc1df8dd7
provider_calls: 0
model_calls: 0
empirical_observations: 0
numeric_stage2_freeze: NOT_ISSUED
callable_astra_identity: UNBOUND
live_provider_dispatch: PROHIBITED
optional_24_call_block: DISABLED
merge_authority: NONE
```

This transaction binds the qualified provider-free scaffold and the released Sol
Stage 2 law by exact Git ancestry, then adds a fail-closed executable-identity
binder for the three local calibration controls. It does not contain local model
weights, private paths, empirical observations, numeric thresholds, an Astra
identifier, credentials, or dispatch authority.

The binder creates one private evidence graph for each control and one public,
path-free receipt set. The private graph includes the clean exact source checkout,
checkpoint revision evidence, every file under the checkpoint root, selected
model and tokenizer configuration, weight index and every ordered shard, the
complete runtime root, runtime version probe, adapter or explicit `NONE`,
quantization or explicit `NONE`, platform-specific versioned hardware topology
evidence, and the distinct low/high effort mappings. It then derives the six
digest fields consumed by the existing empirical control manifest, reconstructs
the complete 648-row plan, and
binds both to the exact law, Stage 1, scaffold, and generator coordinates.

The implementation refuses mutable or substituted public coordinates, dirty
source repositories, missing or duplicate files, mismatched weight indexes,
revision claims without local evidence, symbolic links, root escapes, incomplete
runtime probes, identical effort mappings, absent selected devices, unknown
properties, public path leakage, local byte drift, platform or selected-device
substitution, topology-record or query-digest drift, empty or failed Linux
topology queries, Windows multi-device selection without an independently
qualified topology source, authority-widening inter-device or pooling claims,
and a result that cannot be reproduced from retained private evidence. Linux
retains exact successful `nvidia-smi topo -m` stdout; Windows single-device
evidence records only the platform limitation and never invokes that command.

Provider-free CI uses only synthetic temporary artifact trees. Passing CI means
the binder and refusal controls are qualified. It does not mean LOTUS 3B,
LoopCoder-v2 7B, or the conventional control has been downloaded, hashed,
executed, or admitted. The actual control set remains `UNBOUND` until the binder
runs on the local estate and its private and public receipts are retained.

**Control question:** Can every public control digest be reproduced from the
retained private graph while no private root, checkpoint body, device UUID, or
runtime output crosses into the public receipt?
