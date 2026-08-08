# Task Floor adapter guide

## Minimal implementation path

A runtime does not need to use Tier Bench, Playwright, or the Task Computer. To enter the floor, it needs four adapters:

1. A capability manifest describing what the runtime actually enforces.
2. A command driver implementing the eight TCK operations.
3. A cartridge adapter translating a task and its independent acceptance authority.
4. A bundle exporter translating one completed run into the canonical trajectory and artifact package.

The quickest path is:

```bash
python -m tier_runner.task_floor_cli manifest-validate --manifest manifest.json
python -m tier_runner.task_floor_cli driver-test --command "your-driver"
python -m tier_runner.task_floor_cli bundle-build \
  --run-dir your-run \
  --manifest manifest.json \
  --out-dir portable-bundle
python -m tier_runner.task_floor_cli bundle-assess \
  --bundle portable-bundle/bundle.json
```

## Command-driver protocol

Every process invocation receives one `task-floor/driver-request@1` document on standard input. It returns one `task-floor/driver-response@1` document on standard output. Standard error may contain diagnostics, but it must not contain the canonical response.

A driver should persist idempotency receipts and task state outside the process because the TCK invokes the command repeatedly. The reference implementation uses `TASK_FLOOR_DRIVER_ROOT`.

### `describe`

Return the normalized capability manifest. Do not claim a profile from code paths that the driver cannot exercise.

### `reset`

Create the deterministic reference task supplied by the request and return its initial content-addressed state.

### `observe`

Return the current state without changing it.

### `act`

Validate the action hash, expected state, effect, approval, preconditions, idempotency key, and authority. Return an action receipt and new state or a typed rejection. Repeating the same idempotency key must return the same receipt without reapplying the effect.

### `takeover` and `release`

Create an exclusive human lease. While it is active, agent actions must fail. Release must produce a newly observed state, even when no user-visible field changed.

### `accept`

Run an independent verifier over hidden state or postconditions and return the acceptance result and project handoff.

### `close`

Release runtime resources without deleting evidence.

## Mapping common systems

### MCP

Expose the backend’s ordinary MCP tools. Add Task Floor extension fields for surface, effect, state-binding requirement, idempotency behavior, cartridge, and profile claim. Treat standard tool annotations as hints, not trusted policy facts. The trusted Task Floor host recomputes or verifies the effect.

### A2A

Publish an AgentCard and skill for each cartridge or capability family. Preserve the manifest and cartridge hashes in an extension. A2A task and artifact identifiers should be references into the canonical Task Floor run, not replacement identities.

### AG-UI

Emit state snapshots or deltas, tool-call events, approval interrupts, human takeover, and completion events. Include `state_id`, `action_sha256`, `approval_sha256`, and `event_sha256` in event payloads.

### OpenTelemetry

Use the canonical trace context when available. Spans should identify the Task Floor run, step, effect, authority, action, state, acceptance, and bundle. Telemetry is observational evidence and cannot replace receipts.

### OPA or Cedar

Build policy input from the canonical action, principal, on-behalf-of identity, resource, effect, state, approval, and cartridge. Persist both input and decision identities. The enforcement point must verify that the action presented at execution is the action that was evaluated.

### SPIFFE and OAuth delegation

Map workload identity into the action principal and runtime attestation. Map human or service delegation into `on_behalf_of`. Credentials remain under the credential custodian and should be leased or exchanged for the minimum audience, scope, and lifetime.

### in-toto and SLSA

Use the bundle, cartridge, trajectory, manifest, project handoff, and retained artifacts as subjects or materials. The statement proves provenance. It does not prove task acceptance unless the acceptance result and verifier are included in the predicate.

### BrowserGym or Cua

Wrap the cartridge as the task environment and use the native action space. Export the native trajectory as a compatibility view while preserving Task Floor state, effect, policy, and acceptance events.

### LangGraph

Map state identities to checkpoints, human approval and takeover to interrupts, and idempotency keys to replay guards. A resumed graph must re-observe external state before repeating an effect.

### AgentRx

Feed the canonical trajectory, invariants, failure category, and artifacts into diagnosis. Keep the Task Floor event chain as the source of truth so diagnosis output can be regenerated.

## Adapter anti-patterns

An adapter is non-conformant when it:

- Creates a new unlinked action identity after policy admission
- Treats a model-generated risk label as trusted effect classification
- Drops the exact state identity and retains only a URL or screenshot
- Turns a human approval into an unscoped session Boolean
- Retries an external write without consulting idempotency evidence
- Lets planner completion replace external acceptance
- Omits failed attempts or human intervention from the trajectory
- Exports artifacts without hashes or includes secrets in the portable bundle
- Claims production readiness from a synthetic fixture alone
- Rewrites a protocol export and presents it as the canonical run

## Contributing an adapter

An adapter contribution should include:

```text
capability manifest
command driver or bundle exporter
at least one cartridge fixture
TCK output
protocol-specific test vectors
failure-default description
license and dependency inventory
primary-source mapping notes
```

A new adapter should pass the zero-dependency tests on Windows and Linux. Runtime-specific integration tests may install the backend in a separate CI job.
