# AXM Estate Lab

AXM Estate Lab is both the executable integration instrument for the BigBirdReturns project estate and the reference implementation of the public AXM Interaction Floor. The internal laboratory measures whether a semantic action can cross project boundaries, retain the correct actor and mandate, survive route loss or source drift, commit one deterministic state transition, and emit inspectable receipts. The public floor lets an outside project prove the narrower adapter boundary without importing the estate manifest, AXM game law, or repository topology. Both surfaces live in Tier Bench because their authority is measurement and conformance. They do not own cartridge law, human disposition, physical safety, project priority, deployment approval, or the truth of an observed claim.

The laboratory converts the Halcyon Dawn and Enigma harvest into a general estate exercise. The original project demonstrated that a large physical console becomes tractable when generic devices, installation declarations, edge-local feedback, host-side typed bindings, atomic state publication, software twins, and reconnect snapshots are treated as one system. Estate Lab applies that system shape to AXM-ARC, AXM-WORLD, ScreenGhost, agent-runtime, AXM Embodied, AXM Console, Aide, Bloodstream, Hinge, EarCrate, Zombie Adapter, GhostBox, and Organ Evolution.

## What the laboratory proves

A laboratory run has five independent gates. Repository probes establish which project surfaces are present and whether their declared smoke or full checks pass. Route evaluation admits or refuses each candidate from explicit evidence, determinism, replayability, locality, latency, cost, fragility, and authority-risk terms. Semantic execution checks actor, role, mandate, and ownership epoch before state mutation. Equivalence trials run the same action through different embodiments and require the same state, desired-output, and causal-debrief hashes. Fault trials inject stale ownership, route loss, duplicate delivery, semantic mutation, target refusal, and projection corruption, then require the declared refusal or recovery.

Synthetic mode proves the laboratory contract and its deterministic reference fixtures. It does not claim that Quest, ESP32, a sibling repository, or electrical hardware was exercised. Live mode resolves sibling repositories below one workspace, runs the selected probes, and refuses command or artifact adapters whose owning repositories are absent or failed.

## Reference estate

The retained manifest currently classifies 14 organs, 15 adapters, and 18 routes. The five reference scenarios exercise different layers of the estate.

| Scenario | Mechanism under test | Projects exercised |
|---|---|---|
| `common-control-proof-001` | One coolant-bypass action through direct, ScreenGhost, agent, Quest, and ESP32 embodiments | Tier Bench, AXM-WORLD, ScreenGhost, agent-runtime, AXM Embodied |
| `common-ship-handoff-001` | AI source ownership, captain-attributed transfer, and human embodied takeover | agent-runtime, AXM-WORLD, AXM Console, AXM Embodied |
| `decision-marker-001` | One operator marker routed to proposal, circulation-reference, and hinge-candidate records without execution authority | AXM Console, Aide, Bloodstream, Hinge |
| `underdrain-pump-room-001` | A legible pump, bypass, purge, fungus-seal, contamination, flow, and recovery procedure | AXM-WORLD, ScreenGhost, AXM Embodied |
| `estate-circuit-001` | Cross-organ compute planning, live-audio control, organ evolution, and attention candidacy | Zombie Adapter, EarCrate, AXM Tools, GhostBox, AXM Console |

## Public Interaction Floor

The public floor closes the gap between a strong internal harness and a usable external compatibility target. Its normative specification, adapter declaration, request and response envelopes, profiles, quality tiers, bindings, conformance submission, registry, and gap ledger are all machine-readable and content-addressed. The retained floor currently contains eight profiles, five quality tiers, eight binding definitions, seventeen dynamic vectors plus static profile checks, a zero-dependency reference adapter, a zero-dependency starter generator, and a forty-item executable gap ledger.

```bash
python -m estate_lab floor validate
python -m estate_lab floor describe
python -m estate_lab floor test --output .floor-conformance
python -m estate_lab floor gaps
```

Generate a third-party adapter that does not depend on Estate Lab at runtime:

```bash
python -m estate_lab floor init-adapter ./my-adapter \
  --adapter-id org.example.my-adapter \
  --name "Example Adapter"

python -m estate_lab floor test \
  --adapter ./my-adapter/adapter.json \
  --output ./my-adapter/conformance
```

