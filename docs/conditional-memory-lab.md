# Conditional Memory Lab v1

## Classification

The Conditional Memory Lab is a topology-aware model-architecture and deployment instrument for Tier Bench. It compares a matched dense control against learned lookup-memory variants, measures where their bytes reside and move, exports learned tables as independently identified memory packs, and refuses production promotion until the complete paired evidence matrix closes.

The lab treats conditional memory as a distinct capacity class. A dense core performs context-dependent transformation. A conditional table stores stable learned associations whose rows are selected by token or n-gram identity. The Estate remains the authority for mutable facts, decisions, permissions, receipts, and current project state.

## Authority

The following boundaries are invariant:

- Git bytes and the canonical lab document define the experiment.
- The deterministic plan binds every arm, seed, seat, stage, and promotion gate.
- GPU seats are resolved by NVIDIA UUID before PyTorch is imported. Ordinal position is not an identity.
- Every trial receives the same frozen data law for its seed. Train and validation sequences differ, but the synthetic association map does not drift between them.
- Trial state is append-only. A failed attempt is preserved and a later attempt receives a new directory.
- Candidate quality is compared to the dense control by the same seed.
- Performance is measured on the target runtime, not inferred from parameter count.
- A report may identify a promotable arm, but it always records `promotion_authorized: false`. Routing authority remains outside this module.

## What lands

The module provides:

- strict lab, plan, trial-receipt, report, memory-pack, placement-profile, and pack-evaluation contracts;
- deterministic paired crossover of every architecture across both RTX 3090 seats;
- dense, larger-dense, bottom-only fat embedding, PLE plumbing without a table, full PLE, and hashed n-gram memory arms;
- sparse-gradient lookup tables with a separate SparseAdam optimizer;
- VRAM, host RAM, pinned RAM, and raw memory-map table placement paths;
- protection against staging host-resident tables through VRAM during model initialization;
- a frozen synthetic association and bigram canary with shared train and validation laws;
- uint16 token-corpus ingestion with source hashes;
- stored-capacity, active-core, output-head, row-width, row-transfer, placement, and observed-access ledgers;
- CUDA peak allocation, paired step latency, validation loss, throughput, state hashes, and golden-logit receipts;
- post-training fp32, fp16, bf16, group-int8, and packed group-int4 memory packs;
- deterministic pack identities that are independent of the output directory;
- sampled quantization-error measurements;
- row-access placement profiles for random, hot-set, and sequential traces;
- full-model pack replay against the exact frozen validation stream;
- hardware monitoring and a Windows launcher for concurrent two-seat execution;
- zero-model control tests and an optional physical PyTorch smoke.

## Experiment matrix

The supplied canary contains seven arms.

| Arm | Question |
|---|---|
| `dense` | What does the matched active core achieve without conditional memory? |
| `ple-no-table` | Do projections, gates, and layer injections create an apparent gain without learned lookup capacity? |
| `ple-vram` | Does token-indexed per-layer memory improve the frozen task when resident with the core? |
| `ple-pinned` | Does the same table retain its quality when selected rows cross from pinned host memory? |
| `fat-embedding` | Is the gain caused by additional token capacity, or specifically by per-layer injection? |
| `engram-lite` | Does deterministic hashed n-gram memory capture the stable bigram portion of the task? |
| `big-dense` | Is ordinary active computation the better use of the additional resource budget? |

The smoke profile proves execution and receipt integrity. It contains only two seeds and therefore cannot pass the default three-seed promotion gate. The canary profile is the first evidence-bearing run. The full profile widens the data, seed, and training envelopes only after the canary is clean.

## Physical topology

The intended bench is:

```text
RTX 3090 A   matched experimental seat
RTX 3090 B   matched experimental seat
RTX 4060     resident service and presentation lane
CPU and RAM  control plane, host lookup tier, receipt custody
NVMe         immutable checkpoints, memory packs, cold mapped tier
```

