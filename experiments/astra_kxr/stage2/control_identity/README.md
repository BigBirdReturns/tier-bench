# Astra Stage 2 executable-control identity binding

This directory contains the private-input template for binding the three control
subjects required by the released Sol Stage 2 law. The committed template is not
an executable identity. Every `C:/REPLACE/...` value must resolve to retained
local evidence, and the generated inventory must be reviewed before binding.

The binding sequence on the Windows calibration host is:

```powershell
Set-Location D:\Projects\Measurement\Tier-Bench

git fetch origin `
  joint/astra-stage2-control-identities-20260903

git switch --detach `
  origin/joint/astra-stage2-control-identities-20260903

powershell -ExecutionPolicy Bypass -File `
  scripts\astra_stage2_bind_controls.ps1 `
  -Command template `
  -Out S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\binding.private.template.json

powershell -ExecutionPolicy Bypass -File `
  scripts\astra_stage2_bind_controls.ps1 `
  -Command probe-hardware `
  -Out S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\hardware `
  -DeviceIndices 0
```

The probe always executes the selected-device CSV query. On Linux it also
executes exact `nvidia-smi topo -m`, requires nonempty successful stdout, and
stores those exact bytes plus their digest inside private
`nvidia-topology.json`. On Windows, `topo -m` is never invoked: exactly one
selected device produces the explicit
`NOT_APPLICABLE_SINGLE_SELECTED_DEVICE` limitation record, while two or more
selected devices refuse until a separately implemented and independently
qualified Windows topology source exists. The limitation record never claims
inter-device topology or implicit pooling.

Populate the three source roots, immutable checkpoint snapshot roots, dedicated
runtime roots, adapter and quantization declarations, selected hardware evidence,
and truthful low/high effort mappings. Then inventory, bind, and verify:

```powershell
powershell -ExecutionPolicy Bypass -File `
  scripts\astra_stage2_bind_controls.ps1 `
  -Command inventory `
  -Config S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\binding.private.template.json `
  -Out S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\binding.private.inventory.json

powershell -ExecutionPolicy Bypass -File `
  scripts\astra_stage2_bind_controls.ps1 `
  -Command bind `
  -RepoRoot D:\Projects\Measurement\Tier-Bench `
  -Config S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\binding.private.inventory.json `
  -Out S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\bound

powershell -ExecutionPolicy Bypass -File `
  scripts\astra_stage2_bind_controls.ps1 `
  -Command verify `
  -RepoRoot D:\Projects\Measurement\Tier-Bench `
  -Config S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\binding.private.inventory.json `
  -Out S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities\bound
```

`bound/private/` contains path-bearing evidence, selected device rows, and the
full versioned topology-evidence record and must remain private. The binder
semantically verifies the platform, selected scope, query-row and file digests,
matrix bytes where applicable, and both authority-claim flags before hashing.
`bound/public/` contains the shareable receipts. `control-manifest.json` and
`calibration-plan.json` are admissible only while verification reproduces them
from the retained private evidence. The binder performs no model or provider
call. It does not authorize empirical calibration or numeric Stage 2 freeze.
