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

## Identity

Manifest, scenario, run, event, output, debrief, and adapter response identifiers are content-derived. Wall-clock generation time and absolute workspace paths are excluded from the run identity. The same manifest, scenario, execution mode, and adapter status produce the same run identifier. Receipt directories include the scenario id and run id so repeat runs converge on one identity-bearing location.

## Failure behavior

The runtime fails closed on malformed artifacts, unknown references, authority mismatch, stale ownership, adapter failure, semantic mutation, projection mismatch, and impossible route constraints. Duplicate events are accepted as idempotent no-ops and recorded as duplicates. Repository absence, skipped probes, and synthetic execution remain visible rather than being promoted to success evidence.

## Migration

The laboratory may later move into a dedicated `axm-surface` repository if its semantic contracts become a shared runtime dependency. That migration must preserve Tier Bench as the measurement authority, keep AXM-ARC as the game-law authority, keep AXM Embodied as the physical-safety authority, retain exact receipt compatibility, and prove that Tier Bench can remove the implementation without losing its scenarios, route data, or historical run interpretation.
