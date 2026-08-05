# Start Here

This directory is the cold-entry point for the Community Home Lab Anchor Crate floor.

## Read order

1. `README.md`
2. `ANCHOR_CRATE_ABI.md`
3. `floor.json`
4. `physical_availability_cartridge.json`
5. `backend_registry.json`
6. `backend_equivalence.json`
7. `SCIENCE_PROGRAM.md`
8. `CONTINUITY.md`

## First divergence protocol

When a test or physical run fails, locate the first divergent object rather than rewriting the whole system.

```text
floor contract
  ↓
semantic cartridge
  ↓
portable task ID
  ↓
DAG and node semantic ID
  ↓
backend admission and lowering
  ↓
crate
  ↓
executor response
  ↓
controller validator
  ↓
receipt
  ↓
anchor transition
```

A backend error is not a task failure. A model self-report is not acceptance. A green telemetry dashboard is not a product receipt. A changed runtime, toolchain, model image, head, port, cable, or power limit creates a new execution treatment.

## Generated files

Do not hand-edit:

```text
plan.cuda-fixture.json
plan.riscv-fixture.json
backend_equivalence.json
conformance.*.json
```

Regenerate them through `tieranchor`. CI requires byte equality.

## Ownership

| Plane | Owner |
|---|---|
| Task objective, invariants, DAG, schemas, and acceptance | Project cartridge and Task Floor |
| Task queue, authority, approvals, and external handoff | Tier Desk |
| Backend-neutral task and node identities | Anchor Crate floor |
| Placement, hashes, budgets, validation, effects, and anchor transitions | Deterministic Anchor controller |
| Candidate output and runtime telemetry | Replaceable executor |
| Hardware and model capability claims | TierBench and physical qualification |
| Human disposition | Named human role |

## Forbidden repairs

- Do not add a backend-specific field to task semantics merely to make one executor pass.
- Do not copy hidden validators into a crate.
- Do not accept an executor’s claim that it succeeded or failed without inspecting its product.
- Do not pool memory across devices unless a future task contract explicitly defines and measures a distributed algorithm.
- Do not resume a partial run from conversation or logs when the sealed anchor is missing.
- Do not convert fixture conformance into a physical hardware claim.
