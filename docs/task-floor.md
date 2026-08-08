# Task Floor interoperability and conformance specification

## Status and scope

Task Floor is an MIT-licensed interoperability and assurance layer for agents that can observe state, propose work, call tools, operate browsers or desktops, modify external systems, ask for human intervention, and return artifacts. It is designed to sit below agent frameworks and above concrete runtimes.

Task Floor does not replace MCP, A2A, AG-UI, OpenTelemetry, in-toto, OPA, Cedar, SPIFFE, LangGraph, BrowserGym, Cua, AgentRx, Playwright, Browser Use, Stagehand, Webwright, or computer-use models. Each of those systems solves an important transport, execution, policy, identity, telemetry, provenance, durability, evaluation, or diagnosis problem. Task Floor defines the contracts that must remain true when any of those components is replaced.

The canonical questions are:

1. Which exact state did the actor observe?
2. Which principal proposed the action, on whose behalf, against which resource?
3. What effect could the action have?
4. Which authority admitted the effect?
5. Was the action executed once under the expected preconditions?
6. What changed, and how was that change independently accepted?
7. Which artifacts and handoffs prove the result?
8. Which capability claims are supported by the retained evidence?

## Trust model

Task Floor separates the following authorities. One process may implement several roles in a development fixture, but a conformance claim must declare the actual allocation.

| Authority | Responsibility |
|---|---|
| Observer | Produces content-addressed state and artifacts |
| Planner | Proposes actions and cannot self-authorize them |
| Critic | Reviews proposals without executing them |
| Policy | Applies deterministic effect, approval, identity, and resource rules |
| Executor | Performs admitted actions and emits action receipts |
| Acceptor | Judges postconditions independently of planner completion claims |
| Credential custodian | Holds authenticated state, leases, and delegation material |
| Artifact custodian | Preserves content-addressed evidence and retention policy |
| Human | Supplies approval, intervention, or takeover under an explicit lease |

Transport metadata and model-generated classifications are evidence inputs. They are not automatically trusted policy facts. A runtime may use MCP tool annotations, an A2A AgentCard, an AG-UI event, or an agent-generated risk label, but the trusted host must still decide whether the claimed effect is accurate and admissible.

## Canonical objects

Task Floor v1 defines the following canonical objects. JSON Schemas are published under `schemas/`, while the Python validators in `tier_runner.task_floor_protocol` are the executable reference.

### Capability manifest

A manifest declares interfaces, surfaces, lifecycle features, state guarantees, authority allocation, effect handling, evidence, acceptance, security, observability, identity, execution semantics, privacy, supply chain, versioning, diagnostics, resilience, interoperability exports, and claimed conformance profiles.

A manifest claim is not proof. `manifest_sha256` prevents silent changes, and bundle assessment compares the claim with observed evidence.

### Cartridge

A cartridge defines a project-shaped task independently of any agent or browser backend. It includes:

```text
project and goal
surface ladder
effect taxonomy and approval policy
external acceptance contract
acceptance authority
failure default
project handoff
invariants
environment identity
mutation variants
```

The existing Tier Bench Task Computer scenarios normalize directly into Task Floor cartridges.

### State

A state is content-addressed and contains:

```text
task identity
revision and observation time
previous state identity
surface-specific state
artifact identities
bounded data
```

An action must bind `expected_state_id`. A stale state is a concurrency conflict, not a planning suggestion.

### Action

An action includes:

```text
action and task identity
expected state identity
surface and operation
effect
arguments and intent
idempotency key
principal and on-behalf-of identity
resource
preconditions and expected postconditions
data classifications
compensation or rollback description
approval reference
trace context
```

The action hash covers the complete object. An approval cannot be moved to another state or action without becoming invalid.

### Approval

An approval is a portable, content-addressed decision bound to one task, state, action, effect, authority, issue time, optional expiry, scope, and constraints. A UI-local Boolean or a model statement that an action was approved is insufficient.

### Action receipt

An executor emits an append-only action receipt identifying the starting state, completed state, admitted effect, result or failure, and receipt hash. Idempotent replay returns the original receipt rather than repeating the external effect.

### Trajectory and bundle

A trajectory is a hash-chained event stream over observation, proposal, critique, policy, execution, acceptance, human intervention, and handoff events. An interoperability bundle combines:

```text
manifest
cartridge
run identity and metrics
canonical trajectory
external acceptance
project handoff
non-secret artifacts
protocol exports
claims
```

