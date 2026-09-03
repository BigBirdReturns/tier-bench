"""Fail-closed validation contracts for Stage 2 calibration evidence."""

from __future__ import annotations

import copy
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .canonical import Stage2Error, sha256_object, without_field
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

GENERATOR_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "generator_version",
        "families",
        "k_levels",
        "r_levels",
        "replicates",
        "lane_count",
        "table_size",
        "case_count",
        "cases",
        "payload_sha256",
    }
)

GENERATOR_CASE_FIELDS = frozenset(
    {
        "case_id",
        "family",
        "k",
        "r",
        "replicate",
        "task_sha256",
        "task_bytes",
        "expected_checksum",
    }
)

CONTROL_MANIFEST_BASE_FIELDS = frozenset(
    {
        "schema",
        "evidence_class",
        "stage1_join_head",
        "controls",
        "payload_sha256",
    }
)
CONTROL_MANIFEST_EMPIRICAL_FIELDS = CONTROL_MANIFEST_BASE_FIELDS | {"status"}

CONTROL_FIELDS = frozenset(
    {
        "control_id",
        "class_label",
        "identity",
        "identity_sha256",
    }
)

CONTROL_IDENTITY_FIELDS = frozenset(
    {
        "evidence_class",
        "role",
        "source_repository",
        "source_commit_sha1",
        "model_revision_sha256",
        "weights_sha256",
        "tokenizer_sha256",
        "runtime_sha256",
        "adapter_sha256",
        "hardware_sha256",
    }
)

PLAN_FIELDS = frozenset(
    {
        "schema",
        "stage1_join_head",
        "generator_manifest_sha256",
        "control_manifest_sha256",
        "case_count",
        "control_count",
        "effort_count",
        "observation_count",
        "observations",
        "payload_sha256",
    }
)

PLAN_OBSERVATION_FIELDS = frozenset(
    {
        "observation_id",
        "case_id",
        "family",
        "k",
        "r",
        "replicate",
        "task_sha256",
        "expected_checksum",
        "control_id",
        "control_class",
        "control_identity_sha256",
        "effort",
    }
)

OBSERVATION_FIELDS = frozenset(
    {
        "accepted",
        "api_contract_sha256",
        "cached_input_tokens",
        "case_id",
        "control_class",
        "control_id",
        "control_identity_sha256",
        "effort",
        "evidence_class",
        "expected_checksum",
        "family",
        "input_tokens",
        "k",
        "latency_ms",
        "observation_id",
        "observed_checksum",
        "output_tokens",
        "provider_error",
        "r",
        "reasoning_tokens",
        "record_sha256",
        "replicate",
        "route_identity_sha256",
        "schema",
        "task_sha256",
        "ttft_ms",
    }
)

IDENTITY_DIGEST_FIELDS = (
    "model_revision_sha256",
    "weights_sha256",
    "tokenizer_sha256",
    "runtime_sha256",
    "adapter_sha256",
    "hardware_sha256",
)

