# MENACE Edge Qualification

MENACE Edge is the Tier Bench research and qualification program for a detachable edge judgment node. It does not define a new command-and-control authority, a new mission ontology, or a new repository. It tests whether a replaceable Thunderbolt head and a 24 GiB RTX 3090 burst cartridge can improve accepted human work while AXM-owned state, evidence, authority, communications, and recovery remain locally available without WAN or the burst GPU.

## Product boundary

The node is four separable objects:

1. **Survival substrate.** CPU, RAM, NVMe, local interfaces, mission state, event journal, deterministic query, authority checks, communications queues, and human apertures.
2. **Burst cognition cartridge.** RTX 3090 in a Razer Core X or another separately qualified 24 GiB CUDA carrier. It performs expensive synthesis, multimodal interpretation, code work, diagnosis, and option generation.
3. **State cartridge.** Signed AXM shards, append-only events, hot mission state, runtime manifests, receipts, and recovery material.
4. **Detachable head and I/O kit.** A qualified Windows or Linux computer supplies the operator surface, CPU, RAM, storage, network adapters, radios, cameras, microphones, and equipment adapters.

No profile may claim pooled VRAM. No model may become state or action authority. Connectivity may add streams and output routes, but it may not restore identity, authority, history, or basic usability.

## Reference campaign

`experiments/menace_edge/menace_edge_01.json` compiles a fixed ascent and descent through:

```text
C0 isolated
C1 immediate cell
C2 peer mesh
C3 intermittent reachback
C4 enterprise or theater
C3 intermittent reachback
C2 peer mesh
C1 immediate cell
C0 isolated
```

The campaign crosses five workload families with seven treatments, producing 315 deterministic cells. The workload shapes are:

- multi-role mission handoff;
- partitioned command and controller supervision;
- inventory, maintenance, and physical availability;
- cooperative sensing and communications handoff;
- head, runtime, and adapter substitution.

The committed fixture contains no private source bytes, live operational locations, customer records, or production claim. Private or external donors are represented only as sanitized workload shapes and evidence classes.

## Treatments

The initial comparison set is:

```text
baseline current workflow
AXM survival substrate without a burst model
raw 3090 endpoint without AXM state, authority, or evidence custody
AXM + 3090 at 225 W
AXM + 3090 at 250 W
AXM + 3090 at 275 W
AXM + 3090 at 250 W with intermittent reachback
```

A stock-class 350 W hardware profile is registered for later use but is not granted a candidate treatment by default. The campaign is intended to find the lowest complete power envelope that produces a Pareto improvement in accepted work, human attention, external bytes, role-hours served, and recovery behavior.

## Failure law

The reference campaign injects model restart, peer loss, GPU disconnect, remote-versus-local conflict, WAN loss, head swap, and stale remote report. Every fault must retain the declared survival capabilities. Remote conflict and stale information require explicit disclosure and, where declared, a named human disposition. Recovery may not mint authority, rewrite history, silently prefer the remote branch, or make basic state dependent on the 3090.

## Thermodynamic evidence

Every measured cell records integer wall and GPU energy, elapsed and recovery time, time to first useful product, human active time, external bytes consumed and avoided, accepted and rejected products, consequential misses, role-seconds served, model calls, and operator interventions.

The analyzer emits a vector of exact totals and rational rates. It deliberately emits no aggregate score. A candidate is rejected for survival or authority failure, held for incomplete telemetry, and admitted only when it is no worse on accepted work and consequential misses while materially improving at least one declared dimension against matched baseline cells. Every report retains `production_claim: false` and `promotion_authorized: false`.

## Commands

```console
python -m tier_runner.menace_edge validate \
  --manifest experiments/menace_edge/menace_edge_01.json

python -m tier_runner.menace_edge plan \
  --manifest experiments/menace_edge/menace_edge_01.json \
  --out menace-plan.json

python -m tier_runner.menace_edge verify \
  --manifest experiments/menace_edge/menace_edge_01.json \
  --plan menace-plan.json

python -m tier_runner.menace_edge templates \
  --plan menace-plan.json \
  --out menace-observations.json

python -m tier_runner.menace_edge analyze \
  --manifest experiments/menace_edge/menace_edge_01.json \
  --plan menace-plan.json \
  --observations menace-observations.json \
  --out menace-report.json
```

The generated observation file begins entirely `unmeasured`. An error receipt remains an infrastructure observation and cannot masquerade as a capability measurement.

## First physical transaction

The first physical transaction begins with the renewed Dell RTX 3090 completely stock during the return window. It records enclosure identity, cable, port, head, driver, GPU UUID, negotiated link, power limit, temperatures, throttle state, errors, cold hydration, steady-state traffic, disconnect recovery, and output coherence. Thermal-pad work is admissible only after stock evidence identifies memory temperature or throttling as the limiting variable.

The initial sequence is:

1. host-only C0 survival and deterministic-query pass;
2. stock 3090 enumeration and full 24 GiB allocation;
3. 225 W sustained model-resident inference;
4. 250 W and 275 W only when accepted work improves;
5. GPU disconnect with survival-floor retention;
6. model-server restart and exact state replay;
7. head swap between two qualified TB3 or TB4 computers;
8. connectivity ascent and descent with branch-preserving reconciliation;
9. matched multi-role campaign against the baseline workflow.

## Authority and placement

Tier Bench owns research design, treatment identity, telemetry, comparison, and admission evidence. AXM Core and Command retain runtime state and authority law. Genesis may own a later interoperable event or decision-packet profile. Project-local adapters and ledgers remain with the projects that own their source and action domains. MENACE Edge does not create another spoke and does not absorb those authorities.
