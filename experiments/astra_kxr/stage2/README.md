# FRR-ASTRA Stage 2 calibration scaffold

This directory turns the Stage 1 two-stage-freeze rule into a provider-free, fail-closed calibration transaction. It does not contain an Astra model binding, provider credential, live request path, empirical local observation, or numeric Stage 2 freeze.

## Frozen denominator

The generator creates three fixed-envelope task families across `K ∈ {1,8,32}`, `R ∈ {1,4,16}`, and four deterministic replicates. That produces 108 content-addressed cases. Every case is assigned to exactly three calibration controls at two effort levels, producing a complete 648-observation plan.

The controls are role-bound rather than name-only:

```text
lotus_3b_recurrent
loopcoder_v2_7b_parallel
conventional_transformer_negative
```

The committed `generator-manifest.index.json` binds the full generated case set by payload and cases digests without storing the expanded manifest in Git. The full manifest is regenerated and retained in each CI evidence artifact.

The empirical control template records the public source coordinates available at scaffold freeze time. A local run remains inadmissible until model weights, tokenizer, runtime, adapter, and hardware identities are supplied as SHA-256 values and the manifest is rebound.

## What the scaffold derives

The scaffold derives normalized shape features from complete, accepted, route-stable observations:

```text
R elasticity
K elasticity
K curvature
R monotonicity
R non-monotonicity
reported-token-matched R contrast
effort-to-TTFT elasticity
accuracy floor
```

Intervals are q10/q90 envelopes over 12 family-by-replicate samples per control. Candidate thresholds are midpoint separators only when the required control envelopes do not overlap. Absolute local timing is never transferred to a provider subject.

## Authority boundary

Synthetic fixture evidence always returns `FIXTURE_CONFORMANCE_ONLY` with no candidate thresholds. Empirical evidence can return only `EMPIRICAL_CALIBRATION_CANDIDATE` or `CALIBRATION_INCONCLUSIVE`. This scaffold hard-codes `stage2_frozen: false` and `freeze_authority: ABSENT_IN_SCAFFOLD`.

The active Sol-law claim on issue #172 owns `docs/agents/claims/FRR-ASTRA-STAGE2-1.md`. This scaffold uses the non-colliding claim path `docs/agents/claims/FRR-ASTRA-STAGE2-CALIBRATION-IMPL-1.md`. A later authority-bearing runtime must bind the exact released Sol-law blob.

## Provider-free commands

```bash
python scripts/astra_stage2_calibration.py generator-manifest \
  --out run/generator-manifest.json

python scripts/astra_stage2_calibration.py fixture-control-manifest \
  --out run/fixture-control-manifest.json

python scripts/astra_stage2_calibration.py plan \
  --generator-manifest run/generator-manifest.json \
  --control-manifest run/fixture-control-manifest.json \
  --out run/calibration-plan.json

python scripts/astra_stage2_calibration.py fixture-observations \
  --generator-manifest run/generator-manifest.json \
  --control-manifest run/fixture-control-manifest.json \
  --plan run/calibration-plan.json \
  --out run/fixture-observations.jsonl

python scripts/astra_stage2_calibration.py derive \
  --generator-manifest run/generator-manifest.json \
  --control-manifest run/fixture-control-manifest.json \
  --plan run/calibration-plan.json \
  --observations run/fixture-observations.jsonl \
  --out run/fixture-result.json
```

The empirical transaction replaces the fixture control manifest with a locally bound manifest and replaces fixture observations with exact local receipts. It does not change the generator manifest or denominator.
