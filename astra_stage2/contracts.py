"""Fail-closed validation contracts for Stage 2 calibration evidence."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable

from .canonical import Stage2Error, git_blob_sha1_bytes, sha256_object, without_field
from .generator import (
    CONTROL_ROLES,
    EFFORTS,
    EXPECTED_CASE_COUNT,
    EXPECTED_OBSERVATION_COUNT,
    FAMILIES,
    K_LEVELS,
    R_LEVELS,
    REPLICATES,
    reconstruct_task,
)

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

STAGE1_BLOBS = {
    "docs/agents/claims/CLAUDE-ASTRA-KXR-PREREG-1.md": "50e55101cf70a30a1711bce7b4a0bb2e07a29ebb",
    "docs/agents/claims/CLAUDE-FRR-ASTRA-PREREG-1.md": "a2a7a7326e7a7ca10dee8fe7436b3738a4fedaac",
    "experiments/astra_kxr/DECISION_RULES.json": "f3edab40f3f6c056a6f35b53a580089dba7818aa",
    "experiments/astra_kxr/FRR-ASTRA-1.md": "b11a928947a8eee2f5ce940ab8d3e825dd76c4d9",
    "experiments/astra_kxr/FRR_ASTRA_1_RULES.json": "cdf1e52704808b61c81e3b6bd12bce440cded0ec",
    "experiments/astra_kxr/KNOWN-LIMITATIONS.md": "438ccc2b6a44ed4de9c8639cb541d068e3bb11fc",
    "experiments/astra_kxr/PREREGISTRATION.md": "4f9eeebb0f5f7d263b1d576afba13914739acf4a",
}

FORBIDDEN_RETAINED_KEYS = {
    "prompt",
    "prompt_text",
    "response",
    "response_text",
    "completion",
    "completion_text",
    "transcript",
    "messages",
    "message",
    "session_id",
    "source_path",
    "private_path",
    "raw_request",
    "raw_response",
}

IDENTITY_DIGEST_FIELDS = (
    "model_revision_sha256",
    "weights_sha256",
    "tokenizer_sha256",
    "runtime_sha256",
    "adapter_sha256",
    "hardware_sha256",
)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Stage2Error(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Stage2Error(f"{label} must be an array")
    return value


def _require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Stage2Error(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise Stage2Error(f"{label} must be >= {minimum}")
    return value


def _require_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Stage2Error(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise Stage2Error(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise Stage2Error(f"{label} must be >= {minimum}")
    return number


def _require_sha1(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA1_RE.fullmatch(value):
        raise Stage2Error(f"{label} must be a lowercase 40-hex Git SHA-1")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise Stage2Error(f"{label} must be a lowercase 64-hex SHA-256")
    return value


def _verify_self_hash(value: dict[str, Any], field: str, label: str) -> str:
    observed = _require_sha256(value.get(field), f"{label}.{field}")
    expected = sha256_object(without_field(value, field))
    if observed != expected:
        raise Stage2Error(f"{label} self-hash mismatch")
    return observed


def _walk_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if lowered in FORBIDDEN_RETAINED_KEYS:
                raise Stage2Error(f"forbidden retained text-bearing key at {path}.{key}")
            _walk_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]")


def verify_stage1_blobs(repo_root: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in STAGE1_BLOBS.items():
        path = repo_root / relative
        if not path.is_file():
            raise Stage2Error(f"missing frozen Stage 1 path: {relative}")
        digest = git_blob_sha1_bytes(path.read_bytes())
        if digest != expected:
            raise Stage2Error(
                f"Stage 1 blob drift for {relative}: expected {expected}, observed {digest}"
            )
        observed[relative] = digest
    return observed


def validate_generator_manifest(manifest: Any) -> dict[str, Any]:
    manifest = _require_mapping(manifest, "generator manifest")
    if manifest.get("schema") != "tier-bench/astra-stage2-generator-manifest@1":
        raise Stage2Error("unexpected generator-manifest schema")
    _verify_self_hash(manifest, "payload_sha256", "generator manifest")
    if manifest.get("families") != list(FAMILIES):
        raise Stage2Error("generator families differ from frozen order")
    if manifest.get("k_levels") != list(K_LEVELS):
        raise Stage2Error("K levels differ from frozen order")
    if manifest.get("r_levels") != list(R_LEVELS):
        raise Stage2Error("R levels differ from frozen order")
    if manifest.get("replicates") != list(REPLICATES):
        raise Stage2Error("replicate denominator differs from frozen order")
    if _require_int(manifest.get("case_count"), "case_count") != EXPECTED_CASE_COUNT:
        raise Stage2Error("generator case denominator is incomplete")
    cases = _require_list(manifest.get("cases"), "cases")
    if len(cases) != EXPECTED_CASE_COUNT:
        raise Stage2Error("generator case array length is incomplete")
    coordinates: set[tuple[Any, ...]] = set()
    case_ids: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = _require_mapping(raw_case, f"cases[{index}]")
        coordinate = (case.get("family"), case.get("k"), case.get("r"), case.get("replicate"))
        if coordinate in coordinates:
            raise Stage2Error(f"duplicate generator coordinate: {coordinate}")
        coordinates.add(coordinate)
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith("s2case_"):
            raise Stage2Error("invalid case id")
        if case_id in case_ids:
            raise Stage2Error(f"duplicate case id: {case_id}")
        case_ids.add(case_id)
        _require_sha256(case.get("task_sha256"), f"cases[{index}].task_sha256")
        _require_int(case.get("task_bytes"), f"cases[{index}].task_bytes", minimum=1)
        checksum = case.get("expected_checksum")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{16}", checksum):
            raise Stage2Error("invalid expected checksum")
        reconstruct_task(case)
    expected_coordinates = {
        (family, k, r, replicate)
        for family in FAMILIES
        for k in K_LEVELS
        for r in R_LEVELS
        for replicate in REPLICATES
    }
    if coordinates != expected_coordinates:
        raise Stage2Error("generator coordinate set is incomplete or widened")
    return manifest


def validate_control_manifest(manifest: Any, *, require_bound_empirical: bool = False) -> dict[str, Any]:
    manifest = _require_mapping(manifest, "control manifest")
    if manifest.get("schema") != "tier-bench/astra-stage2-control-manifest@1":
        raise Stage2Error("unexpected control-manifest schema")
    evidence_class = manifest.get("evidence_class")
    if evidence_class not in {"fixture_synthetic", "empirical_local"}:
        raise Stage2Error("unsupported control-manifest evidence class")
    _require_sha1(manifest.get("stage1_join_head"), "stage1_join_head")
    controls = _require_list(manifest.get("controls"), "controls")
    if [item.get("control_id") for item in controls if isinstance(item, dict)] != list(CONTROL_ROLES):
        raise Stage2Error("control roles must equal the frozen three-control denominator")
    for index, raw_control in enumerate(controls):
        control = _require_mapping(raw_control, f"controls[{index}]")
        identity = _require_mapping(control.get("identity"), f"controls[{index}].identity")
        if identity.get("evidence_class") != evidence_class:
            raise Stage2Error("control identity evidence class mismatch")
        if identity.get("role") != control.get("control_id"):
            raise Stage2Error("control identity role mismatch")
        repository = identity.get("source_repository")
        if not isinstance(repository, str) or not repository:
            raise Stage2Error("source_repository is required")
        _require_sha1(identity.get("source_commit_sha1"), "source_commit_sha1")
        if evidence_class == "fixture_synthetic" or require_bound_empirical:
            for field in IDENTITY_DIGEST_FIELDS:
                _require_sha256(identity.get(field), f"identity.{field}")
            expected_identity = sha256_object(identity)
            if control.get("identity_sha256") != expected_identity:
                raise Stage2Error("control identity digest mismatch")
        elif require_bound_empirical:
            raise Stage2Error("empirical manifest is unbound")
    if evidence_class == "fixture_synthetic" or require_bound_empirical:
        _verify_self_hash(manifest, "payload_sha256", "control manifest")
    return manifest


def bind_empirical_control_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = _require_mapping(manifest, "control manifest")
    if manifest.get("evidence_class") != "empirical_local":
        raise Stage2Error("only an empirical-local manifest may be bound")
    bound = {key: value for key, value in manifest.items() if key not in {"payload_sha256", "status"}}
    controls = _require_list(bound.get("controls"), "controls")
    for raw_control in controls:
        control = _require_mapping(raw_control, "control")
        identity = _require_mapping(control.get("identity"), "identity")
        for field in IDENTITY_DIGEST_FIELDS:
            _require_sha256(identity.get(field), field)
        control["identity_sha256"] = sha256_object(identity)
    bound["status"] = "BOUND_EMPIRICAL_IDENTITIES"
    bound["payload_sha256"] = sha256_object(bound)
    validate_control_manifest(bound, require_bound_empirical=True)
    return bound


def validate_plan(
    plan: Any,
    generator_manifest: dict[str, Any],
    control_manifest: dict[str, Any],
) -> dict[str, Any]:
    plan = _require_mapping(plan, "calibration plan")
    if plan.get("schema") != "tier-bench/astra-stage2-calibration-plan@1":
        raise Stage2Error("unexpected calibration-plan schema")
    _verify_self_hash(plan, "payload_sha256", "calibration plan")
    if plan.get("generator_manifest_sha256") != generator_manifest.get("payload_sha256"):
        raise Stage2Error("plan generator binding mismatch")
    if plan.get("control_manifest_sha256") != control_manifest.get("payload_sha256"):
        raise Stage2Error("plan control binding mismatch")
    if plan.get("stage1_join_head") != control_manifest.get("stage1_join_head"):
        raise Stage2Error("plan Stage 1 join binding mismatch")
    if _require_int(plan.get("case_count"), "case_count") != EXPECTED_CASE_COUNT:
        raise Stage2Error("plan case denominator mismatch")
    if _require_int(plan.get("control_count"), "control_count") != len(CONTROL_ROLES):
        raise Stage2Error("plan control denominator mismatch")
    if _require_int(plan.get("effort_count"), "effort_count") != len(EFFORTS):
        raise Stage2Error("plan effort denominator mismatch")
    if _require_int(plan.get("observation_count"), "observation_count") != EXPECTED_OBSERVATION_COUNT:
        raise Stage2Error("plan observation denominator mismatch")
    rows = _require_list(plan.get("observations"), "observations")
    if len(rows) != EXPECTED_OBSERVATION_COUNT:
        raise Stage2Error("plan observation array is incomplete")
    expected_cases = {case["case_id"]: case for case in generator_manifest["cases"]}
    expected_controls = {control["control_id"]: control for control in control_manifest["controls"]}
    observed_ids: set[str] = set()
    observed_cells: set[tuple[str, str, str]] = set()
    for index, raw_row in enumerate(rows):
        row = _require_mapping(raw_row, f"observations[{index}]")
        observation_id = row.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id.startswith("s2obs_"):
            raise Stage2Error("invalid observation id")
        if observation_id in observed_ids:
            raise Stage2Error(f"duplicate observation id: {observation_id}")
        observed_ids.add(observation_id)
        case = expected_cases.get(row.get("case_id"))
        control = expected_controls.get(row.get("control_id"))
        if case is None or control is None or row.get("effort") not in EFFORTS:
            raise Stage2Error("plan references an unregistered case, control, or effort")
        for field in ("family", "k", "r", "replicate", "task_sha256", "expected_checksum"):
            if row.get(field) != case.get(field):
                raise Stage2Error(f"plan case projection mismatch for {field}")
        if row.get("control_class") != control.get("class_label"):
            raise Stage2Error("plan control-class mismatch")
        if row.get("control_identity_sha256") != control.get("identity_sha256"):
            raise Stage2Error("plan control-identity mismatch")
        cell = (row["case_id"], row["control_id"], row["effort"])
        if cell in observed_cells:
            raise Stage2Error(f"duplicate plan cell: {cell}")
        observed_cells.add(cell)
    return plan


def validate_observations(
    observations: Iterable[Any],
    plan: dict[str, Any],
    control_manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    rows = [_require_mapping(row, "observation") for row in observations]
    if len(rows) != EXPECTED_OBSERVATION_COUNT:
        raise Stage2Error(
            f"observation denominator incomplete: expected {EXPECTED_OBSERVATION_COUNT}, observed {len(rows)}"
        )
    expected = {item["observation_id"]: item for item in plan["observations"]}
    seen: set[str] = set()
    evidence_classes: set[str] = set()
    route_bindings: dict[tuple[str, str], str] = {}
    contract_bindings: dict[tuple[str, str], str] = {}
    for row in rows:
        _walk_forbidden(row)
        if row.get("schema") != "tier-bench/astra-stage2-observation@1":
            raise Stage2Error("unexpected observation schema")
        _verify_self_hash(row, "record_sha256", "observation")
        observation_id = row.get("observation_id")
        if not isinstance(observation_id, str) or observation_id not in expected:
            raise Stage2Error("observation id is outside the frozen plan")
        if observation_id in seen:
            raise Stage2Error(f"duplicate observation: {observation_id}")
        seen.add(observation_id)
        expected_row = expected[observation_id]
        for field in (
            "case_id",
            "family",
            "k",
            "r",
            "replicate",
            "task_sha256",
            "control_id",
            "control_class",
            "control_identity_sha256",
            "effort",
        ):
            if row.get(field) != expected_row.get(field):
                raise Stage2Error(f"observation projection mismatch for {field}")
        evidence_class = row.get("evidence_class")
        if evidence_class not in {"fixture_synthetic", "empirical_local"}:
            raise Stage2Error("unsupported observation evidence class")
        evidence_classes.add(evidence_class)
        if row.get("provider_error") is not False:
            raise Stage2Error("provider or runtime errors invalidate the calibration cell")
        checksum = row.get("observed_checksum")
        accepted = row.get("accepted")
        reconstructed_acceptance = checksum == expected_row["expected_checksum"]
        if not isinstance(accepted, bool) or accepted != reconstructed_acceptance:
            raise Stage2Error("accepted flag is not reconstructed from the deterministic answer")
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "ttft_ms",
            "latency_ms",
        ):
            _require_number(row.get(field), field, minimum=0.0)
        if row["cached_input_tokens"] > row["input_tokens"]:
            raise Stage2Error("cached input tokens exceed input tokens")
        route = _require_sha256(row.get("route_identity_sha256"), "route_identity_sha256")
        contract = _require_sha256(row.get("api_contract_sha256"), "api_contract_sha256")
        block = (row["control_id"], row["effort"])
        if block in route_bindings and route_bindings[block] != route:
            raise Stage2Error(f"route identity drift inside block {block}")
        route_bindings[block] = route
        if block in contract_bindings and contract_bindings[block] != contract:
            raise Stage2Error(f"API/runtime contract drift inside block {block}")
        contract_bindings[block] = contract
    if seen != set(expected):
        raise Stage2Error("observation ids do not equal the frozen plan denominator")
    if len(evidence_classes) != 1:
        raise Stage2Error("fixture and empirical evidence may not be mixed")
    evidence_class = next(iter(evidence_classes))
    if evidence_class != control_manifest.get("evidence_class"):
        raise Stage2Error("observation and control-manifest evidence classes differ")
    if evidence_class == "empirical_local":
        validate_control_manifest(control_manifest, require_bound_empirical=True)
    return rows, evidence_class
