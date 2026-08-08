# Task Floor ecosystem gap map

## Method

The machine-readable registry in `experiments/task_floor/oss_registry.json` surveys representative transport protocols, agent and UI protocols, policy and identity systems, provenance and telemetry standards, durable execution frameworks, browser and computer-use runtimes, benchmark environments, trajectory analysis systems, adversarial testbeds, and skill repositories. Coverage is recorded conservatively as `documented`, `partial`, `not_core`, or `not_assessed`, with primary sources attached to every entry.

The registry is not a league table. A low score often means that a project is correctly scoped to one layer. OPA should not be penalized for lacking a browser runtime, and OpenTelemetry should not be expected to enforce approvals. The point is to identify the contracts that disappear when separately useful layers are composed.

## The 26 Task Floor axes

### State, effects, and execution

1. `state_binding`
2. `effect_enforcement`
3. `approval_portability`
4. `idempotency_transactions`
5. `rollback_compensation`
6. `counterfactual_replay`

### Authority, identity, and custody

7. `authority_quorum`
8. `credential_custody`
9. `workload_identity`
10. `human_takeover_receipt`
11. `local_distributed_custody`

### Acceptance and project consequence

12. `external_acceptance`
13. `project_handoff`
14. `claim_verification`
15. `accepted_work_economics`

### Evidence, privacy, and supply chain

16. `artifact_provenance`
17. `retention_privacy`
18. `environment_reproducibility`
19. `skill_supply_chain`
20. `success_compilation`

### Surface and trajectory interoperability

21. `semantic_visual_route`
22. `backend_portability`
23. `trajectory_interchange`
24. `version_negotiation`

### Security and diagnosis

25. `mutation_security`
26. `failure_taxonomy`

## Current critical gaps

The generated gap report identifies five axes with no surveyed system documenting the complete contract:

- Portable approval bound to exact state and action
- Typed project handoff after externally accepted work
- Machine-readable retention, deletion, redaction, classification, and secret exclusion
- Rollback or compensation for partial and irreversible effects
- Exact state binding with stale-action rejection across backend boundaries

Five additional axes have only one documented implementation among the surveyed projects and therefore remain high-risk composition points:

- Accepted-work economics
- Authority quorum
- Counterfactual replay
- Idempotency and transaction semantics
- Skill supply chain

The generated report is `experiments/task_floor/gap_report.json`. It contains the counts, documented systems, partial systems, and conservative weighted coverage for all 21 registry entries.

## Why existing standards are complements

MCP transports tools, context, elicitation, and tasks. A2A transports agent identity, skills, tasks, artifacts, and extensions. AG-UI transports typed frontend and human-interaction events. OpenTelemetry carries traces and metrics. OPA and Cedar evaluate policy. SPIFFE identifies workloads. in-toto and SLSA attest provenance. LangGraph provides durable checkpoints and interrupts. BrowserGym and Cua provide environments, actions, and trajectories. AgentRx diagnoses failures.

The composition gap appears between them. None of those layers alone guarantees that an A2A task was planned against the exact AG-UI state, that an MCP tool annotation accurately described its effect, that the OPA decision was bound to the same content-addressed action, that the executor applied it once, that an independent acceptor verified the postcondition, and that the in-toto statement covers the same artifacts and project handoff.

Task Floor supplies that join.

## Frontier gaps beyond the v1 profiles

`experiments/task_floor/frontier_gaps.json` tracks candidate requirements that should enter a future profile after implementer experience and public review:

- Continuous credential and session revocation through shared security signals
- Attenuated delegated tokens and impersonation versus delegation semantics
- Enforced budgets for time, money, tokens, GPU, energy, network, and action count
- Emergency-stop broadcast across planner, critic, executor, and UI processes
- Multi-tenant isolation and cross-task data-leak prevention
- Protocol downgrade resistance across version and adapter negotiation
- Data residency and jurisdictional storage controls
- Trusted time for expiry, lease, ordering, and non-repudiation
- Accessibility equivalence between semantic and visual routes
- Evaluation isolation and benchmark-contamination controls

These candidates are published now so that adapters do not hard-code assumptions that would make them impossible later.
