# Anchor Crate Floor v1

The Anchor Crate floor is a backend-neutral execution ABI for durable AI-assisted work. It compiles one cartridge into a typed DAG, binds each node to an admitted execution backend, emits a content-addressed crate, validates the returned artifact independently, and advances an append-only anchor.

## Current reference DAG

```text
input:readiness_records
        │
        ▼
normalize_records
  deterministic.transform
        │
        ▼
derive_availability
  deterministic.transform
        │
        ▼
generate_decision_packet
  candidate.generate
  CUDA 3090 fixture or RISC-V fixture
        │
        ▼
verify_decision_packet
  verify.accept
  controller-owned acceptance
```

The task remains the same when the candidate node moves from CUDA to RISC-V. The execution treatment changes.

```text
portable task
anchortask1_1b31b15a68d5ef8c0b21588755d3a7c157070fcfa33bff2aa98478a74656cc8e

CUDA plan
anchorplan1_acd60429eeed790f27276053d000af254cc65f24fa7fe5ab24ef35df12afc0cc

RISC-V plan
anchorplan1_a533336e40b3ed32cc78d2cc83ae458ded9a554c5edebe22b4e2d6a50c2806a6
```

The exact IDs are generated from the committed floor, cartridge, and backend registry. CI regenerates them and refuses drift.

## Files

```text
floor.json
  Authority, node semantics, executor ABI, placement law, MENACE seams,
  and community commodity boundaries.

physical_availability_cartridge.json
  Frozen input, task DAG, invariants, budgets, validators, and acceptance.

backend_registry.json
  Host, RTX 3090 CUDA, and RISC-V accelerator execution suppliers.

plan.cuda-fixture.json
plan.riscv-fixture.json
  Exact deterministic lowerings for the two candidate routes.

backend_equivalence.json
  Proof that portable task and semantic node identities remain equal while
  execution and plan identities remain distinct.

conformance.*.json
  Driver ABI conformance reports. Physical qualification remains false.
```

## Run the fixture

```console
python -m tier_runner.anchor_crate validate \
  --floor labs/community-home-lab/anchor-crate/floor.json \
  --cartridge labs/community-home-lab/anchor-crate/physical_availability_cartridge.json \
  --backends labs/community-home-lab/anchor-crate/backend_registry.json

python -m tier_runner.anchor_crate run \
  --floor labs/community-home-lab/anchor-crate/floor.json \
  --cartridge labs/community-home-lab/anchor-crate/physical_availability_cartridge.json \
  --backends labs/community-home-lab/anchor-crate/backend_registry.json \
  --run-root .git/tier-anchor/readiness-cuda \
  --controller-cwd .
```

Override the candidate node without editing the task:

```console
python -m tier_runner.anchor_crate run \
  --floor labs/community-home-lab/anchor-crate/floor.json \
  --cartridge labs/community-home-lab/anchor-crate/physical_availability_cartridge.json \
  --backends labs/community-home-lab/anchor-crate/backend_registry.json \
  --bind generate_decision_packet=backend.riscv-llm-fixture \
  --run-root .git/tier-anchor/readiness-riscv \
  --controller-cwd .
```

## Force controller replacement

Stop after the deterministic availability state is sealed:

```console
python -m tier_runner.anchor_crate run \
  --floor labs/community-home-lab/anchor-crate/floor.json \
  --cartridge labs/community-home-lab/anchor-crate/physical_availability_cartridge.json \
  --backends labs/community-home-lab/anchor-crate/backend_registry.json \
  --run-root .git/tier-anchor/readiness-resume \
  --controller-cwd . \
  --stop-after-node derive_availability
```

Start a fresh controller process with only the sealed anchor and artifact store:

```console
python -m tier_runner.anchor_crate run \
  --floor labs/community-home-lab/anchor-crate/floor.json \
  --cartridge labs/community-home-lab/anchor-crate/physical_availability_cartridge.json \
  --backends labs/community-home-lab/anchor-crate/backend_registry.json \
  --run-root .git/tier-anchor/readiness-resume \
  --controller-cwd . \
  --resume-anchor .git/tier-anchor/readiness-resume/anchors/0002-<sha256>.json
```

Starting again without the anchor is refused. Tampering with the anchor or any retained artifact is refused.

## Physical boundary

The CUDA and RISC-V entries are ABI fixtures. They do not establish token rate, power, thermal behavior, Thunderbolt compatibility, RISC-V silicon capability, military suitability, or production admission. The arriving Dell RTX 3090 becomes a new backend manifest only after its exact GPU UUID, enclosure, cable, head, driver, runtime, model, power limit, telemetry, and recovery behavior are measured.
