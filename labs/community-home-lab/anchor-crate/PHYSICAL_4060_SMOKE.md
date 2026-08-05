# Physical RTX 4060 Qwen Smoke

This transaction replaces the CUDA-shaped fixture with one exact physical backend and runs the existing physical-availability cartridge through it. The task, source records, semantic DAG, controller validators, acceptance law, and portable task identity remain unchanged.

## Preconditions

The smoke does not invent the host estate. It requires a `PASS` Home Lab Capability Gradient receipt for `capture-estate-snapshot`, the exact receipt-covered `estate-observation.json`, and the exact receipt-covered `inputs/control-host.json`. The census must contain all three declared hosts, all six declared accelerator domains, complete runtime enabled-or-disabled state, and one exact RTX 4060 identity on `control-host`.

The control host must provide enabled paths for Python, Ollama, and `nvidia-smi`. The exact model is `qwen3.5:9b-q4_K_M`. The launcher starts a dedicated loopback Ollama server with `CUDA_VISIBLE_DEVICES` set to the censused GPU UUID. It refuses an occupied endpoint rather than attaching to an unidentified server.

## Transaction

```powershell
.\scripts\run-anchor-crate-4060-smoke.ps1 `
  -TierBenchRoot D:\Projects\tier-bench `
  -GradientRoot D:\Projects\axm-tools\home-lab-gradient `
  -EstateReceipt C:\Users\BAM-Desktop\AppData\Local\AXM\home-lab-gradient\runs\<census>\experiment.receipt.json `
  -EstateObservation C:\Users\BAM-Desktop\AppData\Local\AXM\home-lab-gradient\runs\<census>\estate-observation.json `
  -ControlHostObservation C:\Users\BAM-Desktop\AppData\Local\AXM\home-lab-gradient\runs\<census>\inputs\control-host.json `
  -OutRoot D:\Evidence\anchor-crate-4060-smoke
```

`ANCHOR4060.cmd` forwards the same arguments.

The launcher performs one continuous evidence transaction:

1. Verify and copy the complete three-host census run into the smoke package.
2. Start a dedicated loopback Ollama server bound to the exact RTX 4060 UUID.
3. Scaffold and qualify the existing bounded Qwen function twice through PR #52's function contract.
4. Bind the exact Ollama version, model digest, model size, quantization, VRAM residency, NVIDIA UUID, driver, PCI identity, memory, and power envelope.
5. Build `backend.cuda4060-qwen35-physical` and its content-addressed physical binding.
6. Run executor conformance against `describe`, `probe`, `execute`, `collect`, and `cancel`.
7. Bind only `generate_decision_packet` to the physical backend and run the unchanged reference cartridge.
8. Require controller acceptance of `not_physically_available` with the exact blockers, evidence references, and human-review requirement.
9. Seal the backend build receipt, controller run, physical executor event log, smoke receipt, and complete checksum ledger.
10. Terminate the dedicated Ollama process tree.

## Identity and authority

The generated backend row is machine specific. Its execution identity binds absolute interpreter, executor, and binding paths; the exact host and GPU; the NVIDIA driver; the Ollama version; the model digest; the lowering; the memory and power envelope; and the source receipts. Moving or changing any of those surfaces creates a new backend treatment.

The model returns a candidate decision packet. It cannot hash the anchor, certify its own binding, run the controller validators, accept its result, or promote the backend. The deterministic controller derives the artifacts and receipts, executes the validators, and advances the durable anchor.

## Evidence boundary

A successful smoke establishes that the exact measured 4060 Qwen route can execute one immutable Anchor Crate node and preserve the controller-accepted product. It does not establish the three-host scheduler, 3090 behavior, head substitution, field suitability, military accreditation, or production admission. Those remain later treatments against the same portable task and executor ABI.
