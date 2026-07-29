# Estate Lab design authority

## Classification

Estate Lab is a measurement and conformance organ inside Tier Bench. It exercises project boundaries, routes semantic work, and retains deterministic receipts. It is not a central runtime for the estate and does not absorb the authority of the projects it connects.

## Actors

The estate steward owns the manifest, route policy, scenario inventory, and acceptance of laboratory changes. Each project maintainer owns that project's adapter and probe declarations. A scenario author owns the experimental objective and expected outcomes. The laboratory runtime applies the declared rules mechanically. A human reviewer decides whether a passing experiment is sufficient to change an estate organ, route, or deployment.

## Mechanism

The manifest declares organs, adapters, routes, metrics, probes, and fallback edges. A scenario declares initial state, semantic actions, authority claims, expected state, routing trials, fault trials, and invariants. The runtime validates both artifacts, discovers repositories, runs requested probes, projects probe health onto adapter status, evaluates candidate routes, checks ownership, executes source and target adapters, reduces state, projects desired outputs, produces causal debriefs, and writes a checksummed receipt bundle.

The reducer is intentionally generic. It supports bounded `set`, `increment`, `append`, `remove`, and `toggle` operations against non-root JSON pointers. Domain law remains in the scenario or the project adapter. A production AXM-ARC and AXM-WORLD integration should replace generic reduction with Arc-owned action verification while preserving the same route, authority, and receipt boundaries.

## Routing

Route admission and route scoring are separate. Admission checks semantics, authority, availability, evidence floors, deterministic and replayable requirements, locality, latency, cost, and tags. Scoring ranks only admitted peer routes. Fallback depth outranks score, so a fallback cannot displace an admissible primary. The complete evaluation table remains in the receipt.

## Commodity acquisition

The commodity catalog is a reviewed supplier-decision ledger rather than an online popularity index. It separates consume, adapt, reference, and reject decisions. A consumed supplier must expose an open standard or permissive code contract and a substitution test. An adapted supplier must name the adapter and rip-out test that prevent its vocabulary, policy, or state from becoming AXM authority. Reference candidates contribute fixtures and lessons only. Rejected candidates retain the failure reason.

Supplier maturity, community size, and feature breadth do not waive authority or evidence gates. The catalog may recommend an acquisition experiment, but only a Supplier Foundry qualification can establish the measured context, exact version, license, budgets, semantic conformance, fallback, and removal evidence.

## Identity

Manifest, scenario, commodity catalog, floor specification, floor adapter declaration, conformance submission, adapter registry, gap ledger, run, event, output, debrief, and adapter response identifiers are content-derived. Wall-clock generation time and absolute workspace paths are excluded from the run identity. The same manifest, scenario, execution mode, and adapter status produce the same run identifier. Receipt directories include the scenario id and run id so repeat runs converge on one identity-bearing location.

## Failure behavior

The runtime fails closed on malformed artifacts, unknown references, authority mismatch, stale ownership, adapter failure, semantic mutation, projection mismatch, and impossible route constraints. Duplicate events are accepted as idempotent no-ops and recorded as duplicates. Repository absence, skipped probes, and synthetic execution remain visible rather than being promoted to success evidence.

## Migration

The reference implementation may later move into a dedicated repository if the public floor becomes a shared release surface. That migration must preserve Tier Bench as the measurement authority, keep AXM-ARC as the game-law authority, keep AXM Embodied as the physical-safety authority, retain exact receipt compatibility, and prove that Tier Bench can remove the implementation without losing its scenarios, route data, or historical run interpretation.

## Public interaction floor

Version 0.3 separates the internal estate runtime from a public narrow waist. The internal manifest remains free to model organs, repositories, probes, route metrics, and scenario expectations. An outside project receives only the floor specification, adapter declaration, request and response envelopes, vectors, conformance submission, and registry shapes. This prevents the reference estate from becoming a prerequisite for interoperability.

The public floor owns portable shape and test law. It refuses domain meaning, physical safety, human disposition, scheduling, and truth. The reference command binding runs without a shell. The reference adapter uses only the Python standard library and imports no AXM runtime. A generated starter passes the same public vectors.

## Conformance and registry

Profile claims remain declaration data until static and dynamic vectors pass. The verifier computes bronze through platinum rather than trusting badges. Platinum requires an independent verifier and a substitution receipt because self-conformance cannot establish implementation independence or supplier replaceability.

The adapter registry is a deterministic projection of passing bronze-or-higher submissions. Registry admission does not establish product endorsement, deployment approval, safety, accessibility in use, legal suitability, or upstream maintenance health.

## Executable gap control

The floor gap ledger records protocol, identity, authority, versioning, bindings, conformance, onboarding, distribution, security, physical proof, accessibility, governance, and community-adoption gaps. A gap may be marked closed only when its dependencies are closed or retained references and its closure artifact and test exist. The ledger is content-addressed and acyclic. This keeps roadmaps from laundering intention into completion.

## External standards

CloudEvents, AsyncAPI, W3C Trace Context, OpenTelemetry, W3C Web of Things, Sparkplug, WIT, OCI, ORAS, Sigstore, SLSA, SPDX, CycloneDX, JSON Schema, MCP, and A2A are mapped as commodities or bounded adapters. Their metadata and tooling may surround the floor. None may redefine the semantic event or authority envelope. Their exact acquisition and replacement burdens remain in the commodity catalog and Supplier Foundry.
