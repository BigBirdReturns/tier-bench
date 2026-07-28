# Conditional Memory Lab v1

## Classification

The Conditional Memory Lab is a topology-aware architecture and deployment instrument. The physical estate is now represented as two distinct hosts:

```text
desktop-4060
  RTX 4060
  coordination, packet publication, small resident services, collection,
  report construction, memory-pack custody, and final acceptance

lg-gram-dual3090
  RTX 3090 eGPU seat A
  RTX 3090 eGPU seat B
  independent training, evaluation, profiling, and opposite-seat replay
```

The module does not claim that the three GPUs form one accelerator or that the two RTX 3090 cards expose pooled 48 GB VRAM. Model tensors, activations, KV state, and optimizer collectives do not cross the home network. Work crosses as immutable packets. Results return as checkpoints, receipts, golden outputs, profiles, and cross-verification records.

## Teaming model

Version 1 uses artifact-level teaming because it fits the actual hardware and preserves failure isolation.

1. The desktop compiles the frozen experiment plan and publishes one `run_trial` packet per arm and seed.
2. The LG Gram launches one child worker per RTX 3090 UUID. The seats claim independent packets and run concurrently.
3. When a seat finishes a trial, it publishes the receipt and checkpoint atomically.
4. The opposite RTX 3090 receives a dependent `verify_checkpoint` packet. It reconstructs the exact validation stream, loads the producer checkpoint, and independently checks state identity, validation loss, and top-token order.
5. The desktop imports both the producer receipt and verifier record. A matrix with incomplete opposite-seat replay cannot clear collection.

This is throughput teaming, adversarial teaming, and evidence teaming. Synchronous DDP or tensor parallelism over the two Thunderbolt eGPUs remains a separate future experiment because host-mediated communication may erase its theoretical benefit.

## Exchange authority

The exchange is a shared filesystem reachable from both computers, normally an SMB share over the local network or Tailscale. The same bytes may appear under different local paths:

```text
desktop: D:\TierExchange
LG Gram: Z:\TierExchange
```

Both hosts set `TIER_EXCHANGE_ROOT` to their local path. Packet identities bind only relative flight paths and SHA-256 values.

A flight contains:

```text
flights/<flight-id>/
  manifest.json
  inputs/
    lab.json
    cluster.json
    plan.json
  packets/
  claims/
  heartbeats/
  submissions/
  collections/
  coordinator/
```

Publication and submission use temporary files followed by atomic replacement. Claims use exclusive creation. Heartbeats make abandoned work visible, and stale claims may be reclaimed explicitly. Completed attempts are append-only.

## Hardware identity

The coordinator and worker resolve only hardware physically attached to their own hosts.

Desktop:

```powershell
$env:TIER_GPU_4060_UUID = "GPU-..."
```

LG Gram:

```powershell
$env:TIER_GPU_3090_A_UUID = "GPU-..."
$env:TIER_GPU_3090_B_UUID = "GPU-..."
```

Optional hostname custody can be enabled through `TIER_DESKTOP_HOSTNAME` and `TIER_GRAM_HOSTNAME`. CUDA workers are masked by UUID before PyTorch import. Each child therefore sees its assigned card as `cuda:0`, regardless of Windows ordinal changes.

## Experiment matrix

The supplied canary compares:

| Arm | Question |
|---|---|
| `dense` | What does the matched active core achieve without conditional memory? |
| `ple-no-table` | Do the PLE projections and gates create an apparent gain by themselves? |
| `ple-vram` | Does token-indexed per-layer memory improve quality when resident on the GPU? |
| `ple-pinned` | Does the same architecture retain utility when selected rows cross from pinned host memory? |
| `fat-embedding` | Is the gain merely additional token capacity injected once at the input? |
| `engram-lite` | Does hashed bigram memory capture stable multi-token structure? |
| `big-dense` | Is ordinary dense capacity the better resource allocation? |

Paired crossover rotates every arm across both RTX 3090 seats over the seed set. This exposes enclosure, thermal, Thunderbolt, and card-specific effects without requiring the GPUs to cooperate on one forward pass.

## Memory-pack lifecycle

A completed table-bearing trial can export its lookup table as fp32, fp16, bf16, group-int8, or packed group-int4. Placement profiling and full-model quality replay remain separate receipts.

The coordinator creates `receipt.local.json` beside each collected checkpoint. This local custody receipt preserves the producer receipt identity while rebasing the checkpoint path to the desktop, so later pack export does not depend on a path that exists only on the LG Gram.

## Operator sequence

Install the same branch and CUDA-compatible PyTorch build on both computers. Create or mount the shared exchange and set `TIER_EXCHANGE_ROOT` independently on each host.

Start the persistent worker on the LG Gram:

```powershell
.\scripts\run-conditional-memory-worker.ps1 `
  -ExchangeRoot Z:\TierExchange `
  -WorkRoot C:\TierWorker\ConditionalMemory
```

The worker can be installed as an at-startup scheduled task:

```powershell
.\scripts\run-conditional-memory-worker.ps1 `
  -ExchangeRoot Z:\TierExchange `
  -WorkRoot C:\TierWorker\ConditionalMemory `
  -InstallScheduledTask
```

Publish and collect from the desktop:

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile smoke `
  -ExchangeRoot D:\TierExchange `
  -CoordinatorState D:\TierRuns\ConditionalMemory\Coordinator
```

The desktop command publishes, polls, and collects. `-PublishOnly` releases the work and returns immediately. `-CollectOnly -FlightId <id>` resumes collection for an existing flight.

After the distributed smoke closes, run `canary`. The `full` profile remains held until the canary proves stable GPU identity, complete opposite-seat verification, credible performance data, and no topology or source conflicts.

## Qualification boundary

The control tests establish deterministic packet publication, parallel worker processes, checkpoint transfer, opposite-seat replay, collection, and local custody rebasing under a CPU simulation. CI compiles the cluster surfaces, publishes a fourteen-trial and twenty-eight-packet distributed smoke flight, and parses both Windows launchers.

Those tests do not establish physical RTX 3090 throughput, simultaneous dual-eGPU stability, Windows pinned-memory behavior, Thunderbolt contention, or an architecture-quality gain. Those claims require receipts from the LG Gram and desktop estate.

## Failure default

Unknown UUIDs, wrong hostnames when hostname custody is enabled, source drift, packet tampering, missing dependencies, stale unreclaimed claims, absent checkpoints, failed opposite-seat replay, incomplete collection, and report conflicts remain visible and hold the experiment. Production routing authority remains outside the module.
