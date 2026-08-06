# HALO3 Cell Zero

HALO3 Cell Zero is the first executable home-lab campaign for testing the civilization-to-cell architecture against real constraints. The laboratory combines two declared RTX 3090 foundry lanes, one constrained RTX 4060 HALO3 candidate, three heterogeneous personal-node candidates, one deliberately unfamiliar peripheral, one passive physical continuity floor, and one independent evidence node. The model plane compares Fable, Kimi3, and a deterministic no-model control under one hidden-graded fingerprint contract.

The durable research object is the proof contract. A model, GPU, dashboard, provider, fixture, or successful process exit cannot accept its own result. The deterministic controller compiles the plan, admits model identity, owns hidden grading, records faults, reconciles physical outcomes, and preserves the content-addressed evidence needed for replay. Named humans retain bind, authorization, custody-transfer, role-handoff, and reconciliation authority.

## Topology

```text
PREPARATION

foundry-3090-a                    foundry-3090-b
Kimi3 exact custody               cartridge compilation
runtime and architecture probes   alternate treatments and simulation
        \                          /
         \                        /
          civilization loadout compiler
                    |
                    | signed, bounded cartridges
                    v

CELL

                 halo3-4060
     shared state, synthesis, attention, gateway
              /        |        \
          head-a     head-b     head-c
          leader     specialist scout / continuity
              \        |        /
               foreign-a + passive-floor

EVIDENCE

              evidence-node
 hidden graders, fault injection, power and network observation,
 physical outcome reconciliation, receipt custody, clean replay
```

The foundry is preparation infrastructure rather than a field dependency. The 4060 is intentionally constrained so the campaign can identify which functions deserve persistent edge residency. The three personal nodes must retain identity, accepted state, local authority, evidence access, and basic reattachment when HALO3 disappears. The evidence node remains out of the mission path and may observe or cut resources, but it may not repair the cell during a run.

## Frozen denominator

The manifest declares three model arms, nine physical and logical nodes, twelve ordered proof stages, twelve architectural claims, eight fault treatments, eight fingerprint dimensions, nine fingerprint task families, two degradation conditions, fifty-four model fingerprint cells, and twelve physical-stage cells. The complete deterministic plan therefore contains sixty-six unmeasured cells.

The model identity modes remain deliberately unequal. Fable is provider-observational and requires the request, response, prompt, tool, cost, latency, and billing envelope. Kimi3 is exact open weight and requires revision, shard, configuration, tokenizer, runtime, quantization, hardware, and prompt-template identities. The deterministic control binds exact controller, source, task, and validator bytes. The plan compares behavior while preserving those evidence differences.

## Proof sequence

The campaign first compiles the civilization loadout, then fingerprints the three model arms, proves one personal node can close a harmless local action, forms the three-head cell, measures the marginal contribution of HALO3, binds an unfamiliar peripheral through a named human, partitions the cell, removes HALO3, removes a personal node, disables active digital bearers, reconciles divergent branches, and finally reconstructs the entire campaign from a clean verifier.

Every claim has a minimal witness set, a permanent negative control, a named subtraction target, required receipts, and an explicit acceptance predicate. The generated [`PROOF_MATRIX.md`](PROOF_MATRIX.md) is the operative map from the architecture to the laboratory. A claim cannot move from `declared` to `accepted` merely because its stage ran. Target-machine observations and independent outcome receipts must satisfy the frozen predicate.

## Files

```text
lab.json
  Authority, topology, model arms, stages, claims, faults, metrics, and physical boundary.

model_fingerprint_contract.json
  Shared identity, capability, disposition, orchestration, degradation,
  thermodynamic, affinity, and reproducibility contract for Fable and Kimi3.

Generated `plan.json`
  Deterministic 66-cell campaign plan produced by `tierhalo3 plan`.

Generated `proof_matrix.json` and committed `PROOF_MATRIX.md`
  Deterministic claim, witness, negative-control, subtraction, receipt, and acceptance ledger.
```

## Commands

```console
python -m tier_runner.halo3_cell validate \
  --lab labs/halo3-cell-zero/lab.json \
  --fingerprint labs/halo3-cell-zero/model_fingerprint_contract.json

python -m tier_runner.halo3_cell plan \
  --lab labs/halo3-cell-zero/lab.json \
  --fingerprint labs/halo3-cell-zero/model_fingerprint_contract.json \
  --out /tmp/halo3-plan.json

python -m tier_runner.halo3_cell verify \
  --lab labs/halo3-cell-zero/lab.json \
  --fingerprint labs/halo3-cell-zero/model_fingerprint_contract.json \
  --plan labs/halo3-cell-zero/plan.json

python -m tier_runner.halo3_cell proof-matrix \
  --lab labs/halo3-cell-zero/lab.json \
  --fingerprint labs/halo3-cell-zero/model_fingerprint_contract.json \
  --out-json /tmp/halo3-proof-matrix.json \
  --out-markdown /tmp/HALO3_PROOF_MATRIX.md

python -m tier_runner.halo3_cell templates \
  --plan labs/halo3-cell-zero/plan.json \
  --out /tmp/halo3-observations.json
```

## Immediate execution order

The first physical transaction begins with the estate census and exact function receipts already required by the Community Home Lab Anchor Crate. Once the actual hosts and accelerator domains are observed, the campaign should freeze the Fable and Kimi3 identity envelopes, generate the fifty-four hidden-grade model cells, bind one sensor and one harmless output to `head-a`, and execute `stage-020-single-node`. HALO3 should enter only after the personal-node floor closes, because its measured contribution requires a matched baseline rather than a demonstration that the 4060 can produce text.

The next equipment additions should be chosen for contract coverage rather than spectacle: one e-ink display, one haptic output, one independently observable sensor, one safe actuator or pointer, NFC or optical exchange, and one microcontroller with an intentionally unfamiliar schema. These objects cover persistent role state, silent attention, physical observation, verified effect, radio-silent transfer, and foreign-system adaptation without creating a hazardous test surface.

## Current boundary

The source, schemas, deterministic plan, proof matrix, and provider-free refusal laws can be qualified in hosted CI. The actual hosts, GPUs, model runtimes, sensors, peripheral, passive encoding, power and network faults, human interactions, and physical outcomes remain unmeasured. The two 3090 lanes are separate logical treatments only until the estate census proves distinct hosts, power paths, and storage custody. No production, field, military, or promotion claim is authorized.