CONTROL_CLASS_BY_ROLE = {
    "lotus_3b_recurrent": "recurrent_latent",
    "loopcoder_v2_7b_parallel": "parallel_latent",
    "conventional_transformer_negative": "conventional_negative",
}


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Stage2Error(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Stage2Error(f"{label} must be an array")
    return value


def _require_exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    observed = set(value)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing or unexpected:
        raise Stage2Error(
            f"{label} property set mismatch: missing={missing}, unexpected={unexpected}"
        )


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


def _run_git(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise Stage2Error(f"Git is required for Stage 1 custody verification: {exc}") from exc


def _git_output(repo_root: Path, *arguments: str) -> str:
    process = _run_git(repo_root, *arguments)
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or f"exit {process.returncode}"
        raise Stage2Error(f"Git custody command failed ({' '.join(arguments)}): {detail}")
    return process.stdout.strip()


def _require_clean_git_path(repo_root: Path, relative: str) -> None:
    checks = (
        ("worktree", ("diff", "--quiet", "--no-ext-diff", "--", relative)),
        ("index", ("diff", "--cached", "--quiet", "--no-ext-diff", "HEAD", "--", relative)),
    )
    for label, arguments in checks:
        process = _run_git(repo_root, *arguments)
        if process.returncode == 1:
            raise Stage2Error(f"Stage 1 {label} drift for {relative}")
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or f"exit {process.returncode}"
            raise Stage2Error(f"Git {label} custody check failed for {relative}: {detail}")


def verify_stage1_blobs(repo_root: Path) -> dict[str, str]:
    requested_root = repo_root.resolve()
    repository_root = Path(_git_output(requested_root, "rev-parse", "--show-toplevel")).resolve()
    observed: dict[str, str] = {}
    for relative, expected in STAGE1_BLOBS.items():
        path = repository_root / relative
        if not path.is_file():
            raise Stage2Error(f"missing frozen Stage 1 path: {relative}")
        digest = _git_output(repository_root, "rev-parse", "--verify", f"HEAD:{relative}")
        if digest != expected:
            raise Stage2Error(
                f"Stage 1 blob drift for {relative}: expected {expected}, observed {digest}"
            )
        _require_clean_git_path(repository_root, relative)
        observed[relative] = digest
    return observed


def _validate_plan_closed_shape(plan: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = _require_mapping(plan, "calibration plan")
    _require_exact_keys(plan, PLAN_FIELDS, "calibration plan")
    if plan.get("schema") != "tier-bench/astra-stage2-calibration-plan@1":
        raise Stage2Error("unexpected calibration-plan schema")
    _require_sha1(plan.get("stage1_join_head"), "stage1_join_head")
    _require_sha256(plan.get("generator_manifest_sha256"), "generator_manifest_sha256")
    _require_sha256(plan.get("control_manifest_sha256"), "control_manifest_sha256")
    if _require_int(plan.get("case_count"), "case_count") != EXPECTED_CASE_COUNT:
        raise Stage2Error("plan case denominator mismatch")
    if _require_int(plan.get("control_count"), "control_count") != len(CONTROL_ROLES):
        raise Stage2Error("plan control denominator mismatch")
    if _require_int(plan.get("effort_count"), "effort_count") != len(EFFORTS):
        raise Stage2Error("plan effort denominator mismatch")
    if _require_int(plan.get("observation_count"), "observation_count") != EXPECTED_OBSERVATION_COUNT:
        raise Stage2Error("plan observation denominator mismatch")
    raw_rows = _require_list(plan.get("observations"), "observations")
    if len(raw_rows) != EXPECTED_OBSERVATION_COUNT:
        raise Stage2Error("plan observation array is incomplete")
    rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(raw_rows):
        row = _require_mapping(raw_row, f"observations[{index}]")
        _require_exact_keys(row, PLAN_OBSERVATION_FIELDS, f"observations[{index}]")
        rows.append(row)
    _walk_forbidden(plan)
    _verify_self_hash(plan, "payload_sha256", "calibration plan")
    return plan, rows


def validate_generator_manifest(manifest: Any) -> dict[str, Any]:
    manifest = _require_mapping(manifest, "generator manifest")
    _require_exact_keys(manifest, GENERATOR_MANIFEST_FIELDS, "generator manifest")
    if manifest.get("schema") != "tier-bench/astra-stage2-generator-manifest@1":
        raise Stage2Error("unexpected generator-manifest schema")
    cases = _require_list(manifest.get("cases"), "cases")
    for index, raw_case in enumerate(cases):
        case = _require_mapping(raw_case, f"cases[{index}]")
        _require_exact_keys(case, GENERATOR_CASE_FIELDS, f"cases[{index}]")
    _walk_forbidden(manifest)
    _verify_self_hash(manifest, "payload_sha256", "generator manifest")
    if not isinstance(manifest.get("generator_version"), str) or not manifest["generator_version"]:
        raise Stage2Error("generator_version must be a non-empty string")
    if manifest.get("families") != list(FAMILIES):
        raise Stage2Error("generator families differ from frozen order")
    if manifest.get("k_levels") != list(K_LEVELS):
        raise Stage2Error("K levels differ from frozen order")
    if manifest.get("r_levels") != list(R_LEVELS):
        raise Stage2Error("R levels differ from frozen order")
    if manifest.get("replicates") != list(REPLICATES):
        raise Stage2Error("replicate denominator differs from frozen order")
    if manifest.get("lane_count") != 32:
        raise Stage2Error("generator lane count differs from frozen value")
    if manifest.get("table_size") != 16:
        raise Stage2Error("generator table size differs from frozen value")
    if _require_int(manifest.get("case_count"), "case_count") != EXPECTED_CASE_COUNT:
        raise Stage2Error("generator case denominator is incomplete")
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
        if not isinstance(case_id, str) or not re.fullmatch(r"s2case_[0-9a-f]{24}", case_id):
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


def validate_control_manifest(
    manifest: Any,
    *,
    require_bound_empirical: bool = False,
) -> dict[str, Any]:
    manifest = _require_mapping(manifest, "control manifest")
    evidence_class = manifest.get("evidence_class")
    if evidence_class not in {"fixture_synthetic", "empirical_local"}:
        raise Stage2Error("unsupported control-manifest evidence class")
    expected_fields = (
        CONTROL_MANIFEST_BASE_FIELDS
        if evidence_class == "fixture_synthetic"
        else CONTROL_MANIFEST_EMPIRICAL_FIELDS
    )
    _require_exact_keys(manifest, expected_fields, "control manifest")
    _walk_forbidden(manifest)
    if manifest.get("schema") != "tier-bench/astra-stage2-control-manifest@1":
        raise Stage2Error("unexpected control-manifest schema")
    _require_sha1(manifest.get("stage1_join_head"), "stage1_join_head")

    status = manifest.get("status") if evidence_class == "empirical_local" else None
    if evidence_class == "empirical_local" and status not in {
        "UNBOUND_TEMPLATE",
        "BOUND_EMPIRICAL_IDENTITIES",
    }:
        raise Stage2Error("empirical control-manifest status is invalid")
    bound_empirical = status == "BOUND_EMPIRICAL_IDENTITIES"
    if require_bound_empirical and not bound_empirical:
        raise Stage2Error("empirical control manifest is not bound")

    controls = _require_list(manifest.get("controls"), "controls")
    if len(controls) != len(CONTROL_ROLES):
        raise Stage2Error("control denominator must equal the frozen three controls")
    if [item.get("control_id") for item in controls if isinstance(item, dict)] != list(CONTROL_ROLES):
        raise Stage2Error("control roles must equal the frozen three-control denominator")

    for index, raw_control in enumerate(controls):
        control = _require_mapping(raw_control, f"controls[{index}]")
        _require_exact_keys(control, CONTROL_FIELDS, f"controls[{index}]")
        identity = _require_mapping(control.get("identity"), f"controls[{index}].identity")
        _require_exact_keys(identity, CONTROL_IDENTITY_FIELDS, f"controls[{index}].identity")
        if identity.get("evidence_class") != evidence_class:
            raise Stage2Error("control identity evidence class mismatch")
        if identity.get("role") != control.get("control_id"):
            raise Stage2Error("control identity role mismatch")
        expected_class = CONTROL_CLASS_BY_ROLE.get(control.get("control_id"))
        if control.get("class_label") != expected_class:
            raise Stage2Error("control class label does not match its frozen role")
        repository = identity.get("source_repository")
        if not isinstance(repository, str) or not repository:
            raise Stage2Error("source_repository is required")
        _require_sha1(identity.get("source_commit_sha1"), "source_commit_sha1")

        if evidence_class == "fixture_synthetic" or bound_empirical:
            for field in IDENTITY_DIGEST_FIELDS:
                _require_sha256(identity.get(field), f"identity.{field}")
            expected_identity = sha256_object(identity)
            if control.get("identity_sha256") != expected_identity:
                raise Stage2Error("control identity digest mismatch")
        else:
            for field in IDENTITY_DIGEST_FIELDS:
                value = identity.get(field)
                if value is not None:
                    _require_sha256(value, f"identity.{field}")
            if control.get("identity_sha256") is not None:
                raise Stage2Error("unbound empirical control must not carry identity_sha256")

    if evidence_class == "fixture_synthetic" or bound_empirical:
        _verify_self_hash(manifest, "payload_sha256", "control manifest")
    elif manifest.get("payload_sha256") is not None:
        raise Stage2Error("unbound empirical control manifest must not carry payload_sha256")
    return manifest


def bind_empirical_control_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_control_manifest(manifest, require_bound_empirical=False)
    if manifest.get("evidence_class") != "empirical_local":
        raise Stage2Error("only an empirical-local manifest may be bound")
    if manifest.get("status") != "UNBOUND_TEMPLATE":
        raise Stage2Error("only an unbound empirical template may be bound")
    bound = copy.deepcopy(
        {key: value for key, value in manifest.items() if key not in {"payload_sha256", "status"}}
    )
    controls = _require_list(bound.get("controls"), "controls")
    for index, raw_control in enumerate(controls):
        control = _require_mapping(raw_control, f"controls[{index}]")
        _require_exact_keys(control, CONTROL_FIELDS, f"controls[{index}]")
        identity = _require_mapping(control.get("identity"), f"controls[{index}].identity")
        _require_exact_keys(identity, CONTROL_IDENTITY_FIELDS, f"controls[{index}].identity")
        for field in IDENTITY_DIGEST_FIELDS:
            _require_sha256(identity.get(field), f"identity.{field}")
        control["identity_sha256"] = sha256_object(identity)
    bound["status"] = "BOUND_EMPIRICAL_IDENTITIES"
    bound["payload_sha256"] = sha256_object(bound)
    return validate_control_manifest(bound, require_bound_empirical=True)


def validate_plan(
    plan: Any,
    generator_manifest: dict[str, Any],
    control_manifest: dict[str, Any],
) -> dict[str, Any]:
    generator_manifest = validate_generator_manifest(generator_manifest)
    control_manifest = _require_mapping(control_manifest, "control manifest")
    control_manifest = validate_control_manifest(
        control_manifest,
        require_bound_empirical=control_manifest.get("evidence_class") == "empirical_local",
    )
    plan, rows = _validate_plan_closed_shape(plan)
    if plan.get("generator_manifest_sha256") != generator_manifest.get("payload_sha256"):
        raise Stage2Error("plan generator binding mismatch")
    if plan.get("control_manifest_sha256") != control_manifest.get("payload_sha256"):
        raise Stage2Error("plan control binding mismatch")
    if plan.get("stage1_join_head") != control_manifest.get("stage1_join_head"):
        raise Stage2Error("plan Stage 1 join binding mismatch")

    expected_cases = {case["case_id"]: case for case in generator_manifest["cases"]}
    expected_controls = {control["control_id"]: control for control in control_manifest["controls"]}
    observed_ids: set[str] = set()
    observed_cells: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        observation_id = row.get("observation_id")
        if not isinstance(observation_id, str) or not re.fullmatch(r"s2obs_[0-9a-f]{24}", observation_id):
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
    control_manifest = _require_mapping(control_manifest, "control manifest")
    control_manifest = validate_control_manifest(
        control_manifest,
        require_bound_empirical=control_manifest.get("evidence_class") == "empirical_local",
    )
    plan, _ = _validate_plan_closed_shape(plan)
    if plan.get("control_manifest_sha256") != control_manifest.get("payload_sha256"):
        raise Stage2Error("plan control binding mismatch")
    if plan.get("stage1_join_head") != control_manifest.get("stage1_join_head"):
        raise Stage2Error("plan Stage 1 join binding mismatch")

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
    for index, row in enumerate(rows):
        _require_exact_keys(row, OBSERVATION_FIELDS, f"observations[{index}]")
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
            "expected_checksum",
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
        if not reconstructed_acceptance:
            raise Stage2Error("every deterministic calibration answer must be accepted")
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
    return rows, evidence_class
