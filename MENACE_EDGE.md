# MENACE Edge Seam and Qualification Floor

MENACE Edge is the Tier Bench requirements-mining and qualification program for a detachable edge judgment node. It does not define a new command-and-control authority, mission ontology, product repository, or AXM spoke.

The program has two ordered jobs:

1. **Find the seams.** Compile sanitized operational, technical, and estate donor piles into the smallest set of invariants that repeatedly survive across domains.
2. **Qualify carriers and implementations.** Test whether particular heads, accelerators, models, adapters, networks, and human surfaces preserve those seams and improve accepted human outcomes.

The RTX 3090 and Razer Core X are one candidate carrier for the burst-cognition portion of the resulting contract. They are not the definition of the node.

## Product boundary

The node is four separable objects:

1. **Survival substrate.** CPU, RAM, NVMe, local interfaces, mission state, event journal, deterministic query, authority checks, communications queues, and human apertures.
2. **Burst cognition cartridge.** RTX 3090 in a Razer Core X or another separately qualified 24 GiB CUDA carrier. It performs expensive synthesis, multimodal interpretation, code work, diagnosis, and option generation.
3. **State cartridge.** Signed AXM shards, append-only events, hot mission state, runtime manifests, receipts, and recovery material.
4. **Detachable head and I/O kit.** A qualified Windows or Linux computer supplies the operator surface, CPU, RAM, storage, network adapters, radios, cameras, microphones, and equipment adapters.

No profile may claim pooled VRAM. No model may become state or action authority. Connectivity may add streams and output routes, but it may not restore identity, authority, history, or basic usability.

## Donor-pile census

The committed public census contains six sanitized piles:

```text
local sensing and control
readiness and sustainment
people, communications, and attention
platform sovereignty and substitution
evidence, provenance, and qualification
circulation, orchestration, and recovery
```

The piles contain eighteen donor records. A donor may be a public implemented system, a private reported trace, an operator observation, or a synthetic fixture. Private and mixed donors contribute only a sanitized workload shape to the public repository. The ledger rejects private source bytes, personal-name requirements, operational locations, and exact public use of a private source.

## The eighteen seams

The census currently identifies eighteen mandatory interfaces:

```text
attributed capture
identity resolution without collapse
deterministic state compilation
source-bound relevance selection
role-scoped projection
bounded stochastic interpretation
named authority disposition
idempotent bounded execution
outcome and acceptance receipt
source-preserving synchronization
explicit survival degradation
branch-preserving reconciliation
component and vendor substitution
durable byte and lineage custody
human and task reattachment
visible resource placement
cooperative track handoff
human shift and role handoff
```

Every seam names its producer, consumer, invariant, owner, degradation law, required receipts, minimum independent pile support, and a permanent negative witness. The negative controls include unattributed input, alias collapse, nondeterministic state, opaque context selection, role leakage, model-as-authority, stale mandate, duplicate effects, narrative success, prestige overwrite, WAN dependence, hidden branch conflict, vendor-removal failure, unverifiable archives, lost human context, fictional resource pooling, invented track continuity, and decision-context loss.

## Exact minimal witness set

The coverage matrix registers eight candidate integrated witnesses. The planner exhaustively evaluates every admissible subset up to the declared limit and solves an exact cost-weighted set-cover problem over mandatory seams, mandatory negative witnesses, independent donor-pile support, prerequisites, witness state, and required evidence classes.

The unique minimum is:

```text
witness.cooperative-handoff
witness.multi-role-handoff
witness.partitioned-controller
witness.physical-availability
witness.stack-recovery
```

The five witnesses cover all eighteen seams and all eighteen negative witnesses with no under-supported mandatory seam. Their total declared cost is thirty-one internal comparison units. Those units rank alternatives inside the frozen planner. They do not claim dollars, schedule, field burden, readiness, or operational value.

The plan and report identities are content-derived. `SEAM_CENSUS.md` exposes the pile support for each seam, the selected witnesses, the highest-order pile intersections, and all visible gaps. Permanent CI regenerates the plan and report and requires byte equality with the committed products.

## Reference qualification campaign

After the seam floor is fixed, `experiments/menace_edge/menace_edge_01.json` compiles a prospective ascent and descent through:

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

The 315 cells are an overcomplete prospective universe. They are not an instruction to execute every cell immediately. The exact five-witness set identifies the smallest integrated trace family that must eventually exercise the seam floor.

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

A stock-class 350 W hardware profile is registered for later use but is not granted a candidate treatment by default. The campaign seeks the lowest complete power envelope that produces a Pareto improvement in accepted work, human attention, external bytes, role-seconds served, and recovery behavior.

## Failure law

The reference campaign injects model restart, peer loss, GPU disconnect, remote-versus-local conflict, WAN loss, head swap, and stale remote reporting. Every fault must retain the declared survival capabilities. Remote conflict and stale information require explicit disclosure and, where declared, a named human disposition. Recovery may not mint authority, rewrite history, silently prefer the remote branch, or make basic state dependent on the 3090.

## Thermodynamic evidence

Every measured cell records integer wall and GPU energy, elapsed and recovery time, time to first useful product, human active time, external bytes consumed and avoided, accepted and rejected products, consequential misses, role-seconds served, model calls, and operator interventions.

The analyzer emits exact totals and rational rates. It emits no aggregate score. A candidate is rejected for survival or authority failure, held for incomplete telemetry, and admitted only when matched evidence is no worse on accepted work and consequential misses while materially improving at least one declared dimension. Every report retains `production_claim: false` and `promotion_authorized: false`.

## Commands

Seam census:

```console
python -m tier_runner.menace_seams validate \
  --donors experiments/menace_edge/donor_piles.json \
  --seams experiments/menace_edge/seam_catalog.json \
  --coverage experiments/menace_edge/coverage_matrix.json

python -m tier_runner.menace_seams plan \
  --donors experiments/menace_edge/donor_piles.json \
  --seams experiments/menace_edge/seam_catalog.json \
  --coverage experiments/menace_edge/coverage_matrix.json \
  --out experiments/menace_edge/minimal_witness_plan.json

python -m tier_runner.menace_seams report \
  --donors experiments/menace_edge/donor_piles.json \
  --seams experiments/menace_edge/seam_catalog.json \
  --coverage experiments/menace_edge/coverage_matrix.json \
  --out-json experiments/menace_edge/seam_census_report.json \
  --out-markdown experiments/menace_edge/SEAM_CENSUS.md
```

Physical and operational campaign:

```console
python -m tier_runner.menace_edge validate \
  --manifest experiments/menace_edge/menace_edge_01.json

python -m tier_runner.menace_edge plan \
  --manifest experiments/menace_edge/menace_edge_01.json \
  --out menace-plan.json

python -m tier_runner.menace_edge templates \
  --plan menace-plan.json \
  --out menace-observations.json

python -m tier_runner.menace_edge analyze \
  --manifest experiments/menace_edge/menace_edge_01.json \
  --plan menace-plan.json \
  --observations menace-observations.json \
  --out menace-report.json
```

Generated observation templates begin entirely `unmeasured`. An error receipt remains infrastructure evidence and cannot masquerade as a capability measurement.

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
9. matched execution of the selected witness family against the baseline workflow.

## Authority and placement

Tier Bench owns research design, treatment identity, telemetry, comparison, set-cover planning, and admission evidence. AXM Core and Command retain runtime state and authority law. Genesis may own later interoperable event, claim, or decision-packet profiles. Project-local adapters and ledgers remain with the projects that own their source and action domains. MENACE Edge records the seam between those organs without absorbing their authority.
