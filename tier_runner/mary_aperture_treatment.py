from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


PLAN_SCHEMA = "mary/operator-aperture-plan@1"
VERDICT_SCHEMA = "mary/operator-aperture-canary-verdict@1"
RESPONSE_SCHEMA = "mary/operator-aperture-response@1"
TREATMENT_SCHEMA = "tierbench/mary-aperture-treatment@1"
OWNERSHIP_DECIDER = "deterministic_registry"
FORBIDDEN_KEYS = {
    "aggregate_score",
    "overall_score",
    "readiness_score",
    "winner",
    "universal_winner",
}
REQUIRED_CANARY_CHECKS = {
    "fixed-clause-set",
    "owned-routes",
    "unowned-routes",
    "covering-cartridge-for-every-owned-clause",
    "no-unowned-clause-is-claimable",
    "internet-route",
    "frontier-model-route",
    "deterministic-ownership",
    "model-does-not-decide-ownership",
    "candidate-only-authority",
}


class MaryApertureTreatmentError(ValueError):
    """Fail-closed rejection of an aperture artifact packet."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MaryApertureTreatmentError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads_strict(text: str, label: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicates)
    except json.JSONDecodeError as exc:
        raise MaryApertureTreatmentError(f"invalid {label}: {exc}") from exc


def _read(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MaryApertureTreatmentError(f"cannot read {label}: {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MaryApertureTreatmentError(f"{label} must be UTF-8") from exc
    value = loads_strict(text, label)
    if not isinstance(value, dict):
        raise MaryApertureTreatmentError(f"{label} must be a JSON object")
    return value, raw


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise MaryApertureTreatmentError(message)


def _need_text(value: Any, label: str) -> str:
    _need(isinstance(value, str) and bool(value.strip()), f"{label} must be non-empty text")
    return value


def _need_bool(value: Any, label: str) -> bool:
    _need(isinstance(value, bool), f"{label} must be boolean")
    return value


def _need_list(value: Any, label: str) -> list[Any]:
    _need(isinstance(value, list), f"{label} must be an array")
    return value


def _scan_forbidden_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS or key.endswith("_aggregate_score"):
                raise MaryApertureTreatmentError(
                    f"forbidden aggregate or winner field at {path}.{key}"
                )
            _scan_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden_keys(child, f"{path}[{index}]")


def _verify_self_digest(value: dict[str, Any], field: str, label: str) -> str:
    supplied = _need_text(value.get(field), f"{label}.{field}")
    body = {key: child for key, child in value.items() if key != field}
    actual = sha256_json(body)
    _need(supplied == actual, f"{label} digest mismatch: expected {supplied}, got {actual}")
    return actual


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    _scan_forbidden_keys(plan)
    _need(plan.get("schema") == PLAN_SCHEMA, f"plan schema must be {PLAN_SCHEMA}")
    _need(plan.get("authority") == "candidate_only", "plan authority must be candidate_only")
    _need(plan.get("production_claim") is False, "plan production_claim must be false")
    _need(
        plan.get("ownership_decider") == OWNERSHIP_DECIDER,
        "plan ownership must be decided by deterministic_registry",
    )
    _need(plan.get("model_used_for_ownership") is False, "a model may not decide ownership")
    _need_bool(plan.get("model_used_for_segmentation"), "plan.model_used_for_segmentation")
    _need_text(plan.get("utterance"), "plan.utterance")
    _verify_self_digest(plan, "plan_sha256", "plan")

    clauses = _need_list(plan.get("clauses"), "plan.clauses")
    _need(bool(clauses), "plan must contain at least one clause")
    seen: set[str] = set()
    owned: list[str] = []
    unowned: list[str] = []
    by_route: dict[str, list[str]] = {}

    for index, clause_any in enumerate(clauses):
        label = f"plan.clauses[{index}]"
        _need(isinstance(clause_any, dict), f"{label} must be an object")
        clause = clause_any
        clause_id = _need_text(clause.get("clause_id"), f"{label}.clause_id")
        _need(clause_id not in seen, f"duplicate clause_id: {clause_id}")
        seen.add(clause_id)
        _need(
            clause.get("ownership_decider") == OWNERSHIP_DECIDER,
            f"{clause_id} ownership must be decided by deterministic_registry",
        )
        _need_text(clause.get("segment_id"), f"{label}.segment_id")
        _need_text(clause.get("source_text"), f"{label}.source_text")
        _need_text(clause.get("topic"), f"{label}.topic")
        _need_text(clause.get("intent"), f"{label}.intent")
        route = _need_text(clause.get("route"), f"{label}.route")
        state = _need_text(clause.get("state"), f"{label}.state")
        claimable = _need_bool(clause.get("claimable"), f"{label}.claimable")
        coverings = _need_list(
            clause.get("covering_cartridge_ids"), f"{label}.covering_cartridge_ids"
        )
        _need(
            all(isinstance(item, str) and item for item in coverings),
            f"{label}.covering_cartridge_ids must contain non-empty text",
        )
        by_route.setdefault(route, []).append(clause_id)

        if state == "owned":
            _need(claimable, f"owned clause {clause_id} must be claimable")
            _need(bool(coverings), f"owned clause {clause_id} requires a covering cartridge")
            _need(
                clause.get("missing_property") is None,
                f"owned clause {clause_id} cannot declare a missing property",
            )
            _need(
                clause.get("response_action") in {"answer", "query_and_answer"},
                f"owned clause {clause_id} has invalid response_action",
            )
            _need(route not in {"user", "hold"}, f"owned clause {clause_id} cannot route to {route}")
            owned.append(clause_id)
        else:
            _need(state in {"escalate", "hold"}, f"unsupported clause state: {state}")
            _need(not claimable, f"unowned clause {clause_id} cannot be claimable")
            _need(not coverings, f"unowned clause {clause_id} cannot claim cartridge coverage")
            _need_text(clause.get("missing_property"), f"{label}.missing_property")
            _need(
                clause.get("response_action") in {"ask_user", "hold"},
                f"unowned clause {clause_id} has invalid response_action",
            )
            unowned.append(clause_id)

    summary = plan.get("summary")
    _need(isinstance(summary, dict), "plan.summary must be an object")
    _need(
        summary.get("owned_clause_ids") == owned,
        "plan summary owned_clause_ids do not match clause order",
    )
    _need(
        summary.get("unowned_clause_ids") == unowned,
        "plan summary unowned_clause_ids do not match clause order",
    )
    summary_routes = summary.get("by_route")
    _need(isinstance(summary_routes, dict), "plan.summary.by_route must be an object")
    for route, clause_ids in summary_routes.items():
        _need(isinstance(clause_ids, list), f"route {route} must be an array")
        _need(clause_ids == by_route.get(route, []), f"route projection mismatch for {route}")
    for route in by_route:
        _need(route in summary_routes, f"route missing from summary: {route}")

    internet_required = bool(by_route.get("internet"))
    frontier_required = bool(by_route.get("frontier_model"))
    _need(
        summary.get("internet_required") is internet_required,
        "plan internet_required disagrees with routes",
    )
    _need(
        summary.get("frontier_model_required") is frontier_required,
        "plan frontier_model_required disagrees with routes",
    )
    return {
        "owned": owned,
        "unowned": unowned,
        "by_route": by_route,
        "plan_sha256": plan["plan_sha256"],
    }


def _validate_verdict(verdict: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    _scan_forbidden_keys(verdict)
    _need(verdict.get("schema") == VERDICT_SCHEMA, f"verdict schema must be {VERDICT_SCHEMA}")
    _need(verdict.get("status") == "pass", "verdict status must be pass")
    _need(verdict.get("plan") == plan, "verdict embedded plan does not match the supplied plan artifact")
    checks = _need_list(verdict.get("checks"), "verdict.checks")
    ids: list[str] = []
    for index, check_any in enumerate(checks):
        _need(isinstance(check_any, dict), f"verdict.checks[{index}] must be an object")
        check_id = _need_text(check_any.get("id"), f"verdict.checks[{index}].id")
        _need(check_any.get("pass") is True, f"verdict check failed: {check_id}")
        ids.append(check_id)
    _need(len(ids) == len(set(ids)), "verdict contains duplicate check ids")
    _need(set(ids) == REQUIRED_CANARY_CHECKS, "verdict check set does not match the required aperture canary")
    _verify_self_digest(verdict, "verdict_sha256", "verdict")
    return {"check_ids": ids, "verdict_sha256": verdict["verdict_sha256"]}


def _validate_evidence(row: Any, label: str) -> None:
    _need(isinstance(row, dict), f"{label} must be an object")
    _need_text(row.get("source_id"), f"{label}.source_id")
    digest = _need_text(row.get("evidence_sha256"), f"{label}.evidence_sha256")
    _need(len(digest) == 64, f"{label}.evidence_sha256 must be 64 hex characters")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise MaryApertureTreatmentError(
            f"{label}.evidence_sha256 must be lowercase hexadecimal"
        ) from exc
    _need_text(row.get("evidence_tier"), f"{label}.evidence_tier")
    _need_text(row.get("freshness"), f"{label}.freshness")


def _validate_response(
    response: dict[str, Any],
    plan: dict[str, Any],
    plan_info: dict[str, Any],
    *,
    provider_free: bool,
) -> dict[str, Any]:
    _scan_forbidden_keys(response)
    _need(response.get("schema") == RESPONSE_SCHEMA, f"response schema must be {RESPONSE_SCHEMA}")
    _need(response.get("authority") == "candidate_only", "response authority must be candidate_only")
    _need(response.get("production_claim") is False, "response production_claim must be false")
    _need(response.get("plan_sha256") == plan_info["plan_sha256"], "response is not bound to the supplied plan")
    _need(response.get("utterance") == plan.get("utterance"), "response utterance does not match plan")
    _verify_self_digest(response, "response_sha256", "response")

    owned_results = _need_list(response.get("owned_results"), "response.owned_results")
    unowned_routes = _need_list(response.get("unowned_routes"), "response.unowned_routes")
    owned_ids: list[str] = []
    unowned_ids: list[str] = []
    cartridge_counts: dict[str, int] = {}

    for index, result_any in enumerate(owned_results):
        label = f"response.owned_results[{index}]"
        _need(isinstance(result_any, dict), f"{label} must be an object")
        result = result_any
        clause_id = _need_text(result.get("clause_id"), f"{label}.clause_id")
        owned_ids.append(clause_id)
        _need(result.get("authority") == "candidate_only", f"{clause_id} widened authority")
        cartridge_id = _need_text(result.get("cartridge_id"), f"{label}.cartridge_id")
        cartridge_counts[cartridge_id] = cartridge_counts.get(cartridge_id, 0) + 1
        _need_text(result.get("machine_id"), f"{label}.machine_id")
        _need_text(result.get("route"), f"{label}.route")
        answer = result.get("answer")
        _need(isinstance(answer, dict), f"{label}.answer must be an object")
        _need_text(answer.get("summary"), f"{label}.answer.summary")
        facts = _need_list(answer.get("facts"), f"{label}.answer.facts")
        _need(
            all(isinstance(item, str) and item for item in facts),
            f"{label}.answer.facts must contain non-empty text",
        )
        evidence = _need_list(result.get("evidence"), f"{label}.evidence")
        _need(bool(evidence), f"{clause_id} must retain at least one evidence reference")
        for evidence_index, evidence_row in enumerate(evidence):
            _validate_evidence(evidence_row, f"{label}.evidence[{evidence_index}]")
        _verify_self_digest(result, "response_sha256", label)

    for index, route_any in enumerate(unowned_routes):
        label = f"response.unowned_routes[{index}]"
        _need(isinstance(route_any, dict), f"{label} must be an object")
        route = route_any
        clause_id = _need_text(route.get("clause_id"), f"{label}.clause_id")
        unowned_ids.append(clause_id)
        _need(route.get("claimable") is False, f"unowned clause {clause_id} became claimable")
        _need_text(route.get("missing_property"), f"{label}.missing_property")
        _need_text(route.get("reason"), f"{label}.reason")
        _need(route.get("response_action") in {"ask_user", "hold"}, f"{clause_id} action invalid")
        _need(
            route.get("route") in {"user", "hold", "internet", "frontier_model", "validator"},
            f"{clause_id} route invalid",
        )

    _need(owned_ids == plan_info["owned"], "owned response clauses do not match plan")
    _need(unowned_ids == plan_info["unowned"], "unowned response clauses do not match plan")

    sessions = _need_list(response.get("machine_sessions"), "response.machine_sessions")
    session_counts: dict[str, int] = {}
    for index, session_any in enumerate(sessions):
        label = f"response.machine_sessions[{index}]"
        _need(isinstance(session_any, dict), f"{label} must be an object")
        session = session_any
        cartridge_id = _need_text(session.get("cartridge_id"), f"{label}.cartridge_id")
        _need(cartridge_id not in session_counts, f"duplicate machine session for {cartridge_id}")
        query_count = session.get("query_count")
        _need(isinstance(query_count, int) and query_count > 0, f"{label}.query_count invalid")
        session_counts[cartridge_id] = query_count
        _need(session.get("carrier") in {"stdio", "filedrop", "service", "artifact"}, f"{label}.carrier invalid")
        machine = session.get("machine")
        _need(isinstance(machine, dict), f"{label}.machine must be an object")
        _need(machine.get("authority") == "read_only", f"{cartridge_id} machine is not read_only")
        _need_text(machine.get("machine_id"), f"{label}.machine.machine_id")
        capabilities = _need_list(machine.get("capabilities"), f"{label}.machine.capabilities")
        _need(
            any(isinstance(item, str) and item.startswith("query:") for item in capabilities),
            f"{cartridge_id} has no query capability",
        )

    _need(session_counts == cartridge_counts, "machine-session query counts do not match owned results")

    summary = response.get("summary")
    _need(isinstance(summary, dict), "response.summary must be an object")
    _need(summary.get("owned_clause_count") == len(owned_ids), "owned count mismatch")
    _need(summary.get("unowned_clause_count") == len(unowned_ids), "unowned count mismatch")
    _need(summary.get("machine_session_count") == len(sessions), "session count mismatch")
    _need(summary.get("machine_query_count") == len(owned_ids), "query count mismatch")
    _need_bool(summary.get("internet_used"), "response.summary.internet_used")
    _need_bool(summary.get("frontier_model_used"), "response.summary.frontier_model_used")
    _need_bool(summary.get("mutation_attempted"), "response.summary.mutation_attempted")

    if provider_free:
        _need(summary["internet_used"] is False, "provider-free treatment used the internet")
        _need(summary["frontier_model_used"] is False, "provider-free treatment used a frontier model")
        _need(summary["mutation_attempted"] is False, "read treatment attempted mutation")
        _need(not plan_info["by_route"].get("internet"), "provider-free plan routes to internet")
        _need(not plan_info["by_route"].get("frontier_model"), "provider-free plan routes to frontier model")

    return {
        "response_sha256": response["response_sha256"],
        "owned_clause_count": len(owned_ids),
        "unowned_clause_count": len(unowned_ids),
        "machine_session_count": len(sessions),
        "machine_query_count": len(owned_ids),
        "internet_used": summary["internet_used"],
        "frontier_model_used": summary["frontier_model_used"],
        "mutation_attempted": summary["mutation_attempted"],
    }


def run_treatment(
    *,
    plan_path: Path,
    verdict_path: Path,
    response_path: Path,
    provider_free: bool = True,
) -> dict[str, Any]:
    raw_digests: dict[str, dict[str, Any]] = {}
    try:
        plan, plan_raw = _read(plan_path, "plan")
        verdict, verdict_raw = _read(verdict_path, "verdict")
        response, response_raw = _read(response_path, "response")
        for name, path, raw in (
            ("plan", plan_path, plan_raw),
            ("verdict", verdict_path, verdict_raw),
            ("response", response_path, response_raw),
        ):
            raw_digests[name] = {
                "path_name": path.name,
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            }

        plan_info = _validate_plan(plan)
        verdict_info = _validate_verdict(verdict, plan)
        response_info = _validate_response(response, plan, plan_info, provider_free=provider_free)
        body = {
            "schema": TREATMENT_SCHEMA,
            "status": "pass",
            "provider_free": provider_free,
            "artifacts": raw_digests,
            "plan_sha256": plan_info["plan_sha256"],
            "verdict_sha256": verdict_info["verdict_sha256"],
            "response_sha256": response_info["response_sha256"],
            "observations": {
                key: response_info[key]
                for key in (
                    "owned_clause_count",
                    "unowned_clause_count",
                    "machine_session_count",
                    "machine_query_count",
                    "internet_used",
                    "frontier_model_used",
                    "mutation_attempted",
                )
            },
            "authority": {
                "candidate_only": True,
                "production_claim": False,
                "promotion_authorized": False,
                "ownership_decider": OWNERSHIP_DECIDER,
                "model_may_decide_ownership": False,
            },
            "claim_boundary": (
                "This treatment verifies the structure, self-digests, cross-bindings, "
                "ownership law, evidence references, read-only machine sessions, and "
                "provider-free route behavior of supplied MARY operator-aperture artifacts. "
                "It does not qualify the live sources, model quality, physical systems, "
                "mutation authority, production operation, or field use."
            ),
        }
        return {**body, "treatment_sha256": sha256_json(body)}
    except MaryApertureTreatmentError as exc:
        body = {
            "schema": TREATMENT_SCHEMA,
            "status": "refused",
            "provider_free": provider_free,
            "artifacts": raw_digests,
            "reason": str(exc),
            "authority": {
                "candidate_only": True,
                "production_claim": False,
                "promotion_authorized": False,
                "ownership_decider": OWNERSHIP_DECIDER,
                "model_may_decide_ownership": False,
            },
        }
        return {**body, "treatment_sha256": sha256_json(body)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tiermary",
        description="Verify externally supplied MARY operator-aperture artifacts without importing MARY.",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--verdict", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-external-routes",
        action="store_true",
        help="permit an artifact packet that records internet or frontier use",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_treatment(
        plan_path=args.plan,
        verdict_path=args.verdict,
        response_path=args.response,
        provider_free=not args.allow_external_routes,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_bytes(encoded.encode("utf-8"))
        temporary.replace(args.output)
    else:
        sys.stdout.write(encoded)
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
