"""Typed data model for the AXM Estate Lab.

The model separates five objects that must not collapse into one another:

* an organ, which owns a bounded function and authority membrane;
* an adapter, which exposes one source or receiver surface;
* a route, which connects adapters under explicit evidence and cost terms;
* a semantic action, which states what is requested independently of embodiment;
* a scenario, which defines what the laboratory must prove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

EvidenceClass = Literal["confirmed", "measured", "reported", "derived", "judgment", "open"]
RouteStatus = Literal["available", "degraded", "unavailable"]
ScenarioKind = Literal["equivalence", "sequence"]

EVIDENCE_RANK: dict[str, int] = {
    "open": 0,
    "judgment": 1,
    "reported": 2,
    "derived": 3,
    "measured": 4,
    "confirmed": 5,
}


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    profile: str
    command: tuple[str, ...]
    timeout_seconds: int = 120
    expected_exit_codes: tuple[int, ...] = (0,)
    evidence_class: EvidenceClass = "measured"
    required_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrganSpec:
    organ_id: str
    repository: str
    local_names: tuple[str, ...]
    function: str
    owns: tuple[str, ...]
    refuses: tuple[str, ...]
    capabilities: tuple[str, ...]
    probes: tuple[ProbeSpec, ...] = ()


@dataclass(frozen=True)
class AdapterSpec:
    adapter_id: str
    organ_id: str
    kind: str
    mode: Literal["synthetic", "command", "artifact", "human"]
    capabilities: tuple[str, ...]
    local_only: bool
    deterministic: bool
    replayable: bool
    evidence_class: EvidenceClass
    default_status: RouteStatus = "available"
    command: tuple[str, ...] = ()
    timeout_seconds: int = 30
    notes: str = ""


@dataclass(frozen=True)
class RouteMetrics:
    evidence: int
    determinism: int
    replayability: int
    locality: int
    latency_ms: int
    cost_microunits: int
    fragility: int
    authority_risk: int


@dataclass(frozen=True)
class RouteSpec:
    route_id: str
    source_adapter: str
    target_adapter: str
    action_prefixes: tuple[str, ...]
    required_role: str
    required_mandate: str
    tags: tuple[str, ...]
    metrics: RouteMetrics
    fallback_route_ids: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class RoutingPolicy:
    minimum_evidence: int = 2
    require_determinism: bool = True
    require_replayability: bool = True
    prefer_local: bool = True
    weights: dict[str, int] = field(
        default_factory=lambda: {
            "evidence": 100,
            "determinism": 45,
            "replayability": 40,
            "locality": 20,
            "latency_ms": -1,
            "cost_microunits": -2,
            "fragility": -35,
            "authority_risk": -60,
        }
    )


@dataclass(frozen=True)
class EstateManifest:
    format: str
    estate_id: str
    organs: dict[str, OrganSpec]
    adapters: dict[str, AdapterSpec]
    routes: dict[str, RouteSpec]
    policy: RoutingPolicy
    source_path: Path
    raw: dict[str, Any]


@dataclass(frozen=True)
class AuthorityClaim:
    actor: str
    role: str
    mandate: str
    ownership_epoch: int


@dataclass(frozen=True)
class SemanticAction:
    step_id: str
    semantic_id: str
    subject: str
    operation: Literal["set", "increment", "append", "remove", "toggle"]
    state_path: str
    value: Any
    required_role: str
    required_mandate: str
    authority: AuthorityClaim
    route_ids: tuple[str, ...]
    route_query: dict[str, Any]
    expected: dict[str, Any]
    projection: dict[str, Any]


@dataclass(frozen=True)
class FaultTrial:
    trial_id: str
    fault: str
    route_id: str | None
    expected_outcome: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class RoutingTrial:
    trial_id: str
    action_prefix: str
    candidate_route_ids: tuple[str, ...]
    unavailable_route_ids: tuple[str, ...]
    constraints: dict[str, Any]
    expected_route_id: str | None
    expected_outcome: str


@dataclass(frozen=True)
class ScenarioSpec:
    format: str
    scenario_id: str
    title: str
    kind: ScenarioKind
    objective: str
    initial_state: dict[str, Any]
    actions: tuple[SemanticAction, ...]
    equivalence_route_ids: tuple[str, ...]
    expected_final_state: dict[str, Any]
    routing_trials: tuple[RoutingTrial, ...]
    fault_trials: tuple[FaultTrial, ...]
    invariants: tuple[str, ...]
    source_path: Path
    raw: dict[str, Any]


@dataclass(frozen=True)
class ProbeResult:
    organ_id: str
    probe_id: str
    status: Literal["passed", "failed", "skipped", "missing"]
    evidence_class: EvidenceClass
    exit_code: int | None
    duration_ms: int
    stdout_sha256: str | None
    stderr_sha256: str | None
    reason: str | None


@dataclass(frozen=True)
class RouteEvaluation:
    route_id: str
    eligible: bool
    score: int | None
    refusal_reasons: tuple[str, ...]
    metrics: RouteMetrics


@dataclass(frozen=True)
class RouteDecision:
    route_id: str
    score: int
    evaluations: tuple[RouteEvaluation, ...]


@dataclass(frozen=True)
class StepOutcome:
    step_id: str
    route_id: str
    outcome: Literal["committed", "refused", "faulted", "duplicate"]
    reason: str | None
    event_id: str | None
    state_before_hash: str
    state_after_hash: str
    output_hash: str | None
    debrief_hash: str | None
    route_score: int | None
    details: dict[str, Any]


@dataclass(frozen=True)
class ScenarioOutcome:
    scenario_id: str
    status: Literal["passed", "failed", "refused"]
    kind: ScenarioKind
    run_id: str
    manifest_id: str
    scenario_digest: str
    final_state_hash: str
    steps: tuple[StepOutcome, ...]
    routing_trials: tuple[dict[str, Any], ...]
    fault_trials: tuple[dict[str, Any], ...]
    equivalence: dict[str, Any]
    failures: tuple[str, ...]
    receipt_dir: Path | None = None