The two RTX 3090 cards are independent seats. The lab does not claim transparent VRAM pooling. Each seed-arm trial runs on one seat, while the crossover rotates every arm across both seats over the seed set. This design exposes card, enclosure, thermal, and link effects without making high-bandwidth peer transfer a prerequisite.

Set these environment variables to the exact values reported by `nvidia-smi`:

```powershell
$env:TIER_GPU_3090_A_UUID = "GPU-..."
$env:TIER_GPU_3090_B_UUID = "GPU-..."
$env:TIER_GPU_4060_UUID   = "GPU-..."
```

A CUDA worker receives its UUID through `CUDA_VISIBLE_DEVICES` before importing PyTorch. The selected card then appears to the worker as `cuda:0`. This is intentional and prevents ordinal drift.

## Conditional-table execution

A host-resident table is never moved wholesale to the GPU. The active model is moved while the table parameter is temporarily detached from module traversal. The table remains in host or pinned memory, row selection occurs in that tier, and only selected rows cross to the target device.

Lookup gradients are sparse. The active model uses AdamW, with normalization and embedding parameters excluded from weight decay. A trainable memory table uses SparseAdam. This prevents the training harness from allocating or updating a dense gradient for every unselected row and makes table scaling materially representative of conditional memory.

Schema version 1 reserves `prefetch_layers` and `cache_bytes`, but rejects nonzero values because those mechanisms are not yet implemented. The receipt cannot claim prefetch or caching through a configuration field that the runtime ignored.

## Frozen association canary

The synthetic canary combines three next-token mechanisms:

```text
60 percent  token-specific frozen association
25 percent  deterministic bigram and position law
15 percent  random continuation
```

Each trial seed creates one association map. Train and validation draw different sequences from that same map. This is the minimum valid shape for testing whether a token-indexed table learned stable associations. Generating a new validation map would measure domain shift and would erase the capability under test.

The dataset fingerprint includes the association-map hash, full train tensor hash, full validation tensor hash, and combined identity. Every arm at a given seed must report the same combined hash. Any mismatch holds the entire matrix.

## Trial and state layout

A run writes beneath the selected state directory:

```text
<state>/
  <lab-id>/
    <profile>/
      <plan-prefix>/
        <trial-slug>/
          attempt-001/
            started.json
            checkpoint.pt
            receipt.json
```

`started.json` proves that the attempt began under a specific plan, seat, source tree, and timestamp. `receipt.json` records either a completed result or the complete failure object and traceback. Existing receipt paths cannot be overwritten.

A completed receipt binds:

```text
lab and plan hashes
trial, arm, seed, pair, and seat
resolved GPU or CPU identity
module source hashes
runtime and CUDA identity
data and association-map fingerprints
initial and final model-state hashes
checkpoint path and hash
topology and access ledger
optimizer split and gradient policy
loss trace and validation result
golden logits
latency, throughput, peak CUDA memory, and wall time
```

## Promotion logic

For each candidate and seed, the report pairs the candidate receipt with the dense-control receipt from that seed. Default gates require:

- the declared minimum number of completed paired seeds;
- mean relative validation-loss improvement at or above the configured threshold;
- mean p95 step-time regression at or below the configured threshold;
- mean peak CUDA-memory regression at or below the configured threshold;
- coverage of both physical seats;
- preserved final-state and checkpoint identities;
- one consistent source tree and one dataset fingerprint per seed;
- no missing, failed, invalid, or duplicate planned receipts.

The report uses `control`, `hold`, or `promote` as an experimental decision. It does not authorize a production route. A separate Tier Bench authority must review the receipts, task relevance, and any downstream acceptance suite.

## Memory packs

A completed table-bearing trial can export its learned lookup table independently from the dense checkpoint. The pack contains:

```text
manifest.json
codes.bin
scales.bin, when quantized
```

The manifest binds the source receipt, checkpoint, architecture, table key, dimensions, source bytes, quantization layout, per-file hashes, compression ratio, and sampled reconstruction error. It records two identities:

- `pack_sha256`, a deterministic content identity independent of output location and creation time;
- `manifest_sha256`, the canonical hash of the complete provenance-bearing manifest.

Group-int4 uses signed values from -8 through 7 packed two per byte, with one fp16 scale per row group. Group-int8 uses signed values from -127 through 127 with the same scale shape. Float packs preserve fp32, fp16, or bf16 rows without integer codes.

Pack qualification is deliberately split into two receipts. `pack-profile` measures compressed row access and transfer behavior under an exact key trace. `pack-evaluate` dequantizes the pack into the source checkpoint's existing table allocation in bounded chunks and reruns the complete frozen validation stream. This prevents a fast but inaccurate pack, or an accurate but operationally unusable placement, from passing through one blended number.

## First physical pass

From the repository root:

```powershell
python -m pip install -e .
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
python -m tier_runner.conditional_memory_cli probe `
  --out D:\TierRuns\ConditionalMemory\hardware-probe.json

.\scripts\run-conditional-memory-lab.ps1 `
  -Profile smoke `
  -StateDir D:\TierRuns\ConditionalMemory
```

Review the smoke report and every failed attempt. A clean smoke proves only that the matrix executes on the intended hardware and that the receipts close. Then run:

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile canary `
  -StateDir D:\TierRuns\ConditionalMemory
```

Do not begin the full profile until the canary has stable data identities, balanced seats, credible timing, and no source or hardware conflicts.

## Pack qualification sequence

Select a completed table-bearing receipt from a checkpoint-preserving profile, then run:

```powershell
python -m tier_runner.conditional_memory_cli pack-export `
  --receipt <receipt.json> `
  --out-dir D:\TierRuns\ConditionalMemory\packs\ple-int4 `
  --dtype int4 `
  --group-size 128

python -m tier_runner.conditional_memory_cli pack-validate `
  --manifest D:\TierRuns\ConditionalMemory\packs\ple-int4\manifest.json

python -m tier_runner.conditional_memory_cli pack-profile `
  --lab experiments\conditional_memory\lab.example.json `
  --plan <plan.json> `
  --seat gpu.3090-a `
  --manifest D:\TierRuns\ConditionalMemory\packs\ple-int4\manifest.json `
  --placement pinned_ram `
  --pattern random `
  --out D:\TierRuns\ConditionalMemory\packs\ple-int4\profile-pinned-random.json

python -m tier_runner.conditional_memory_cli pack-evaluate `
  --lab experiments\conditional_memory\lab.example.json `
  --plan <plan.json> `
  --receipt <receipt.json> `
  --manifest D:\TierRuns\ConditionalMemory\packs\ple-int4\manifest.json `
  --seat gpu.3090-a `
  --out D:\TierRuns\ConditionalMemory\packs\ple-int4\evaluation.json
```

Repeat the placement profile for VRAM, host RAM, pinned RAM, and memory mapping, then repeat with sequential and hot-set traces. The pack is useful only when task loss and the real byte path both remain inside the intended envelope.

## Qualification boundary

The repository tests prove deterministic planning, strict schema handling, receipt and report hashing, crossover balance, fail-closed drift handling, NVIDIA CSV parsing, sparse-table training on CPU when PyTorch is available, int4 pack round-tripping, placement profiling, and full-model packed-table replay.

CI does not establish RTX 3090 performance, Thunderbolt behavior, Windows pinned-memory behavior, or a conditional-memory quality gain. Those claims require physical receipts from the target bench. The synthetic canary establishes an architecture and systems result for its exact data law. It does not establish general reasoning, coding, or agent capability.

## Failure default

Unknown GPU identities, absent UUIDs, source drift, data drift, duplicate attempts, missing trials, failed trials, malformed receipts, checkpoint mismatch, pack mismatch, unsupported table dtypes, nonzero unimplemented cache settings, and incomplete promotion gates remain visible and hold the experiment.