`bundle-build` can materialize all retained non-secret run artifacts under the bundle directory. The bundle remains verifiable after the original run directory is removed.

### Skill package

A successful trajectory may propose a reusable skill or deterministic program. The package binds the source bundle, trajectory, acceptance, runtime, entrypoint, effects, compatibility, tests, review status, rollback strategy, artifacts, and signatures. A proposed skill is unreviewed and `production_authorized: false` by default.

## Conformance profiles

Profiles are cumulative. A system may implement a higher-level feature without satisfying lower levels, but its highest contiguous profile stops at the first failed level.

| Profile | Meaning | Essential evidence |
|---|---|---|
| TF0 | Discoverable transport | Valid manifest, declared interface, SHA-256 evidence identity |
| TF1 | State-bound execution | Content-addressed state, exact action binding, receipts, optimistic concurrency |
| TF2 | Governed effects | Declared and enforced effects, portable approval, executor separation, idempotency |
| TF3 | External acceptance and evidence | Independent verifier, postconditions, artifact hashes, typed project handoff |
| TF4 | Human and credential resilience | Takeover lease, pause and resume, secret isolation, credential lease, network policy, delegation |
| TF5 | Protocol, telemetry, and provenance portability | MCP, A2A, AG-UI, OpenTelemetry, in-toto, OPA, and CloudEvents exports |
| TF6 | Adversarial replay and recovery | Mutation and injection tests, failure taxonomy, counterfactual replay, compensation, redaction |
| TF7 | Evidence-backed production claim | Claim verification, workload attestation, signatures, reproducible environment, retention, version negotiation, production qualification |

TF7 is intentionally difficult. Declaring `production_qualified: true` cannot make it pass. All lower profiles must pass, the claim must not exceed evidence, and production qualification must be supported by retained attestations.

## Driver conformance kit

A runtime can implement the Task Floor command driver without adopting Tier Bench internals. The driver reads one request as JSON on standard input and writes one response as JSON on standard output.

Required operations are:

```text
describe
reset
observe
act
takeover
release
accept
close
```

The public TCK performs live probes for manifest validity, state hashing, stale-action rejection, optimistic concurrency, action binding, idempotent local writes, unapproved external-write denial, approved external writes, takeover pause and release, resumed state identity, hidden acceptance, and closure.

The reference driver reaches TF4. TF5 is assessed through a complete interoperability bundle because protocol exports require a trajectory and evidence package rather than one live command exchange.

## Interoperability exports

Exports are compatibility views over the canonical bundle. They do not claim that the target protocol natively enforces Task Floor requirements.

| Export | Mapping |
|---|---|
| MCP | Tools and annotations, with explicit notice that annotations are untrusted hints |
| A2A | AgentCard, skill, Task Floor extension, and supported interface |
| AG-UI | Run, state, tool-call, approval, and completion events |
| OpenTelemetry | GenAI-oriented spans and attributes linked to the canonical trajectory |
| in-toto | Statement and Task Floor run predicate over bundle subjects |
| OPA | Structured policy input and expected decision contract |
| BrowserGym | Cartridge registration and evaluator descriptor |
| CloudEvents | Portable event envelopes for trajectory events |
| AgentRx | Canonical trajectory and invariant-analysis input |
| Cua | Computer-use trajectory record and artifact references |
| Cedar | Principal, action, resource, context, and entity input |
| LangGraph | Checkpoint, interrupt, resume, and idempotency descriptor |

An adapter should preserve canonical identities in extension fields instead of translating them away.

## Claim language

A public capability claim should use this form:

```text
Task Floor TF<N> verified
report_sha256: <digest>
bundle_sha256: <digest>
claim_scope: <bounded workload and environment>
```

“Compatible,” “supports approvals,” “safe,” “production ready,” and similar statements are not Task Floor claims unless a conformance report identifies the exact profile, bundle, scope, and evidence.

## Failure defaults

The reference floor is fail-closed. Unknown schema versions, stale state, missing approval, duplicate non-idempotent work, unresolved identity, absent artifacts, failed postconditions, incomplete handoff, broken hashes, unsupported compensation, expired takeover, and overclaimed profiles hold or deny execution.

## Versioning

Task Floor v1 uses namespaced schema identifiers and explicit interface versions. Backward-compatible additions use optional fields. A change that alters hashing, required semantics, effect meaning, or admission rules requires a new schema identifier. Extension namespaces must not redefine core effects or authorities.