The reference adapter passes every claimed profile and reaches gold. Platinum remains intentionally unavailable to self-certification because it requires an independent verifier and a supplier substitution or rip-out receipt. See [`FLOOR_SPECIFICATION.md`](FLOOR_SPECIFICATION.md), [`FLOOR_CONFORMANCE.md`](FLOOR_CONFORMANCE.md), [`FLOOR_GOVERNANCE.md`](FLOOR_GOVERNANCE.md), [`FLOOR_BINDINGS.md`](FLOOR_BINDINGS.md), and [`ADOPTING_FLOOR.md`](ADOPTING_FLOOR.md).

## OSS and commodity acquisition ledger

The reviewed catalog at `fixtures/commodities.example.json` covers 81 public projects and standards across 27 capability categories. It records 18 consume decisions, 37 bounded adapters, 25 design references, and one preserved rejection. Version 0.3 adds the standards and governance layer needed for external adoption, including CloudEvents, AsyncAPI, W3C Trace Context, OpenTelemetry semantic conventions, W3C Web of Things, Sparkplug, the WebAssembly Component Model, OCI and ORAS, Sigstore, SLSA, SPDX, CycloneDX, JSON Schema, MCP, A2A, and public conformance-program references.

Every consumed or adapted supplier names a substitution test. Every adapted supplier names its adapter contract. Every candidate names the authority it may not acquire. The catalog identity is content-derived, so a changed decision, source, license posture, risk, or acquisition boundary changes the catalog ID. See [`COMMODITY_SWEEP.md`](COMMODITY_SWEEP.md) for the cross-community analysis and the first ten supplier fixture families.

Inspect the complete acquisition plan:

```bash
python -m estate_lab commodities
```

Filter to immediate physical and embodied suppliers and emit machine-readable JSON:

```bash
python -m estate_lab commodities \
  --decision consume \
  --decision adapt \
  --priority P0 \
  --target axm-embodied \
  --format json
```

Write a durable Markdown projection:

```bash
python -m estate_lab commodities \
  --format markdown \
  --output .estate-lab-runs/commodity-plan.md
```

The catalog does not assert that a supplier works for AXM merely because its upstream project is mature. It defines the candidate, boundary, evidence, risk, and required rip-out test that a Supplier Foundry qualification must execute.

## Run the retained proof

From the Tier Bench repository root:

```bash
python -m estate_lab validate
python -m estate_lab commodities --format json
python -m estate_lab floor validate
python -m estate_lab floor test --output .floor-conformance
python -m unittest discover -s estate_lab/tests -v
python -m estate_lab run-all --output .estate-lab-runs
```

Each scenario writes a content-addressed directory containing the manifest and scenario snapshots, the complete run receipt, semantic events, source and target adapter responses, route evaluations, desired outputs, causal debriefs, probe logs, a Markdown summary, a standalone HTML report, and SHA-256 checksums.

Inspect one route decision without changing state:

```bash
python -m estate_lab route engineering.coolant_bypass.set \
  --role engineering \
  --mandate ship.engineering.control \
  --candidate route.world.direct \
  --candidate route.world.screen \
  --candidate route.world.agent
```

Require a physical route:

```bash
python -m estate_lab route engineering.coolant_bypass.set \
  --role engineering \
  --mandate ship.engineering.control \
  --require-tag physical
```

## Exercise the local project estate

The Windows launcher defaults to the current project topology and keeps output outside the repositories:

```powershell
powershell -ExecutionPolicy Bypass -File estate_lab/scripts/run_estate_lab.ps1 \
  -Workspace <projects-root> \
  -Output <projects-root>\AXM\estate-lab-runs \
  -ProbeProfile smoke
```

The equivalent portable command is:

```bash
python -m estate_lab discover \
  --workspace /path/to/projects \
  --mode live \
  --probe-profile smoke

python -m estate_lab run-all \
  --workspace /path/to/projects \
  --mode live \
  --probe-profile smoke \
  --output /path/to/estate-lab-runs
```

Live mode does not silently replace an absent project with its synthetic stand-in. Synthetic adapters are marked degraded, artifact and command adapters are unavailable when their repositories are missing, failed probes make the owning adapter unavailable, and the route ledger states why every rejected route failed.

## Route law

