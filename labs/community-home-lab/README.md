# Community Home Lab v0.2: Anchor Crate Execution Floor

The Community Home Lab is the commodity supply and qualification surface for the AXM Estate. It consumes model runtimes, queues, databases, policy engines, observability stacks, remote-operation tools, and hardware as replaceable suppliers. Human decision, task truth, authority, acceptance, and durable Estate custody remain outside every supplier.

Version 0.2 adds the **Anchor Crate execution floor**. The floor turns an accepted task contract into a backend-neutral DAG whose nodes can be lowered onto the desktop CPU, the resident RTX 4060, the detachable RTX 3090, a native-Linux host, a remote service, or a future RISC-V or custom accelerator without changing the task’s semantic identity.

```text
Tier Desk / Task Floor
  owns task, authority, approval, acceptance, and project handoff
          ↓
Anchor Cartridge
  frozen input, DAG, invariants, budgets, validators, seams
          ↓
Deterministic Anchor Controller
  hashes, dependency state, placement, crates, effects, validation, recovery
          ↓
Replaceable execution suppliers
  CPU | 4060 | 3090 | remote open weights | RISC-V | custom ASIC
          ↓
Typed receipts and content-addressed artifacts
          ↓
Accepted work cache, TierBench, Venkman, project writeback
```

## Estate mapping

| Estate object | Initial laboratory role |
|---|---|
| Desktop CPU and RAM | Controller, artifact custody, deterministic transforms, scheduling, acceptance |
| Internal RTX 4060 | Resident utility cartridge for extraction, embeddings, vision, and small models |
| Core X plus RTX 3090 | Detachable 24 GiB burst cartridge for heavy candidate nodes |
| NUC6i7KYK | Native-Ubuntu head, network head, overnight worker, and host-substitution control |
| LG Gram and Galaxy Book | Detachable operator heads and Thunderbolt-host qualification arms |
| NVMe | Hot cartridges, runtime images, current artifacts, indexes, and conversion scratch |
| HDD estate | Model lake, inactive cartridges, historical evidence, checkpoints, and receipts |

No memory is silently pooled. A DAG may place independent nodes on different resources, and a model may deliberately use bounded CPU or storage tiers, but every placement remains visible in the plan and receipt.

## Durable unit

The durable unit is not a model session. It is:

```text
portable task identity
+ sealed cartridge
+ content-addressed anchor lineage
+ bounded crates
+ exact backend and lowering identities
+ controller-owned validators
+ accepted artifacts and receipts
```

A runtime may disappear after one node. A head may be replaced after one anchor. A backend may be upgraded, power-limited, or removed. Continuation is reconstructed from the anchor and accepted receipts rather than conversational memory.

## Current reference transaction

The first cartridge asks whether an asset shown administratively as on hand is physically serviceable. Deterministic nodes normalize source records and derive physical availability. A candidate-generation node produces a concise decision packet. The final controller node verifies the claim, blockers, evidence references, and required human review.

The committed comparison lowers the same candidate node onto two ABI fixtures:

- an RTX 3090 CUDA route;
- a future RISC-V LLM accelerator route.

Both retain the same portable task and node semantic identities. Their plans, execution identities, toolchains, ISA declarations, and wording differ. Neither fixture is physically qualified.

See [`anchor-crate/README.md`](anchor-crate/README.md) for commands and evidence.
