# DAG, Cartridge Rotation, and Storage Tiers

The Anchor Crate controller treats the home estate as a factory with independent machines, buffers, carts, and work cells. It does not force every operation through one resident model or one serial process.

## DAG scheduling object

Each node declares:

- dependencies;
- semantic class;
- operation and schemas;
- capability requirements;
- effect class;
- memory, storage, network, and power envelope;
- validators and stop condition;
- optional backend preferences.

The controller first enforces hard admission. It then places ready nodes onto available backends. Independent nodes may run concurrently when their resource lanes do not conflict. A slower node may run unattended when its task contract permits wall-clock expansion.

## Storage hierarchy

```text
HDD model and evidence lake
  inactive model cartridges, historical evidence, checkpoints, raw media
            ↓ hydrate
NVMe hot floor
  active models, indexes, runtime images, conversion scratch, current artifacts
            ↓ bounded staging
Host RAM
  controller state, databases, queues, page cache, staging buffers
            ↓ load or selected transfer
Accelerator memory
  current model, active KV state, kernels, and working tensors
```

The storage tiers trade wall clock for cost. They do not pretend SSD is ordinary accelerator memory. Steady dense decoding should keep its active weights resident. Sparse or staged workloads may deliberately page bounded components when the measured wall clock remains useful.

## Cartridge rotation

A model cartridge is an immutable model, runtime, tokenizer, quantization, context policy, and tool surface. A task cartridge is an immutable input, DAG, schemas, validators, budgets, and acceptance contract. They are independently swappable.

The scheduler can therefore express operations such as:

```text
hydrate model B while model A finishes
unload A after its accepted receipt
load B for the next ready candidate nodes
leave deterministic transforms on CPU
route small vision or extraction work to the 4060
send one heavy candidate node to the 3090
retain all resulting artifacts in the same anchor lineage
```

The expensive device becomes a work cell rather than the computer that owns the mission.

## Accepted-action reuse

A pure node is reusable only when its complete action key matches:

```text
portable task identity
node semantic identity
input artifact hashes
validator identities
floor contract
operation and schema
```

Backend execution identity remains in the receipt. An exact accepted artifact may be reused when the semantic action key permits it. A stochastic candidate is not reused merely because its prompt looks similar.
