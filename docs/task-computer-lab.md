# Project-native Task Computer Lab

## Purpose

The Task Computer Lab turns the Manus-shaped Playwright computer into a repeatable project instrument. A browser task is represented by an objective, an external acceptance authority, an ordered surface ladder, a side-effect policy, a planner packet, a critic verdict, action receipts, and a project-specific handoff. The reference script is a baseline planner, not the task definition.

The first catalog covers four live project needs:

| Cartridge | Project need | Primary surface | Acceptance authority |
|---|---|---|---|
| `tier-desk-approve-underdrain` | Review acceptance before granting queue authority | Playwright semantic DOM | Hidden task state and transition receipt |
| `axm-chat-pull-latest` | Pull only unseen conversation turns and retain a sync receipt | Playwright plus task downloads | Hidden turn boundary, sealed state, downloaded receipt |
| `screen-ghost-visual-fallback` | Admit a visual action only when semantic control is unavailable | ScreenGhost photonic route | Hidden fixture state plus screenshot-bound request |
| `axm-world-underdrain-playtest` | Prove a legible authored action, consequence, record, and continuation | Playwright semantic DOM | Hidden story state and cold-operator questions |

These are synthetic project fixtures. They prove the control loop and receipt architecture. They do not claim production-site compatibility, real ScreenGhost vision accuracy, live AXM Chat ingestion, or AXM World player acceptance.

## First principles

The lab enforces ten separations:

1. The task is the goal and acceptance contract. It is not an action script.
2. The browser owns session state, files, tabs, screenshots, and traces.
3. Observation compiles the current surface into a state hash and semantic element map.
4. A planner receives a bounded packet and proposes typed actions. It receives no browser object.
5. A critic admits or rejects the proposal under deterministic surface and side-effect policy.
6. The desktop executes accepted actions and emits the next state.
7. ScreenGhost is a named fallback route with its own screenshot-bound request and candidate evidence.
8. Hidden fixture state is available only to the acceptance authority and synthetic visual oracle.
9. Every step is append-only and content-addressed.
10. Promotion remains external. Every run records `promotion_authorized: false`.

## Run the reference suite

Install the browser extra and Chromium once:

```powershell
python -m pip install -e ".[browser]"
python -m playwright install chromium
```

List the cartridges:

```powershell
tiertaskcomputer list
```

Run one headed scenario:

```powershell
tiertaskcomputer run `
  --scenario axm-chat-pull-latest `
  --variant base `
  --headed `
  --out-root <tier-runs-root>\TaskComputer
```

Run the full mutation suite headlessly:

```powershell
tiertaskcomputer suite `
  --out-root <tier-runs-root>\TaskComputer
```

The suite executes every declared scenario variant. A run directory contains:

```text
scenario.json
run-start.json
records/
  0001-packet.json
  0001-proposal.json
  0001-verdict.json
  0001-step.json
  ...
computer/
  workspace/
  downloads/
  artifacts/
  secrets/
project-handoff.json
receipt.json
```

Verify a completed run without reopening the browser:

```powershell
tiertaskcomputer verify --run-dir <tier-runs-root>\TaskComputer\<run-id>
```

## Planner iteration

The reference planner selects targets by stable matcher rather than recorded numeric index. Element order can change without rewriting the plan. The current matchers support ID, test ID, exact or partial accessible name, visible text, role, tag, and one stable attribute.

To test a local model, provide an executable that reads one planner packet as JSON on stdin and writes one proposal as JSON on stdout:

```powershell
tiertaskcomputer run `
  --scenario tier-desk-approve-underdrain `
  --planner-command "python <tier-models-root>\planner_wrapper.py" `
  --out-root <tier-runs-root>\TaskComputer
```

The proposal must bind both the packet hash and current state hash. The response contract is embedded in every packet.

For the <dual-3090-node> topology, use a shared exchange:

```powershell
tiertaskcomputer run `
  --scenario axm-world-underdrain-playtest `
  --planner-exchange <tier-exchange-root>\TaskComputer `
  --planner-timeout 1800 `
  --out-root <tier-runs-root>\TaskComputer
```

The desktop writes a content-addressed request under:

```text
<exchange>/<run-id>/planner/requests/
```

The Gram-side planner writes the matching response under:

```text
<exchange>/<run-id>/planner/responses/
```

This file exchange is intentionally model-neutral. A 3090 can run an Ollama, llama.cpp, vLLM, or custom local wrapper without giving it authority over the browser profile.

## ScreenGhost route

The visual fallback cartridge intentionally renders a visible control that does not expose button semantics, a role, tabindex, or an inline click attribute. The Playwright state therefore contains the visible text and screenshot but no semantic action target.

The reference run emits:

```text
screen-ghost-request.json
state hash
clean screenshot hash
marked screenshot hash
visual target description
effect classification
candidate coordinate contract
```

The current candidate is supplied by a fixture-only oracle and is labeled `synthetic_fixture_oracle`. Replacing that oracle with the real ScreenGhost adapter does not change the request, verdict, action, or receipt shapes.

## Project handoffs

Each cartridge emits a handoff shaped for its owning project:

```text
Tier Desk     task transition and review evidence
AXM Chat      previous/current turn boundary and sealed state
ScreenGhost   photonic route and changed-state result
AXM World     identity, problem, choice, changed world, record, next beat
```

The handoff is a derivative artifact. Its hash binds it to the Task Computer run, while the owning project retains authority to accept, reject, or compile it into its own canonical protocol.

## Iteration order

The next practical sequence is:

1. Run all synthetic fixtures and inspect the marked screenshots, proposals, verdicts, and project handoffs.
2. Replace the reference planner with one local model on a single scenario.
3. Put the second 3090 in critic mode and compare admitted actions against the deterministic critic.
4. Replace the ScreenGhost fixture oracle with the real ScreenGhost candidate adapter.
5. Point a persistent browser profile at a disposable real account or local copy of one project UI.
6. Add a cartridge only after its hidden acceptance authority and failure default are explicit.

The control question for every new cartridge is whether a cold operator can explain who they are, the problem, the action chosen, what changed, what was recorded, and what happens next from the retained run alone.
