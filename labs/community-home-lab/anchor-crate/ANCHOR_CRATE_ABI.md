# Anchor Crate ABI

## Purpose

The ABI separates a durable task from the hardware that happens to execute it. The task is expressed as a cartridge and semantic DAG. The controller lowers each node onto a backend. A backend may be a local process, container, remote service, GPU runtime, FPGA, RISC-V coprocessor, or custom LLM ASIC.

A new accelerator does not receive task authority. It receives one bounded crate and returns one typed response.

## Identity hierarchy

```text
floor contract SHA-256
  constitutional ABI and authority membrane

semantic cartridge SHA-256
  backend-neutral task, DAG, validators, budgets, and input

portable_task_id
  stable task identity across backend substitutions

node_semantic_id
  stable node identity across backend substitutions

backend manifest SHA-256
  exact architecture, ISA, runtime, toolchain, lowerings, resources, and driver

execution_id
  node semantic identity plus exact backend and lowering

plan_id
  complete DAG placement and acceptance treatment
```

Editorial titles, notes, and supplier descriptions do not perturb the portable task identity. Authority, operations, schemas, validators, effects, budgets, and required seams do.

## Semantic classes

| Class | Meaning | Acceptance rule |
|---|---|---|
| `exact` | Pure deterministic transformation or final projection | Exact controller validator |
| `validator_equivalent` | Output wording or representation may vary | Hidden or public controller validators preserve semantics |
| `human_disposition` | A named person exercises bounded authority | Identity, role, mandate, state, and explicit event |
| `effect` | External or mutable effect | Approval, idempotency, postcondition, and compensation law |

“Deterministic task” therefore does not require every model token to be identical. It requires deterministic task identity, DAG state, input custody, placement identity, validator law, outcome classification, and recovery. A stochastic candidate is admissible only through deterministic acceptance.

## Anchor state

The anchor contains the minimum sufficient durable state for another controller process to continue:

- portable task and plan identity;
- parent anchor identity;
- node states and attempt counts;
- content-addressed input and output artifacts;
- accepted receipt identities;
- consumed and remaining budgets;
- exact stop condition;
- explicit non-production and non-promotion state.

Every anchor is canonicalized and hashed. The parent pointer forms an append-only lineage. The anchor contains no chain of thought, hidden validator content, or unverified executor claim.

## Crate

A crate contains:

- portable task, plan, anchor, node semantic, and execution identities;
- one node operation and semantic class;
- input artifact descriptors;
- output schema and controller validator IDs;
- effect and resource envelope;
- remaining budget and stop condition;
- exact backend, runtime, ISA, toolchain, and lowering identities.

The crate is immutable after dispatch. It carries only the context required by the node.

## Executor command protocol

Each invocation receives one canonical JSON request on standard input and emits one canonical JSON response on standard output.

Operations:

```text
describe
probe
execute
cancel
collect
```

The backend may return candidate output, runtime telemetry, and advisory diagnostics. It may not return authoritative acceptance, anchor hashes, artifact hashes, hidden-validator results, or final disposition. Any such claim is rejected by the controller.

## Future accelerator implementation

A custom accelerator vendor needs four artifacts:

1. **Backend manifest.** Exact architecture, ISA, runtime, toolchain digest, model formats, memory, power envelope, telemetry, and supported effects.
2. **Operation lowerings.** One digest-bound compiler or microcode lowering for each operation it claims.
3. **Executor driver.** A small host process implementing the canonical request and response ABI.
4. **Conformance and task receipts.** Driver TCK, frozen cartridges, controller validators, and physical measurements.

The initial RISC-V fixture declares `RV64GCV plus vendor tensor extension`, but the ABI is not tied to that ISA. A future device may use RISC-V orchestration cores with tensor arrays, an FPGA shell, a fixed-function transformer pipeline, or another architecture. The semantic cartridge remains unchanged when the lowerings and resource envelope satisfy the node contract.

## Supply-chain and accreditation path

The backend manifest, driver, lowerings, model image, and toolchain are separate content-addressed subjects. They can be packaged through OCI artifacts, SBOMs, in-toto links, SLSA provenance, and signatures. Those records establish identity and lineage. The controller’s task validators and acceptance receipts establish task correctness.
