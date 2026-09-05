# FRR-ASTRA-STAGE2-EXECUTION-CONTRACT-1 — pre-observation execution contract amendment

```yaml
id: FRR-ASTRA-STAGE2-EXECUTION-CONTRACT-1
state: EXECUTION_CONTRACT_AMENDMENT_CANDIDATE
date: 2026-09-05
parent_release_head: 5c4d5b42b412232b4764cd5ebf1adc0c634e3126
parent_release_tree: b75fc13219c0cb9128358ecddfa95f1643e7e93e
stage1_join_head: 60bca963d63edca267106bc5c7725c2cc1df8dd7
law_predecessor_blob: 77abe4e177fc61e4f52f56ea64494b113f9662fc
empirical_calibration: NOT_RUN
calibration_observations: 0
model_calls: 0
provider_calls: 0
merge_authority: NONE
```

## Measured defect

The frozen Stage 2 generator computed `expected_checksum` as the first 16
hexadecimal digits of SHA-256 over the canonical final-state object. The frozen
Stage 1 task design requires a model response containing one fixed-length
hexadecimal checksum, but the admitted Stage 2 source had no answer-hidden
request renderer and no executable contract requiring the request hash/bytes.
A tool-free language model would therefore have been asked to reproduce a
cryptographic digest whose computation was not represented in the stimulus.

The observation contract also omitted several bindings required by the Stage 2
law: exact request hash/bytes, block/order, stop state, authenticated request
identifier, response model/backend fingerprint, and content-addressed raw event
evidence. No empirical observation existed when these defects were measured.

## Amendment

The v1 seed domain remains unchanged, so each `(family,K,R,replicate)`
coordinate retains its transition tables, active lanes, salts, starts, and
nonce. The executable generator/request contract advances to v2 and therefore
receives new case, manifest, plan, and observation identities.

`render_task_prompt()` emits exactly 2,982 ASCII bytes for every one of the 108
cases. It serializes all 32 lanes in fixed-width form, includes the family
algorithm and the checksum rule, and never reads or serializes
`expected_checksum`. Every generator case and plan cell binds the request
SHA-256 and byte count.

The response remains exactly 16 lowercase hexadecimal characters. Its value is
a model-computable state checksum: start sixteen zero nibbles; for every active
lane `i` with final state `s`, update bucket `i mod 16` by
`(bucket + s + 7*floor(i/16) + 1) mod 16`. For branch-reconcile, also add the
witness lane to bucket 14 and `witness_state + 1` to bucket 15, modulo 16.
Emit buckets 0 through 15.

The 648-cell denominator is unchanged. Cells are grouped into 72 deterministic
blocks keyed by `(family, replicate, control, effort)`, with all nine K/R
coordinates assigned a deterministic `order_index` from 0 through 8.

Public observations remain raw-text-free but now bind request bytes/hash,
block/order, normalized event timestamps, stop state, request-id hash,
response-model hash, backend-fingerprint hash, selected-header hash,
inter-event-time hash, and one raw-evidence SHA-256 for the private sidecar.

## Preserved authority

This amendment does not change the Stage 1 preregistration bytes, hypotheses,
K/R levels, replicates, task families, waterline-before-geometry order,
admission gates, subject endpoints, or two-stage-freeze rule. The complete
Stage 1 blob set remains verified from Git objects.

It does not bind any runtime, adapter, checkpoint execution identity, or effort
mapping. It does not authorize Bind, calibration, provider execution, numeric
freeze, release merge, or a benchmark verdict. Existing source and physical
Prepare evidence remains historical input only.

## Qualification requirements

Before this amendment can govern empirical execution, the provider-free
scaffold must regenerate the 108-case generator and 648-cell plan, verify the
committed generated indexes, pass the complete adversarial Stage 2 scaffold,
and prove request determinism, fixed byte length, answer hiding, blocked-order
closure, request drift refusal, backend drift refusal, duplicate request-id
refusal, monotonic event-time refusal, and unchanged Stage 1 custody.

A subsequent binder successor must explicitly bind the amended law and
execution-contract blobs before any empirical control manifest can become
admissible. Until then the terminal remains
`EMPIRICAL_CALIBRATION_NOT_RUN` with zero admitted observations.
