# Anchor Crate Continuity and Succession

## Stable mission

Preserve portable task meaning, deterministic controller authority, content-addressed artifacts, append-only anchor lineage, explicit backend substitution, and independently accepted outcomes while every current runtime, model, queue, database, host, and accelerator remains replaceable.

## Replacement transaction

A backend replacement is complete only when the following transaction closes:

1. Freeze the old backend manifest and accepted receipts.
2. Create a new manifest with exact architecture, ISA, runtime, toolchain, model identity, execution cartridge, lowerings, resources, effects, and telemetry.
3. Run driver conformance.
4. Compile the same semantic cartridge against the new backend.
5. Confirm that portable task and node semantic identities remain unchanged.
6. Confirm that plan and execution identities change.
7. Run the same controller validators and hidden acceptance.
8. Compare accepted work, energy, wall clock, memory, interventions, and recovery.
9. Remove the old backend and verify that accepted artifacts, anchors, and reports remain readable.

A replacement that requires editing the task objective, invariants, output schema, validators, or authority law is a task migration rather than a backend substitution.

## Recovery transaction

After process death or head loss:

1. Select the latest verified anchor whose parent chain and artifacts all verify.
2. Recompile the plan from the frozen floor, cartridge, and backend registry.
3. Require exact plan identity.
4. Reopen every accepted artifact by digest.
5. Resume only pending nodes whose dependencies are accepted.
6. Preserve rejected receipts and consumed budgets.
7. Emit a new controller-resume event.

The system refuses implicit reconstruction from model narration, terminal scrollback, or an unsealed checkpoint.

## Disaster rebuild

A complete rebuild requires only:

```text
source repository or Git bundle
floor and cartridge JSON
backend manifests and execution cartridges
content-addressed artifact store
anchor files and receipts
controller implementation or a conforming replacement
```

Optional dashboards, queues, caches, and model servers may be rebuilt from those objects. They are not the archive.

## Succession test

A new maintainer should be able to answer:

- What does the portable task mean?
- Which fields are backend neutral?
- Which exact backend and model image executed each node?
- Which validators accepted the product?
- Which anchor is safe to resume?
- Which component may be removed without changing task meaning?
- What evidence would be invalidated by a runtime, toolchain, model, or authority change?

The floor is durable only when those answers are recoverable without the original operator or model conversation.