Routing contains a hard gate followed by transparent arithmetic. A candidate must match the semantic action prefix, required role, required mandate, adapter health, minimum evidence, determinism, replayability, locality, latency, cost, and required or forbidden tags. Eligible peer routes are scored from the manifest-owned weights. A fallback route is considered only when no route in the earlier fallback tier is admissible. This prevents a highly scored fallback from silently replacing a healthy declared primary.

The retained default score is:

```text
100 × evidence
+ 45 × determinism
+ 40 × replayability
+ 20 × locality
- 1 × latency_ms
- 2 × cost_microunits
- 35 × fragility
- 60 × authority_risk
```

The score selects among already admissible routes. It cannot make an inadmissible route legal, grant a role, authenticate an actor, promote an evidence class, or authorize a human decision.

## Adapter contracts

The internal estate route contract and the public floor contract are separate by design. Internal source and target adapters remain bound to an estate organ and receive `axm-adapter-request/1` objects. The public floor uses `axm-interaction-request/1`, `axm-semantic-event/1`, `axm-interaction-response/1`, and a standalone `axm-interaction-adapter/1` declaration. An outside implementation can therefore prove protocol compatibility without claiming a place in the AXM estate.

Both command bindings execute with argv arrays and `shell=False`. No scenario or event value becomes shell code. Nonzero exit, timeout, missing response, malformed JSON, identity drift, refusal mismatch, semantic mutation, or response nondeterminism becomes explicit evidence.

See [`ADAPTER_CONTRACT.md`](ADAPTER_CONTRACT.md) for the internal route seam and [`FLOOR_SPECIFICATION.md`](FLOOR_SPECIFICATION.md) for the external narrow waist.

## Authority and ownership

Every semantic action names a subject, actor, role, mandate, and ownership epoch. The current state carries the authoritative ownership record for that subject. Actor, role, mandate, epoch, and route authority must all agree before either adapter runs or state changes. A source that loses tracking or control must relinquish its epoch. A later packet from the previous source is stale even when its value appears plausible.

The laboratory models ownership as state because ownership transfer must be replayable and inspectable. AXM Embodied remains the authority for signed physical envelopes and actuation refusal. Estate Lab can prove that an event was rejected under a declared ownership model; it cannot prove that a motor, switch, hand tracker, or operator physically behaved as claimed.

## Project probes

Each organ declares zero or more manifest-owned probes. Probes are grouped by `smoke` and `full`, execute in the resolved repository with a bounded timeout, and retain exit code, duration, stdout hash, stderr hash, and failure reason. Probe commands never run through a shell. Missing executables are skipped by name, missing required paths fail visibly, and repository absence remains `missing` rather than being reused as stale evidence.

The reference smoke profile covers the Estate Lab suite, AXM-ARC type checking, AXM-WORLD type checking, Zombie Adapter golden reconstruction, and Organ Evolution validation when those repositories are present. The full profile declares the projects' deeper test or gate commands. A failed project probe makes that organ's live adapters unavailable for route admission.

## Adding an organ or experiment

Extend `fixtures/estate.example.json` by separating the organ, adapter, and route objects. The organ states its bounded function, what it owns, what it refuses, its local repository names, and any probes. The adapter states one embodiment and evidence class. The route states the semantic action family, source and target adapters, authority requirements, tags, metrics, and explicit fallbacks.

Add a scenario under `fixtures/scenarios/`. An equivalence scenario runs one semantic action independently through several routes and compares route-independent fingerprints. A sequence scenario commits several actions through one shared state. Both forms may include routing and fault trials. The parser rejects unknown fields, duplicate identifiers, unknown references, mismatched action authority, invalid pointers, and fallback cycles.

## Evidence boundary

A passing synthetic run confirms the parser, route arithmetic, authority checks, reducer, adapter non-mutation contract, equivalence comparison, injected-fault handling, receipt construction, and deterministic identifiers. A passing live probe confirms only the declared project command and the bytes retained in its receipt. A physical route remains reported or derived until a commissioned device, raw event stream, calibration record, reconnect trial, and independent replay are present. No software receipt is allowed to borrow the evidentiary status of hardware it did not exercise.

The control question for every extension is whether one semantic action can enter through multiple admitted sources, remain inside one actor and authority envelope, survive route loss and ownership transfer, and reproduce the same committed state, desired outputs, causal debrief, and receipt without importing another organ's law.
