# Task Computer dual-3090 team

## Physical roles

The browser computer remains on the desktop. Its Chromium profile, files, tabs, downloads, approvals, action receipts, and human takeover boundary never move to the LG Gram.

```text
desktop RTX 4060 lane
  Playwright browser and task workspace
  project cartridge and acceptance authority
  deterministic policy critic
  action execution and changed-state observation

LG Gram RTX 3090 A
  planner worker
  receives bounded state packets
  returns typed action proposals

LG Gram RTX 3090 B
  independent critic worker
  receives the state and proposed action batch
  returns pass or hold with errors, warnings, and rationale
```

The deterministic desktop critic remains authoritative even when the 3090 critic passes. A remote critic rejection holds the proposal before the desktop browser receives it. The two model seats therefore add cognition and adversarial review without acquiring browser-profile authority.

## Exchange layout

Both computers mount the same shared exchange under their own local paths:

```text
<exchange>/<run-id>/planner/
  requests/
  claims/
  responses/
  receipts/

<exchange>/<run-id>/critic/
  requests/
  claims/
  responses/
  receipts/
```

Each request is content-addressed by the current state and packet hash. A worker claims through exclusive file creation, invokes one stdin/stdout model wrapper, validates the response contract, publishes atomically, and writes a seat receipt. Stale claims are recoverable after the declared lease window.

## Transport smoke before models

Use the deterministic fixture adapter to prove both GPU seats, shared storage, and desktop orchestration before loading a model.

On the LG Gram, open two PowerShell windows. Bind the exact UUIDs reported by `nvidia-smi`:

```powershell
$env:TIER_GPU_3090_A_UUID = "GPU-..."
$env:TIER_GPU_3090_B_UUID = "GPU-..."
$env:TIER_EXCHANGE_ROOT = "Z:\TierExchange\TaskComputer"
```

Start the planner seat:

```powershell
.\scripts\run-task-computer-team-worker.ps1 `
  -Role planner `
  -SeatId gpu.3090-a `
  -GpuUuidEnv TIER_GPU_3090_A_UUID `
  -ExchangeRoot Z:\TierExchange\TaskComputer `
  -ModelCommand "python examples\task_computer\fixture_team_agent.py"
```

Start the critic seat:

```powershell
.\scripts\run-task-computer-team-worker.ps1 `
  -Role critic `
  -SeatId gpu.3090-b `
  -GpuUuidEnv TIER_GPU_3090_B_UUID `
  -ExchangeRoot Z:\TierExchange\TaskComputer `
  -ModelCommand "python examples\task_computer\fixture_team_agent.py"
```

On the desktop, mount the same bytes and run a headed cartridge:

```powershell
$env:TIER_EXCHANGE_ROOT = "D:\TierExchange\TaskComputer"

.\scripts\run-task-computer-lab.ps1 `
  -Command run `
  -Scenario axm-world-underdrain-playtest `
  -Variant reordered `
  -PlannerExchange D:\TierExchange\TaskComputer `
  -CriticExchange D:\TierExchange\TaskComputer `
  -Headed
```

The deterministic adapter is not an intelligence result. A successful run proves that the desktop emitted a state-bound packet, 3090 A returned a valid proposal, 3090 B reviewed the same proposal, the desktop policy admitted it, Playwright executed it, hidden project acceptance passed, and all exchange and browser receipts verify.

## Replacing the smoke adapter with local models

A model wrapper reads exactly one JSON document on stdin and writes exactly one JSON document on stdout. The worker sets:

```text
TIER_TASK_ROLE=planner or critic
TIER_TASK_SEAT_ID=<declared seat>
CUDA_VISIBLE_DEVICES=<exact NVIDIA GPU UUID>
```

The planner response contract is included in every planner packet. The critic response contract is included in every critic request. The wrappers may use llama.cpp, Ollama, vLLM, Transformers, or another local runtime, but they must preserve the JSON boundary and must not manipulate the browser directly.

Suggested first model comparison:

```text
3090 A  one local coding or general instruction model as planner
3090 B  a different model or quantization as critic
4060    small desktop classifier, embeddings, screenshot routing, and policy services
```

Swap planner and critic seats on alternate runs. Compare accepted task success, critic disagreement, retries, wall time, tokens, and action count. The goal is accepted work per hour under complete receipts rather than nominal GPU utilization.

## Failure default

Absent UUIDs, source drift, duplicate claims, malformed JSON, stale packet hashes, critic rejection, unavailable targets, action-policy conflict, hidden acceptance failure, and incomplete receipts hold the run. The model seats can recommend actions, but only the desktop can act on the browser computer.
