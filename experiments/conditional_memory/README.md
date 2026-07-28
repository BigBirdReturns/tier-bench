# Conditional Memory Lab operator packet

The estate has two hosts. The desktop carries the RTX 4060 and owns coordination, collection, verification policy, and artifact custody. The LG Gram carries both RTX 3090 eGPUs and owns the two independent execution seats.

## 1. Install the branch on both hosts

```powershell
git fetch origin agent/conditional-memory-lab-v1
git switch agent/conditional-memory-lab-v1
python -m pip install -e .
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

Use the same commit and Python environment on both machines. Flight publication binds the source hashes and workers reject a different checkout.

## 2. Create the shared exchange

Use a reliable local SMB share. Tailscale may carry the SMB path when the computers are not on the same LAN. The hosts may use different mount paths.

Desktop:

```powershell
$env:TIER_EXCHANGE_ROOT = "D:\TierExchange"
```

LG Gram:

```powershell
$env:TIER_EXCHANGE_ROOT = "Z:\TierExchange"
```

The shared path is transport and handoff. Model execution uses local scratch on the LG Gram.

## 3. Bind exact GPU identities

Desktop:

```powershell
nvidia-smi --query-gpu=index,uuid,name,memory.total --format=csv,noheader
$env:TIER_GPU_4060_UUID = "GPU-..."
```

LG Gram:

```powershell
nvidia-smi --query-gpu=index,uuid,name,memory.total --format=csv,noheader
$env:TIER_GPU_3090_A_UUID = "GPU-..."
$env:TIER_GPU_3090_B_UUID = "GPU-..."
```

Do not substitute ordinal values. Each worker child is masked by UUID before PyTorch import.

## 4. Start the LG Gram worker

One execution launches two child workers, one per eGPU:

```powershell
.\scripts\run-conditional-memory-worker.ps1 `
  -ExchangeRoot Z:\TierExchange `
  -WorkRoot C:\TierWorker\ConditionalMemory
```

For persistent operation:

```powershell
.\scripts\run-conditional-memory-worker.ps1 `
  -ExchangeRoot Z:\TierExchange `
  -WorkRoot C:\TierWorker\ConditionalMemory `
  -InstallScheduledTask
```

The worker watches for flights, claims work atomically, records heartbeats, runs both seats concurrently, and publishes completed artifacts.

## 5. Publish from the desktop

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile smoke `
  -ExchangeRoot D:\TierExchange `
  -CoordinatorState D:\TierRuns\ConditionalMemory\Coordinator
```

The smoke contains fourteen trial packets and fourteen dependent checkpoint-verification packets. The producer and verifier are always different RTX 3090 seats.

To release work without keeping the desktop terminal open:

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile smoke `
  -ExchangeRoot D:\TierExchange `
  -PublishOnly
```

Later resume collection with the printed flight ID:

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile smoke `
  -ExchangeRoot D:\TierExchange `
  -FlightId <flight-id> `
  -CollectOnly
```

## 6. Inspect the exchange

```powershell
python -m tier_runner.conditional_memory_exchange_cli status `
  --flight-root D:\TierExchange\flights\<flight-id>
```

The flight does not close while any packet is pending, claimed, failed, or missing. Stale claims require explicit `-ReclaimStale` on the worker.

## 7. Run the evidence-bearing canary

After the physical smoke closes:

```powershell
.\scripts\run-conditional-memory-lab.ps1 `
  -Profile canary `
  -ExchangeRoot D:\TierExchange `
  -CoordinatorState D:\TierRuns\ConditionalMemory\Coordinator
```

The report remains experimental. It can name a promotable arm, but it records `promotion_authorized: false`.

## 8. Export packs on the desktop

Collection produces the immutable producer `receipt.json`, the copied `checkpoint.pt`, and a rebased `receipt.local.json`. Use the local receipt for pack export:

```powershell
python -m tier_runner.conditional_memory_cli pack-export `
  --receipt <collected-trial>\run_trial\receipt.local.json `
  --out-dir D:\TierRuns\ConditionalMemory\Packs\candidate-int4 `
  --dtype int4 `
  --group-size 128
```

Then qualify quality and placement through the existing `pack-evaluate` and `pack-profile` commands.

## Operational law

The network passes work descriptions, checkpoints, receipts, and logs. It does not pass per-token activations or pretend to pool the 4060 with the two 3090s. The two eGPUs team by parallel production and reciprocal verification. The desktop remains the authority that accepts or rejects the returned work.
