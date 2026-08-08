"""Evidence-backed conformance and OSS gap assessment for Task Floor.

The conformance report distinguishes declared capability from observed evidence.
Transport protocols, agent cards, policy engines, and telemetry exports are useful
inputs, but a profile passes only when the canonical bundle contains the required
state, authority, effect, acceptance, and provenance evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from .playwright_computer_common import PlaywrightComputerError, hash_json, without_hash
from .task_floor_export import verify_bundle
from .task_floor_protocol import (
    CONFORMANCE_SCHEMA,
    PROFILE_ORDER,
    PROFILE_REQUIREMENTS,
    PROFILE_TITLES,
    REGISTRY_SCHEMA,
    validate_manifest,
)

COVERAGE_STATES = {"documented", "partial", "not_core", "not_assessed"}
GAP_DEFINITIONS = {
    "state_binding": (
        "Actions bind the exact observed state and stale proposals fail before execution."
    ),
    "effect_enforcement": (
        "Effects are declared at action and argument scope, enforced by a trusted host, "
        "and retained in receipts."
    ),
    "approval_portability": (
        "Approval is a portable state-and-action-bound object rather than a UI-local boolean."
    ),
    "idempotency_transactions": (
        "Retries are keyed, duplicate effects are prevented, and transactional boundaries are explicit."
    ),
    "rollback_compensation": (
        "Irreversible or partially completed effects declare rollback or compensation behavior."
    ),
    "authority_quorum": (
        "Planner, critic, policy, executor, acceptor, credential custodian, and human authority remain separable."
    ),
    "external_acceptance": (
        "Completion is decided by an authority independent of the planner and executor."
    ),
    "project_handoff": (
        "A successful run emits a typed derivative artifact for the owning project."
    ),
    "human_takeover_receipt": (
        "Human intervention is a state-bound lease with pause, release, and re-observation."
    ),
    "credential_custody": (
        "Authenticated state and secrets remain under a declared custodian, delegation scope, and lease."
    ),
    "workload_identity": (
        "Runtime actors can prove workload identity and on-behalf-of delegation independently of model text."
    ),
    "semantic_visual_route": (
        "Semantic, accessibility, visual, API, workspace, terminal, and human routes remain explicit."
    ),
    "artifact_provenance": (
        "Inputs, outputs, traces, handoffs, models, policies, and skills are content-addressed and attestable."
    ),
    "retention_privacy": (
        "Data classification, redaction, retention, deletion, and secret exclusion are machine-readable."
    ),
    "mutation_security": (
        "Conformance includes reordered, delayed, adversarial, prompt-injected, and deceptive variants."
    ),
    "failure_taxonomy": (
        "Failures are classified across planning, observation, policy, approval, execution, environment, acceptance, and verification."
    ),
    "counterfactual_replay": (
        "A trajectory can be replayed or forked from content-addressed checkpoints without silently repeating effects."
    ),
    "environment_reproducibility": (
        "Browser, OS, model, policy, dependency, and fixture identities are sufficient to reproduce or explain a run."
    ),
    "version_negotiation": (
        "Schemas and interfaces declare versions, compatibility, extensions, and deprecation behavior."
    ),
    "claim_verification": (
        "Capability and production claims cannot exceed independently verified conformance evidence."
    ),
    "backend_portability": (
        "The task and acceptance contract survive replacement of agent, browser, sandbox, and policy backends."
    ),
    "trajectory_interchange": (
        "A canonical trajectory can feed diagnosis, telemetry, replay, evaluation, and benchmark tools."
    ),
    "accepted_work_economics": (
        "Cost, tokens, GPU time, human time, actions, and energy are normalized per externally accepted task."
    ),
    "local_distributed_custody": (
        "Remote planners and critics can propose without acquiring executor, browser-profile, or secret authority."
    ),
    "skill_supply_chain": (
        "Learned skills and successful programs have source, review, signatures, compatibility, tests, and rollback."
    ),
    "success_compilation": (
        "Accepted trajectories can compile into reusable deterministic skills or programs with retained provenance."
    ),
}

FAILURE_CATEGORIES = {
    "planning",
    "observation",
    "target_resolution",
    "policy",
    "approval",
    "execution",
    "environment",
    "credential",
    "network",
    "acceptance",
    "verification",
    "timeout",
    "human",
    "execution_or_acceptance",
    "unknown",
}


def _check(
    rows: list[dict[str, Any]],
    check_id: str,
    profile: str,
    passed: bool,
    *,
    evidence: Any = None,
    error: str | None = None,
) -> None:
    rows.append(
        {
            "id": check_id,
            "profile": profile,
            "pass": bool(passed),
            "evidence": evidence,
            "error": error,
        }
    )


def _events(bundle: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        row
        for row in bundle.get("trajectory", {}).get("events", [])
        if row.get("kind") == kind
    ]


def _step_map(bundle: dict[str, Any]) -> dict[int, dict[str, list[dict[str, Any]]]]:
    result: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for event in bundle.get("trajectory", {}).get("events", []):
        step = event.get("step_number")
        if step is not None:
            result[int(step)][str(event.get("kind"))].append(event)
    return result


def _actions(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for event in _events(bundle, "planner.proposal"):
        for action in event.get("data", {}).get("actions", []):
            if isinstance(action, dict):
                actions.append(
                    {
                        **action,
                        "step_number": event.get("step_number"),
                        "state_id": event.get("data", {}).get("state_id"),
                    }
                )
    return actions


def _executed(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [event.get("data", {}) for event in _events(bundle, "action.executed")]


def _browser_receipts(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        receipt
        for data in _executed(bundle)
        for receipt in [data.get("browser_receipt")]
        if isinstance(receipt, dict)
    ]


def _secret_artifact_paths(bundle: dict[str, Any]) -> list[str]:
    return [
        str(row.get("path"))
        for row in bundle.get("artifacts", [])
        if "secrets" in {part.casefold() for part in str(row.get("path", "")).split("/")}
    ]


def _approval_evidence(
    bundle: dict[str, Any], governed_effects: set[str]
) -> tuple[bool, list[dict[str, Any]]]:
    by_step: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for data in _executed(bundle):
        by_step[int(data.get("result", {}).get("action", {}).get("step_number", 0) or 0)].append(data)
    rows: list[dict[str, Any]] = []
    all_ok = True
    executed_events = _events(bundle, "action.executed")
    for action in _actions(bundle):
        effect = action.get("effect")
        if effect not in governed_effects:
            continue
        step = int(action.get("step_number") or 0)
        action_id = action.get("id")
        candidates = [
            event.get("data", {})
            for event in executed_events
            if int(event.get("step_number") or 0) == step
            and (event.get("data", {}).get("action") or {}).get("id") == action_id
        ]
        admitted = False
        evidence: dict[str, Any] = {
            "step_number": step,
            "action_id": action_id,
            "effect": effect,
        }
        for candidate in candidates:
            receipt = candidate.get("browser_receipt")
            if isinstance(receipt, dict):
                evidence["receipt_sha256"] = receipt.get("receipt_sha256")
                evidence["approval_present"] = receipt.get("approval_present")
                evidence["approval_required"] = receipt.get("approval_required")
                admitted = bool(receipt.get("approval_present"))
            result = candidate.get("result")
            if isinstance(result, dict):
                takeover = result.get("takeover") or result.get("release")
                if takeover:
                    admitted = True
                    evidence["human_lease"] = takeover
        if not candidates:
            evidence["error"] = "governed action was proposed but no matching execution exists"
        if not admitted:
            all_ok = False
            evidence.setdefault("error", "governed action lacks portable or receipt-backed approval evidence")
        rows.append(evidence)
    return all_ok, rows


def _profile_results(checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for profile in PROFILE_ORDER:
        required = set(PROFILE_REQUIREMENTS[profile])
        rows = [row for row in checks if row["id"] in required]
        missing = sorted(required - {row["id"] for row in rows})
        profiles[profile] = {
            "title": PROFILE_TITLES[profile],
            "pass": not missing and all(row["pass"] for row in rows),
            "missing_requirements": missing,
            "checks": rows,
        }
    return profiles


def _highest_contiguous(profiles: dict[str, dict[str, Any]]) -> str | None:
    highest: str | None = None
    for profile in PROFILE_ORDER:
        if profiles[profile]["pass"]:
            highest = profile
        else:
            break
    return highest


def assess_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    bundle_errors = verify_bundle(bundle)
    manifest = bundle.get("manifest", {}) if isinstance(bundle, dict) else {}
    cartridge = bundle.get("cartridge", {}) if isinstance(bundle, dict) else {}
    _check(
        checks,
        "manifest.valid",
        "TF0",
        not bundle_errors,
        evidence={"bundle_sha256": bundle.get("bundle_sha256") if isinstance(bundle, dict) else None},
        error="; ".join(bundle_errors) if bundle_errors else None,
    )
    interfaces = manifest.get("interfaces", []) if isinstance(manifest, dict) else []
    _check(
        checks,
        "interface.declared",
        "TF0",
        bool(interfaces),
        evidence=[row.get("protocol") for row in interfaces if isinstance(row, dict)],
        error=None if interfaces else "no interfaces declared",
    )
    artifact_rows = bundle.get("artifacts", []) if isinstance(bundle, dict) else []
    artifact_digests = bool(artifact_rows) and all(
        isinstance(row, dict)
        and len(str(row.get("digest", {}).get("sha256", ""))) == 64
        for row in artifact_rows
    )
    _check(
        checks,
        "evidence.sha256",
        "TF0",
        artifact_digests,
        evidence={"artifact_count": len(artifact_rows)},
    )

    steps = _step_map(bundle)
    state_ids: list[str] = []
    state_binding_errors: list[str] = []
    receipt_evidence = 0
    for step_number, events in sorted(steps.items()):
        started = events.get("step.started", [])
        finished = events.get("step.finished", [])
        proposals = events.get("planner.proposal", [])
        executed = events.get("action.executed", [])
        if len(started) != 1 or len(finished) != 1 or len(proposals) != 1:
            state_binding_errors.append(
                f"step {step_number} lacks one started, proposal, and finished event"
            )
            continue
        start_id = str(started[0].get("data", {}).get("state_id", ""))
        finish_id = str(finished[0].get("data", {}).get("state_id", ""))
        proposal_state = str(proposals[0].get("data", {}).get("state_id", ""))
        state_ids.extend([start_id, finish_id])
        if proposal_state and proposal_state != start_id:
            state_binding_errors.append(
                f"step {step_number} proposal binds {proposal_state}, expected {start_id}"
            )
        for event in executed:
            data = event.get("data", {})
            receipt = data.get("browser_receipt")
            candidate = data.get("candidate")
            result = data.get("result")
            if isinstance(receipt, dict):
                receipt_evidence += 1
                if receipt.get("started_state_id") != start_id:
                    state_binding_errors.append(
                        f"step {step_number} browser receipt starts from another state"
                    )
            elif isinstance(candidate, dict):
                receipt_evidence += 1
                if candidate.get("state_id") != start_id:
                    state_binding_errors.append(
                        f"step {step_number} visual candidate binds another state"
                    )
            elif isinstance(result, dict):
                receipt_evidence += 1
            else:
                state_binding_errors.append(
                    f"step {step_number} action has no execution receipt or result"
                )
            completed = data.get("completed_state_id")
            if completed and completed != finish_id:
                state_binding_errors.append(
                    f"step {step_number} action result and finished state differ"
                )
    content_addressed = bool(state_ids) and all(len(value) == 64 for value in state_ids)
    _check(
        checks,
        "state.content_addressed",
        "TF1",
        content_addressed,
        evidence={"states": state_ids},
    )
    binding_ok = bool(steps) and not state_binding_errors
    _check(
        checks,
        "state.action_binding",
        "TF1",
        binding_ok,
        evidence={"steps": len(steps), "errors": state_binding_errors},
        error="; ".join(state_binding_errors) if state_binding_errors else None,
    )
    _check(
        checks,
        "evidence.action_receipts",
        "TF1",
        receipt_evidence == len(_events(bundle, "action.executed")) and receipt_evidence > 0,
        evidence={
            "actions": len(_events(bundle, "action.executed")),
            "receipt_backed": receipt_evidence,
        },
    )
    optimistic = bool(manifest.get("state", {}).get("exact_action_binding")) and bool(
        manifest.get("state", {}).get("conflict_detection")
    ) and binding_ok
    _check(
        checks,
        "execution.optimistic_concurrency",
        "TF1",
        optimistic,
        evidence={
            "exact_action_binding": manifest.get("state", {}).get("exact_action_binding"),
            "conflict_detection": manifest.get("state", {}).get("conflict_detection"),
        },
    )

    actions = _actions(bundle)
    declared = bool(actions) and all(action.get("effect") for action in actions)
    _check(
        checks,
        "effects.declared",
        "TF2",
        declared and bool(manifest.get("effects", {}).get("declared")),
        evidence=dict(Counter(str(action.get("effect")) for action in actions)),
    )
    verdicts = _events(bundle, "critic.verdict")
    enforced = (
        bool(verdicts)
        and all(row.get("data", {}).get("pass") is True for row in verdicts)
        and bool(manifest.get("effects", {}).get("enforced"))
    )
    _check(
        checks,
        "effects.enforced",
        "TF2",
        enforced,
        evidence={"verdicts": len(verdicts)},
    )
    governed = set(cartridge.get("effect_policy", {}).get("approval_effects", []))
    approvals_ok, approval_rows = _approval_evidence(bundle, governed)
    _check(
        checks,
        "effects.approval",
        "TF2",
        bool(manifest.get("effects", {}).get("approval")) and approvals_ok,
        evidence=approval_rows,
        error=(
            None
            if approvals_ok
            else "one or more approval-governed actions lack approval evidence"
        ),
    )
    authority = manifest.get("authority", {})
    executor = set(authority.get("executor", []))
    acceptor = set(authority.get("acceptor", []))
    separated = bool(executor) and bool(acceptor) and executor.isdisjoint(acceptor)
    _check(
        checks,
        "authority.executor_separated",
        "TF2",
        separated,
        evidence={"executor": sorted(executor), "acceptor": sorted(acceptor)},
        error=None if separated else "executor and acceptor authority overlap",
    )
    idempotency_keys = [
        str(event.get("data", {}).get("idempotency_key", ""))
        for event in _events(bundle, "action.executed")
    ]
    idempotent = (
        bool(idempotency_keys)
        and all(idempotency_keys)
        and len(idempotency_keys) == len(set(idempotency_keys))
        and bool(manifest.get("execution", {}).get("idempotency_keys"))
    )
    _check(
        checks,
        "execution.idempotency",
        "TF2",
        idempotent,
        evidence={"keys": idempotency_keys},
    )

    acceptance = bundle.get("acceptance", [])
    acceptance_pass = (
        bool(acceptance)
        and all(row.get("pass") is True for row in acceptance if isinstance(row, dict))
        and bundle.get("run", {}).get("status") == "ACCEPTED"
        and bool(manifest.get("acceptance", {}).get("external_verifier"))
    )
    _check(
        checks,
        "acceptance.external_verifier",
        "TF3",
        acceptance_pass,
        evidence={"checks": len(acceptance), "status": bundle.get("run", {}).get("status")},
    )
    handoff = bundle.get("project_handoff", {})
    handoff_ok = isinstance(handoff, dict) and len(str(handoff.get("handoff_sha256", ""))) == 64
    _check(
        checks,
        "acceptance.project_handoff",
        "TF3",
        handoff_ok and bool(manifest.get("acceptance", {}).get("project_handoff")),
        evidence={"handoff_sha256": handoff.get("handoff_sha256") if isinstance(handoff, dict) else None},
    )
    postconditions = (
        acceptance_pass
        and bool(manifest.get("acceptance", {}).get("postconditions"))
        and bool(manifest.get("effects", {}).get("postconditions"))
    )
    _check(
        checks,
        "acceptance.postconditions",
        "TF3",
        postconditions,
        evidence={"checks": acceptance},
    )
    _check(
        checks,
        "evidence.artifact_hashes",
        "TF3",
        artifact_digests and bool(manifest.get("evidence", {}).get("artifact_hashes")),
        evidence={"artifacts": len(artifact_rows)},
    )

    _check(
        checks,
        "lifecycle.human_takeover",
        "TF4",
        bool(manifest.get("lifecycle", {}).get("human_takeover")),
        evidence=manifest.get("lifecycle", {}),
    )
    _check(
        checks,
        "lifecycle.resume",
        "TF4",
        bool(manifest.get("lifecycle", {}).get("resume")),
        evidence=manifest.get("lifecycle", {}),
    )
    secret_paths = _secret_artifact_paths(bundle)
    _check(
        checks,
        "security.secrets_isolated",
        "TF4",
        bool(manifest.get("security", {}).get("secrets_isolated"))
        and bool(manifest.get("privacy", {}).get("secret_exclusion"))
        and not secret_paths,
        evidence={"secret_artifacts": secret_paths},
        error=None if not secret_paths else "secret paths leaked into bundle artifacts",
    )
    _check(
        checks,
        "security.credential_lease",
        "TF4",
        bool(manifest.get("security", {}).get("credential_lease")),
        evidence=manifest.get("security", {}),
    )
    _check(
        checks,
        "security.network_policy",
        "TF4",
        bool(manifest.get("security", {}).get("network_policy")),
        evidence=manifest.get("security", {}),
    )
    delegated = (
        bool(manifest.get("identity", {}).get("agent_delegation"))
        and bool(authority.get("planner"))
        and bool(authority.get("executor"))
        and set(authority.get("planner", [])).isdisjoint(set(authority.get("executor", [])))
    )
    _check(
        checks,
        "identity.delegation",
        "TF4",
        delegated,
        evidence={
            "planner": authority.get("planner", []),
            "executor": authority.get("executor", []),
        },
    )

    exports = bundle.get("exports", {})
    export_requirements = (
        ("mcp", "interop.mcp"),
        ("a2a", "interop.a2a"),
        ("ag-ui", "interop.ag-ui"),
        ("opentelemetry", "interop.opentelemetry"),
        ("in-toto", "interop.in-toto"),
        ("opa", "interop.opa"),
        ("cloudevents", "interop.cloudevents"),
    )
    for key, requirement in export_requirements:
        value = exports.get(key)
        passed = (
            isinstance(value, dict)
            and len(str(value.get("export_sha256", ""))) == 64
            and bool(manifest.get("interop", {}).get(key))
        )
        _check(
            checks,
            requirement,
            "TF5",
            passed,
            evidence={
                "export": key,
                "export_sha256": value.get("export_sha256") if isinstance(value, dict) else None,
            },
            error=None if passed else f"{key} export or manifest declaration is missing",
        )

    mutations = cartridge.get("mutation_dimensions", [])
    _check(
        checks,
        "resilience.mutation_suite",
        "TF6",
        bool(mutations) and bool(manifest.get("resilience", {}).get("mutation_suite")),
        evidence={"mutation_dimensions": mutations},
    )
    _check(
        checks,
        "resilience.prompt_injection_tests",
        "TF6",
        bool(manifest.get("resilience", {}).get("prompt_injection_tests"))
        and bool(manifest.get("security", {}).get("prompt_injection_boundary")),
        evidence={
            "resilience": manifest.get("resilience", {}),
            "security": manifest.get("security", {}),
        },
    )
    failure_category = bundle.get("metrics", {}).get("failure_category")
    failure_taxonomy = bool(manifest.get("diagnostics", {}).get("failure_taxonomy")) and (
        failure_category is None or failure_category in FAILURE_CATEGORIES
    )
    _check(
        checks,
        "diagnostics.failure_taxonomy",
        "TF6",
        failure_taxonomy,
        evidence={"failure_category": failure_category},
    )
    replayable = (
        bool(manifest.get("diagnostics", {}).get("counterfactual_replay"))
        and bool(manifest.get("state", {}).get("replay"))
        and bool(bundle.get("trajectory", {}).get("event_head_sha256"))
        and idempotent
    )
    _check(
        checks,
        "diagnostics.counterfactual_replay",
        "TF6",
        replayable,
        evidence={
            "event_head_sha256": bundle.get("trajectory", {}).get("event_head_sha256"),
            "idempotent": idempotent,
        },
    )
    compensable = bool(manifest.get("execution", {}).get("compensation")) and all(
        action.get("effect") not in {"destructive", "financial", "external_write"}
        or action.get("compensation")
        for action in actions
    )
    _check(
        checks,
        "execution.compensation",
        "TF6",
        compensable,
        evidence={
            "declared": manifest.get("execution", {}).get("compensation"),
            "governed_actions": [
                {
                    "id": action.get("id"),
                    "effect": action.get("effect"),
                    "compensation": action.get("compensation"),
                }
                for action in actions
                if action.get("effect") in {"destructive", "financial", "external_write"}
            ],
        },
    )
    _check(
        checks,
        "privacy.redaction",
        "TF6",
        bool(manifest.get("privacy", {}).get("redaction")) and not secret_paths,
        evidence={"secret_artifacts": secret_paths},
    )

    preliminary = _profile_results(checks)
    preliminary_highest = _highest_contiguous(preliminary)
    claimed = list(manifest.get("conformance", {}).get("profiles_claimed", []))
    passed_before_tf7 = {
        profile for profile in PROFILE_ORDER if profile != "TF7" and preliminary[profile]["pass"]
    }
    overclaimed = sorted(set(claimed) - passed_before_tf7)
    claims_verified = (
        bool(manifest.get("diagnostics", {}).get("claim_verification"))
        and not overclaimed
        and bool(manifest.get("conformance", {}).get("claim_scope"))
    )
    _check(
        checks,
        "conformance.claim_verification",
        "TF7",
        claims_verified,
        evidence={
            "claimed": claimed,
            "passed_before_tf7": sorted(passed_before_tf7),
            "overclaimed": overclaimed,
            "preliminary_highest": preliminary_highest,
        },
        error=(
            None
            if claims_verified
            else f"manifest overclaims profiles or lacks claim verification: {overclaimed}"
        ),
    )
    _check(
        checks,
        "identity.workload_attestation",
        "TF7",
        bool(manifest.get("identity", {}).get("workload_identity"))
        and bool(manifest.get("identity", {}).get("runtime_attestation")),
        evidence=manifest.get("identity", {}),
    )
    _check(
        checks,
        "evidence.signatures",
        "TF7",
        bool(manifest.get("evidence", {}).get("signatures"))
        and bool(manifest.get("identity", {}).get("signed_messages")),
        evidence={
            "evidence": manifest.get("evidence", {}),
            "identity": manifest.get("identity", {}),
        },
    )
    _check(
        checks,
        "supply_chain.reproducible_environment",
        "TF7",
        bool(manifest.get("supply_chain", {}).get("reproducible_environment"))
        and bool(manifest.get("supply_chain", {}).get("dependency_inventory"))
        and bool(manifest.get("supply_chain", {}).get("model_runtime_identity")),
        evidence=manifest.get("supply_chain", {}),
    )
    _check(
        checks,
        "privacy.retention",
        "TF7",
        bool(manifest.get("privacy", {}).get("retention"))
        and bool(manifest.get("privacy", {}).get("data_classification")),
        evidence=manifest.get("privacy", {}),
    )
    _check(
        checks,
        "versioning.negotiation",
        "TF7",
        bool(manifest.get("versioning", {}).get("schema_negotiation"))
        and bool(manifest.get("versioning", {}).get("deprecation_policy")),
        evidence=manifest.get("versioning", {}),
    )
    pre_production_profiles = _profile_results(checks)
    production = (
        bool(manifest.get("conformance", {}).get("production_qualified"))
        and all(pre_production_profiles[profile]["pass"] for profile in PROFILE_ORDER[:-1])
        and not overclaimed
    )
    _check(
        checks,
        "production.qualified",
        "TF7",
        production,
        evidence={
            "declared": manifest.get("conformance", {}).get("production_qualified"),
            "lower_profiles_pass": {
                profile: pre_production_profiles[profile]["pass"]
                for profile in PROFILE_ORDER[:-1]
            },
        },
        error=None if production else "production qualification is absent or unsupported",
    )

    profiles = _profile_results(checks)
    highest = _highest_contiguous(profiles)
    report = {
        "schema": CONFORMANCE_SCHEMA,
        "kind": "bundle",
        "bundle_sha256": bundle.get("bundle_sha256"),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "profiles": profiles,
        "highest_contiguous_profile": highest,
        "passed": all(row["pass"] for row in checks),
        "checks": checks,
        "claims": {
            "claimed_profiles": claimed,
            "overclaimed_profiles": overclaimed,
            "verified": claims_verified,
            "production_qualified": production,
        },
    }
    report["report_sha256"] = hash_json(report)
    return report


def validate_registry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != REGISTRY_SCHEMA:
        raise PlaywrightComputerError(f"registry.schema must be {REGISTRY_SCHEMA}")
    axes = raw.get("axes")
    entries = raw.get("entries")
    if not isinstance(axes, dict) or not axes:
        raise PlaywrightComputerError("registry.axes must be a non-empty object")
    if not isinstance(entries, list) or not entries:
        raise PlaywrightComputerError("registry.entries must be a non-empty array")
    unknown_axes = set(axes) - set(GAP_DEFINITIONS)
    if unknown_axes:
        raise PlaywrightComputerError(
            f"registry has unknown axes: {sorted(unknown_axes)}"
        )
    missing_axes = set(GAP_DEFINITIONS) - set(axes)
    if missing_axes:
        raise PlaywrightComputerError(
            f"registry omits Task Floor axes: {sorted(missing_axes)}"
        )
    normalized_entries: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise PlaywrightComputerError(f"registry.entries[{index}] must be an object")
        identifier = str(entry.get("id", "")).strip()
        if not identifier or identifier in ids:
            raise PlaywrightComputerError(
                f"registry.entries[{index}].id must be unique and non-empty"
            )
        ids.add(identifier)
        coverage = entry.get("coverage")
        if not isinstance(coverage, dict):
            raise PlaywrightComputerError(
                f"registry.entries[{index}].coverage must be an object"
            )
        normalized_coverage: dict[str, str] = {}
        for axis in axes:
            status = coverage.get(axis, "not_assessed")
            if status not in COVERAGE_STATES:
                raise PlaywrightComputerError(
                    f"registry entry {identifier} axis {axis} must be one of {sorted(COVERAGE_STATES)}"
                )
            normalized_coverage[axis] = status
        sources = entry.get("sources", [])
        if not isinstance(sources, list) or not sources:
            raise PlaywrightComputerError(
                f"registry entry {identifier} must include primary sources"
            )
        normalized_entries.append(
            {
                **deepcopy(entry),
                "id": identifier,
                "sources": sources,
                "coverage": normalized_coverage,
            }
        )
    value = {
        "schema": REGISTRY_SCHEMA,
        "last_reviewed": raw.get("last_reviewed"),
        "method": raw.get("method"),
        "coverage_states": deepcopy(raw.get("coverage_states", {})),
        "axes": {axis: str(description) for axis, description in axes.items()},
        "entries": sorted(normalized_entries, key=lambda row: row["id"]),
    }
    value["registry_sha256"] = hash_json(value)
    observed = raw.get("registry_sha256")
    if observed is not None and observed != value["registry_sha256"]:
        raise PlaywrightComputerError("registry.registry_sha256 does not verify")
    return value


def gap_report(raw_registry: Any) -> dict[str, Any]:
    registry = validate_registry(raw_registry)
    gaps: list[dict[str, Any]] = []
    for axis, description in registry["axes"].items():
        counts = Counter(entry["coverage"][axis] for entry in registry["entries"])
        documented = [
            entry["id"]
            for entry in registry["entries"]
            if entry["coverage"][axis] == "documented"
        ]
        partial = [
            entry["id"]
            for entry in registry["entries"]
            if entry["coverage"][axis] == "partial"
        ]
        priority = "critical" if not documented else "high" if len(documented) == 1 else "normal"
        gaps.append(
            {
                "id": axis,
                "description": description,
                "priority": priority,
                "counts": dict(sorted(counts.items())),
                "documented_by": documented,
                "partial_by": partial,
                "task_floor_contract": True,
            }
        )
    gaps.sort(
        key=lambda row: (
            {"critical": 0, "high": 1, "normal": 2}[row["priority"]],
            row["id"],
        )
    )
    system_scores = []
    for entry in registry["entries"]:
        documented = sum(
            status == "documented" for status in entry["coverage"].values()
        )
        partial = sum(status == "partial" for status in entry["coverage"].values())
        score = documented + 0.5 * partial
        system_scores.append(
            {
                "id": entry["id"],
                "documented": documented,
                "partial": partial,
                "score": score,
                "max_score": len(registry["axes"]),
            }
        )
    system_scores.sort(key=lambda row: (-row["score"], row["id"]))
    report = {
        "schema": "task-floor/gap-report@1",
        "registry_sha256": registry["registry_sha256"],
        "entries": len(registry["entries"]),
        "axes": len(registry["axes"]),
        "gaps": gaps,
        "critical_gaps": [row["id"] for row in gaps if row["priority"] == "critical"],
        "high_gaps": [row["id"] for row in gaps if row["priority"] == "high"],
        "system_scores": system_scores,
        "conclusion": (
            "No surveyed transport, runtime, policy, telemetry, provenance, or "
            "benchmark project documents the complete Task Floor contract."
        ),
    }
    report["report_sha256"] = hash_json(report)
    return report
