# Conditional Memory Lab operator packet

This directory contains the first matched architecture and placement canary for learned conditional memory in Tier Bench. The lab is intentionally small enough to repeat, adversarially inspect, and scale only after the measurement rails prove trustworthy.

## 1. Bind the physical seats

Discover the cards:

```powershell
nvidia-smi --query-gpu=index,uuid,name,memory.total --format=csv,noheader
```

Bind exact UUIDs in the operator shell:

```powershell
$env:TIER_GPU_3090_A_UUID = "GPU-..."
$env:TIER_GPU_3090_B_UUID = "GPU-..."
$env:TIER_GPU_4060_UUID   = "GPU-..."
```

The worker process masks by UUID before PyTorch import. Do not substitute ordinal values such as `0` or `1`.

## 2. Validate and freeze the smoke plan

```powershell
python -m pip install -e .

python -m tier_runner.conditional_memory_cli validate `
  --lab experiments\conditional_memory\lab.example.json `
  --profile smoke

python -m tier_runner.conditional_memory_cli plan `
  --lab experiments\conditional_memory\lab.example.json `
  --profile smoke `
  --out D:\TierRuns\ConditionalMemory\smoke-plan.json

python -m tier_runner.conditional_memory_cli verify-plan `
  --lab experiments\conditional_memory\lab.example.json `
  --plan D:\TierRuns\ConditionalMemory\smoke-plan.json
```

The smoke plan contains fourteen trials: seven arms, two seeds, and one instance of every arm on each RTX 3090 seat. Its two seeds cannot satisfy the default three-seed promotion gate.

## 3. Run both seats

The launcher creates a unique flight directory, starts one worker per 3090, samples all NVIDIA GPUs, waits for both workers, and builds the status and comparison reports.

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile smoke `
  -StateDir D:\TierRuns\ConditionalMemory
```

For a control-plane test without CUDA:

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile smoke `
  -StateDir D:\TierRuns\ConditionalMemory-CPU `
  -ForceCpu
```

A CPU pass does not qualify either GPU seat.

## 4. Read the flight

Each flight directory contains:

```text
plan.json
hardware-monitor-<invocation>.jsonl
hardware-monitor-<invocation>.jsonl.summary.json
<invocation>-seat-gpu.3090-a.stdout.log
<invocation>-seat-gpu.3090-a.stderr.log
<invocation>-seat-gpu.3090-b.stdout.log
<invocation>-seat-gpu.3090-b.stderr.log
status-<invocation>.json
report-<invocation>.json
monitor-<invocation>.stop
```

Trial receipts and checkpoints are written below the flight's `state` directory. `status.json` must report no missing, failed, invalid, or duplicate trials. `report.json` contains paired quality, p95 latency, peak CUDA allocation, topology ledgers, the Pareto frontier, and the gate decision for each arm.

## 5. Run the evidence-bearing canary

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile canary `
  -StateDir D:\TierRuns\ConditionalMemory
```

Do not treat a lower validation loss as sufficient. Inspect whether the candidate clears the latency and peak-memory gates on both seats, whether `ple-vram` beats `ple-no-table` and `fat-embedding`, and whether `big-dense` remains the better allocation.

## 6. Export and qualify a learned memory pack

The canary and full profiles preserve checkpoints. Choose a completed `ple-vram`, `ple-pinned`, `fat-embedding`, or `engram-lite` receipt.

```powershell
python -m tier_runner.conditional_memory_cli pack-export `
  --receipt <receipt.json> `
  --out-dir D:\TierRuns\ConditionalMemory\packs\candidate-int4 `
  --dtype int4 `
  --group-size 128

python -m tier_runner.conditional_memory_cli pack-validate `
  --manifest D:\TierRuns\ConditionalMemory\packs\candidate-int4\manifest.json
```

Measure the compressed access path:

```powershell
python -m tier_runner.conditional_memory_cli pack-profile `
  --lab experiments\conditional_memory\lab.example.json `
  --plan <plan.json> `
  --seat gpu.3090-a `
  --manifest D:\TierRuns\ConditionalMemory\packs\candidate-int4\manifest.json `
  --placement pinned_ram `
  --batch-rows 128 `
  --iterations 500 `
  --warmup 50 `
  --pattern random `
  --out D:\TierRuns\ConditionalMemory\packs\candidate-int4\profile-pinned.json
```

Replay the pack through the full model and frozen validation stream:

```powershell
python -m tier_runner.conditional_memory_cli pack-evaluate `
  --lab experiments\conditional_memory\lab.example.json `
  --plan <plan.json> `
  --receipt <receipt.json> `
  --manifest D:\TierRuns\ConditionalMemory\packs\candidate-int4\manifest.json `
  --seat gpu.3090-a `
  --out D:\TierRuns\ConditionalMemory\packs\candidate-int4\evaluation.json
```

The placement profile and full-model evaluation are separate authorities. Preserve both.

## 7. Iterate without destroying evidence

Change the lab document or add a named profile. Recompile a new plan. Any change creates a new lab or plan hash and therefore a separate state branch. Do not edit completed receipts, reuse a populated pack directory, or overwrite a profile receipt. Failed attempts remain part of the record.

The first extension targets are a Tier Desk Work IR classification corpus, a frozen repository-symbol corpus, and an AXM world-language corpus. Each requires its own external acceptance authority. The synthetic canary remains the systems and architecture reference, not the final product benchmark.
