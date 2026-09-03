#!/usr/bin/env python3
"""Build an exact physical RTX 4060/Ollama Anchor Crate backend from measured receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import platform
import sys
from typing import Any, Iterable, Mapping, Sequence

BINDING_SCHEMA = "tier-bench/anchor-ollama-cuda-binding@1"
BACKEND_SCHEMA = "tier-bench/anchor-backend@1"
REGISTRY_SCHEMA = "tier-bench/anchor-backend-registry@1"
ESTATE_RECEIPT_SCHEMA = "axm-community-lab/experiment-receipt@1"
ESTATE_OBSERVATION_SCHEMA = "axm-community-lab/estate-observation@1"
HOST_OBSERVATION_SCHEMA = "axm-community-lab/windows-host-observation@1"
PROBE_SCHEMA = "tier-bench/anchor-4060-physical-probe@1"
FUNCTION_CONTRACT_SCHEMA = "axm-community-lab/function-contract@1"
THERMAL_FAN_CHANNELS = [
    "Pump Fan control/1",
    "System Fan #1 control/2",
    "System Fan #3 control/4",
]
FAN_GOVERNANCE = "PawnIO_LibreHardwareMonitor_holder"
THERMAL_PROFILE_ID = "W01-RTX4060-MENACE-A17-THERMAL-V1"
THERMAL_GPU_UUID = "GPU-e0b1541d-fc7d-38f5-d4c0-c15a3bd241a0"
THERMAL_CONTROL_SCHEMA = "tier-bench/anchor-thermal-control@1"

PROMPT_TEMPLATE = (
    "You are a bounded decision-packet formatter. Use only the supplied readiness state. "
    "Copy asset_id, blockers, and evidence_record_ids exactly. Set claim from physically_available, "
    "write one concise summary, and require human review. Return only the declared JSON schema."
)
DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "asset_id",
        "claim",
        "blockers",
        "evidence_record_ids",
        "summary",
        "requires_human_review",
    ],
    "properties": {
        "asset_id": {"type": "string"},
        "claim": {"type": "string", "enum": ["physically_available", "not_physically_available"]},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "evidence_record_ids": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "requires_human_review": {"type": "boolean"},
    },
}


class BuildError(ValueError):
    """The measured evidence is incomplete, contradictory, or not bound to the target route."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def compact_hash_json(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def receipt_id(receipt: Mapping[str, Any]) -> str:
    body = dict(receipt)
    declared = body.pop("receipt_sha256", None)
    computed = compact_hash_json(body)
    if declared is not None and declared != computed:
        raise BuildError(f"receipt identity mismatch: declared {declared}, computed {computed}")
    return computed


def validate_artifacts(receipt: Mapping[str, Any], receipt_path: Path) -> dict[str, Path]:
    artifacts = receipt.get("artifacts")
    require(isinstance(artifacts, list) and bool(artifacts), f"receipt has no artifacts: {receipt_path}")
    root = receipt_path.parent.resolve()
    result: dict[str, Path] = {}
    for index, raw in enumerate(artifacts):
        require(isinstance(raw, Mapping), f"receipt artifact[{index}] is not an object")
        relative = Path(str(raw.get("path") or ""))
        require(not relative.is_absolute() and ".." not in relative.parts, "receipt artifact path escapes")
        absolute = (root / relative).resolve()
        try:
            absolute.relative_to(root)
        except ValueError as exc:
            raise BuildError("receipt artifact path escapes") from exc
        require(absolute.is_file(), f"receipt artifact missing: {relative}")
        observed = sha256_file(absolute)
        require(observed == raw.get("sha256"), f"receipt artifact digest mismatch: {relative}")
        result[relative.as_posix()] = absolute
    return result


def passed_receipt(
    receipt_path: Path,
    *,
    experiment_id: str,
    required_support: tuple[str, str],
) -> tuple[dict[str, Any], dict[str, Path], str]:
    receipt = load_json(receipt_path)
    require(receipt.get("schema") == ESTATE_RECEIPT_SCHEMA, f"unsupported receipt schema: {receipt_path}")
    require(receipt.get("experiment_id") == experiment_id, f"wrong experiment receipt: {receipt_path}")
    require(receipt.get("status") == "PASS", f"receipt is not PASS: {receipt_path}")
    checks = receipt.get("checks")
    require(isinstance(checks, list) and bool(checks), "receipt checks missing")
    require(all(isinstance(row, Mapping) and row.get("pass") is True for row in checks), "receipt has a failing check")
    supports = receipt.get("supports")
    require(isinstance(supports, list), "receipt supports missing")
    capability, tier = required_support
    require(
        any(isinstance(row, Mapping) and row.get("capability") == capability and row.get("tier") == tier for row in supports),
        f"receipt does not support {capability}@{tier}",
    )
    return receipt, validate_artifacts(receipt, receipt_path), receipt_id(receipt)


def parse_thermal_power(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"(?P<power>\d+(?:\.\d+)?)", value)
    if not match:
        return None
    try:
        return float(match.group("power"))
    except ValueError:
        return None


def passed_thermal_profile(
    receipt_path: Path,
    *,
    expected_sha256: str,
    expected_profile_id: str,
    expected_power_limit_watts: float,
) -> tuple[dict[str, Any], str]:
    observed_sha256 = sha256_file(receipt_path)
    require(observed_sha256 == expected_sha256, f"thermal receipt controlling identity mismatch: {receipt_path}")
    receipt = load_json(receipt_path)
    require(receipt.get("profile_id") == expected_profile_id, f"thermal profile id mismatch: {receipt_path}")
    require(receipt.get("terminal") == "PASS", f"thermal profile did not terminal PASS: {receipt_path}")
    if "pass" in receipt:
        require(receipt.get("pass") is True, f"thermal profile is not pass=true: {receipt_path}")
    if "rerun_required" in receipt:
        require(receipt["rerun_required"] is False, f"thermal profile requires rerun: {receipt_path}")
    if "provider_calls" in receipt:
        require(int(receipt["provider_calls"] or 0) == 0, f"thermal profile made provider calls: {receipt_path}")

    if isinstance(receipt.get("pass_criteria_all_met"), Mapping):
        criteria = receipt["pass_criteria_all_met"]
        if "holder_continuously_active" in criteria:
            require(
                criteria["holder_continuously_active"] is True,
                f"thermal profile holder is not continuously active: {receipt_path}",
            )
        if "every_mapped_case_fan_stable_nonzero_tachometer" in criteria:
            require(
                criteria["every_mapped_case_fan_stable_nonzero_tachometer"] is True,
                f"thermal profile fan tachometer guard is not satisfied: {receipt_path}",
            )

    sources = []
    operating_point = receipt.get("operating_point")
    if isinstance(operating_point, Mapping):
        sources.append(operating_point.get("power_limit_w"))
    elif isinstance(operating_point, str):
        sources.append(operating_point)
    if isinstance(receipt.get("result"), Mapping):
        sources.append(receipt["result"].get("requested_power_limit_w"))
    power_limit = None
    for source in sources:
        candidate = parse_thermal_power(source)
        if candidate is not None:
            power_limit = candidate
            break
    require(power_limit is not None, f"thermal profile power limit is missing: {receipt_path}")
    require(
        abs(float(power_limit) - float(expected_power_limit_watts)) < 1e-6,
        f"thermal profile is not bound to {expected_power_limit_watts}W: {receipt_path}",
    )
    return receipt, observed_sha256


def load_thermal_control(path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    require(bool(re.fullmatch(r"[0-9a-f]{64}", expected_sha256)), "thermal control expected SHA-256 is invalid")
    observed_sha256 = sha256_file(path)
    require(observed_sha256 == expected_sha256, "thermal control manifest controlling identity mismatch")
    control = load_json(path)
    require(control.get("schema") == THERMAL_CONTROL_SCHEMA, "unsupported thermal control manifest schema")
    require(control.get("profile_id") == THERMAL_PROFILE_ID, "thermal control profile identity mismatch")
    receipts = control.get("receipts")
    require(isinstance(receipts, Mapping), "thermal control receipt identities missing")
    for name in ("public_sha256", "private_sha256"):
        require(bool(re.fullmatch(r"[0-9a-f]{64}", str(receipts.get(name) or ""))), f"thermal control {name} is invalid")
    artifacts = control.get("artifacts")
    require(isinstance(artifacts, list) and bool(artifacts), "thermal control artifact identities missing")
    for index, row in enumerate(artifacts):
        require(isinstance(row, Mapping), f"thermal control artifact {index} is invalid")
        artifact_path = Path(str(row.get("path") or ""))
        digest = str(row.get("sha256") or "")
        require(artifact_path.is_file(), f"thermal control artifact is unavailable: {artifact_path}")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", digest)), f"thermal control artifact digest is invalid: {artifact_path}")
        require(sha256_file(artifact_path) == digest, f"thermal control artifact digest mismatch: {artifact_path}")
    return control, observed_sha256


def find_artifact(artifacts: Mapping[str, Path], suffix: str) -> Path:
    matches = [path for name, path in artifacts.items() if name == suffix or name.endswith("/" + suffix)]
    require(len(matches) == 1, f"expected exactly one receipt artifact ending in {suffix}, found {len(matches)}")
    return matches[0]


def runtime_map(observation: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = observation.get("runtime")
    require(isinstance(rows, list), "host runtime inventory missing")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in rows:
        require(isinstance(raw, Mapping), "host runtime row is not an object")
        name = str(raw.get("name") or "")
        require(name and name not in result, f"invalid or duplicate runtime identity: {name!r}")
        result[name] = raw
    return result


def select_gpu(observation: Mapping[str, Any], requested_uuid: str | None) -> dict[str, Any]:
    graphics = observation.get("graphics")
    require(isinstance(graphics, Mapping), "host graphics inventory missing")
    rows = graphics.get("nvidia")
    require(isinstance(rows, list), "host NVIDIA inventory missing")
    candidates = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping)
        and "RTX 4060" in str(row.get("name") or "").upper()
        and (requested_uuid is None or row.get("uuid") == requested_uuid)
    ]
    require(len(candidates) == 1, f"expected one exact RTX 4060 identity, found {len(candidates)}")
    gpu = candidates[0]
    for key in ("uuid", "name", "vbios_version", "memory_total_mib", "driver_version", "pci_bus_id", "power_limit_watts"):
        require(gpu.get(key) not in {None, ""}, f"RTX 4060 identity is missing {key}")
    require(int(gpu["memory_total_mib"]) >= 7000, "RTX 4060 memory envelope is unexpectedly small")
    return gpu


def validate_probe(
    probe_path: Path,
    *,
    gpu: Mapping[str, Any],
    model: str,
    model_digest: str,
    endpoint: str,
    thermal_control: Mapping[str, Any],
    thermal_control_sha256: str,
) -> tuple[dict[str, Any], str]:
    probe = load_json(probe_path)
    require(probe.get("schema") == PROBE_SCHEMA, "unsupported physical probe schema")
    require(probe.get("status") == "PASS", "physical probe is not PASS")
    require(probe.get("production_claim") is False, "physical probe cannot claim production")
    checks = probe.get("checks")
    require(isinstance(checks, list) and bool(checks), "physical probe checks missing")
    require(all(isinstance(row, Mapping) and row.get("pass") is True for row in checks), "physical probe has a failing check")
    require(probe.get("endpoint") == endpoint, "physical probe endpoint differs from function contract")
    observed_gpu = probe.get("gpu")
    observed_ollama = probe.get("ollama")
    require(isinstance(observed_gpu, Mapping) and isinstance(observed_ollama, Mapping), "physical probe identity objects missing")
    for key in ("uuid", "name", "vbios_version", "memory_total_mib", "driver_version", "pci_bus_id"):
        require(str(observed_gpu.get(key)) == str(gpu.get(key)), f"physical probe GPU {key} differs from census")
    require(observed_ollama.get("model") == model, "physical probe model name differs")
    require(observed_ollama.get("model_digest") == model_digest, "physical probe model digest differs")
    require(isinstance(observed_ollama.get("size_vram"), int) and observed_ollama["size_vram"] >= 2 * 1024**3, "physical probe did not establish accelerator residency")
    require(isinstance(observed_gpu.get("memory_used_mib"), (int, float)) and observed_gpu["memory_used_mib"] >= 1024, "physical probe did not establish GPU memory residency")
    thermal = probe.get("thermal_profile")
    require(isinstance(thermal, Mapping), "physical probe thermal profile binding missing")
    require(thermal.get("profile_id") == THERMAL_PROFILE_ID, "physical probe thermal profile identity differs")
    receipts = thermal_control["receipts"]
    require(thermal.get("public_receipt_sha256") == receipts["public_sha256"], "physical probe public thermal receipt digest differs")
    require(thermal.get("private_receipt_sha256") == receipts["private_sha256"], "physical probe private thermal receipt digest differs")
    require(thermal.get("control_manifest_observed_sha256") == thermal_control_sha256, "physical probe thermal control observed digest differs")
    require(thermal.get("control_manifest_expected_sha256") == thermal_control_sha256, "physical probe thermal control authority differs")
    require(thermal.get("fan_governance") == FAN_GOVERNANCE, "physical probe fan holder governance differs")
    holder = thermal.get("holder")
    require(isinstance(holder, Mapping) and holder.get("active") is True, "physical probe holder is not active")
    accepted_holder = thermal_control.get("holder")
    require(isinstance(accepted_holder, Mapping), "thermal control holder identities missing")
    for identity in ("executable", "lhm", "pawnio", "policy"):
        measured = holder.get(identity)
        accepted = accepted_holder.get(identity)
        require(isinstance(measured, Mapping) and isinstance(accepted, Mapping), f"physical probe {identity} identity missing")
        require(str(measured.get("path")).lower() == str(accepted.get("path")).lower(), f"physical probe {identity} path differs")
        require(measured.get("sha256") == accepted.get("sha256"), f"physical probe {identity} digest differs")
    require(isinstance(holder.get("sensor_age_seconds"), (int, float)) and holder["sensor_age_seconds"] <= 12, "physical probe holder sensors are stale")
    fan_rows = thermal.get("fan_channels")
    require(isinstance(fan_rows, list) and len(fan_rows) == len(THERMAL_FAN_CHANNELS), "physical probe fan map is incomplete")
    require(
        {str(row.get("channel")) for row in fan_rows if isinstance(row, Mapping)} == set(THERMAL_FAN_CHANNELS),
        "physical probe fan map differs from the thermal profile",
    )
    accepted_fans = {
        str(row.get("channel")): row
        for row in thermal_control.get("fan_channels", [])
        if isinstance(row, Mapping)
    }
    require(
        all(
            isinstance(row, Mapping)
            and row.get("control_identity") == accepted_fans.get(str(row.get("channel")), {}).get("control_identity")
            and row.get("tachometer_sensor_identity") == accepted_fans.get(str(row.get("channel")), {}).get("tachometer_sensor_identity")
            and isinstance(row.get("tachometer_rpm"), (int, float))
            and row["tachometer_rpm"] > 0
            and isinstance(row.get("timestamp"), str)
            and bool(row["timestamp"])
            for row in fan_rows
        ),
        "physical probe fan tachometer confirmation is incomplete",
    )
    artifacts = thermal.get("coverage_artifacts")
    require(artifacts == thermal_control.get("artifacts"), "physical probe thermal artifact identities differ from control manifest")
    require(isinstance(artifacts, list) and len(artifacts) >= 8, "thermal covered-artifact set is incomplete")
    for row in artifacts:
        require(isinstance(row, Mapping), "thermal covered-artifact row is invalid")
        path = Path(str(row.get("path") or ""))
        digest = str(row.get("sha256") or "")
        require(path.is_file() and len(digest) == 64, f"thermal covered artifact is unavailable: {path}")
        require(sha256_file(path) == digest, f"thermal covered-artifact digest drift: {path}")
    power = probe.get("power_control")
    require(isinstance(power, Mapping), "physical probe power-control evidence missing")
    require(float(power.get("default_watts", 0)) == 115.0, "physical probe GPU default power identity differs")
    require(float(power.get("minimum_watts", 999)) <= 90.0, "90 W is outside the bound card legal range")
    require(float(power.get("applied_watts", 0)) == 90.0 and power.get("application_result") == "PASS", "physical probe did not prove exact 90 W application")
    inventory = probe.get("gpu_inventory_before")
    require(isinstance(inventory, list) and bool(inventory), "physical probe did not enumerate NVIDIA GPUs")
    require(any(isinstance(row, Mapping) and row.get("uuid") == gpu["uuid"] for row in inventory), "physical probe inventory omits target GPU")
    dedicated = probe.get("dedicated_server")
    require(isinstance(dedicated, Mapping), "physical probe dedicated process identity missing")
    root_pid = dedicated.get("pid")
    process_tree = dedicated.get("process_tree")
    require(isinstance(root_pid, int) and root_pid > 0, "dedicated Ollama root PID is invalid")
    require(isinstance(process_tree, list) and bool(process_tree), "dedicated Ollama process tree is missing")
    process_pids = {row.get("pid") for row in process_tree if isinstance(row, Mapping)}
    require(root_pid in process_pids, "dedicated Ollama process tree omits its root")
    for row in process_tree:
        require(isinstance(row, Mapping), "dedicated Ollama process row is invalid")
        require(isinstance(row.get("pid"), int) and row["pid"] > 0, "dedicated Ollama process PID is invalid")
        require(isinstance(row.get("parent_pid"), int) and row["parent_pid"] >= 0, "dedicated Ollama parent PID is invalid")
        require(isinstance(row.get("executable_path"), str) and row["executable_path"], "dedicated Ollama executable path missing")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", str(row.get("executable_sha256") or ""))), "dedicated Ollama executable digest missing")
        require(sha256_file(Path(row["executable_path"])) == row["executable_sha256"], "dedicated Ollama executable digest differs")
        require(isinstance(row.get("creation_time"), str) and row["creation_time"], "dedicated Ollama creation time missing")
    root_row = next(row for row in process_tree if isinstance(row, Mapping) and row.get("pid") == root_pid)
    require(str(root_row["executable_path"]).lower() == str(dedicated.get("executable")).lower(), "dedicated Ollama root executable differs")
    require(root_row["executable_sha256"] == dedicated.get("executable_sha256"), "dedicated Ollama root executable digest differs")
    require(root_row["creation_time"] == dedicated.get("creation_time"), "dedicated Ollama root creation time differs")
    descendants = {root_pid}
    while True:
        added = {
            row["pid"]
            for row in process_tree
            if isinstance(row, Mapping) and row.get("parent_pid") in descendants
        } - descendants
        if not added:
            break
        descendants.update(added)
    require(descendants == process_pids, "dedicated Ollama process rows do not form one rooted descendant tree")
    compute_rows = observed_gpu.get("compute_processes")
    require(isinstance(compute_rows, list), "physical probe compute-process evidence missing")
    target_rows = [row for row in compute_rows if isinstance(row, Mapping) and row.get("gpu_uuid") == gpu["uuid"]]
    require(any(row.get("pid") in process_pids and float(row.get("used_memory_mib") or 0) > 0 for row in target_rows), "target GPU process is not a member of the dedicated Ollama tree")
    return probe, sha256_file(probe_path)


def build(
    *,
    base_registry_path: Path,
    estate_receipt_path: Path,
    estate_observation_path: Path,
    control_host_observation_path: Path,
    function_receipt_path: Path,
    physical_probe_path: Path,
    executor_path: Path,
    python_executable: Path,
    output_dir: Path,
    backend_id: str,
    gpu_uuid: str | None,
    thermal_profile_public_receipt_path: Path | None = None,
    thermal_profile_private_receipt_path: Path | None = None,
    thermal_control_manifest_path: Path | None = None,
    expected_thermal_control_manifest_sha256: str | None = None,
    thermal_target_power_limit_watts: float = 90.0,
) -> dict[str, Any]:
    estate_receipt, estate_artifacts, estate_receipt_sha = passed_receipt(
        estate_receipt_path,
        experiment_id="capture-estate-snapshot",
        required_support=("device_identity", "observed"),
    )
    function_receipt, function_artifacts, function_receipt_sha = passed_receipt(
        function_receipt_path,
        experiment_id="freeze-one-function",
        required_support=("function_contract", "qualified"),
    )
    require(thermal_control_manifest_path is not None and expected_thermal_control_manifest_sha256 is not None, "externally bound thermal control manifest is required")
    thermal_control, thermal_control_sha = load_thermal_control(
        thermal_control_manifest_path,
        expected_thermal_control_manifest_sha256,
    )
    require(thermal_profile_public_receipt_path is not None and thermal_profile_private_receipt_path is not None, "both thermal profile receipts are required for physical route construction")
    thermal_public, thermal_public_sha = passed_thermal_profile(
        thermal_profile_public_receipt_path,  # type: ignore[arg-type]
        expected_sha256=str(thermal_control["receipts"]["public_sha256"]),
        expected_profile_id=THERMAL_PROFILE_ID,
        expected_power_limit_watts=thermal_target_power_limit_watts,
    )
    thermal_private, thermal_private_sha = passed_thermal_profile(
        thermal_profile_private_receipt_path,  # type: ignore[arg-type]
        expected_sha256=str(thermal_control["receipts"]["private_sha256"]),
        expected_profile_id=THERMAL_PROFILE_ID,
        expected_power_limit_watts=thermal_target_power_limit_watts,
    )
    require(
        thermal_public["profile_id"] == thermal_private["profile_id"],
        "thermal profile public/private IDs must agree",
    )

    estate_observation = load_json(estate_observation_path)
    control_observation = load_json(control_host_observation_path)
    require(estate_observation.get("schema") == ESTATE_OBSERVATION_SCHEMA, "unsupported estate observation schema")
    require(control_observation.get("schema") == HOST_OBSERVATION_SCHEMA, "unsupported host observation schema")
    require(control_observation.get("host_id") == "control-host", "physical backend must bind the control-host observation")
    require(estate_observation_path.resolve() in estate_artifacts.values(), "estate observation is not covered by the estate receipt")
    require(control_host_observation_path.resolve() in estate_artifacts.values(), "control-host observation is not covered by the estate receipt")
    require(estate_observation.get("host_count_observed") == 3, "three-host census is incomplete")
    require(estate_observation.get("accelerator_domains_resolved") == estate_observation.get("accelerator_domains_expected"), "accelerator census is incomplete")
    unresolved = estate_observation.get("unresolved")
    require(isinstance(unresolved, Mapping) and all(not unresolved.get(key) for key in unresolved), "estate observation contains unresolved census defects")

    contract_path = find_artifact(function_artifacts, "function-contract.json")
    contract = load_json(contract_path)
    require(contract.get("schema") == FUNCTION_CONTRACT_SCHEMA, "unsupported function contract schema")
    implementation = contract.get("implementation")
    require(isinstance(implementation, Mapping), "function implementation missing")
    model = str(implementation.get("model") or "")
    endpoint = str(implementation.get("endpoint") or "")
    require(model == "qwen3.5:9b-q4_K_M", "function contract is not the frozen 4060 Qwen route")
    require(endpoint.startswith("http://127.0.0.1:") or endpoint.startswith("http://localhost:"), "function endpoint is not loopback")
    output_paths = [path for name, path in function_artifacts.items() if name.endswith("/output.json")]
    require(len(output_paths) >= 2, "function receipt contains fewer than two valid outputs")
    outputs = [load_json(path) for path in sorted(output_paths)]
    digests = {row.get("model_digest") for row in outputs}
    models = {row.get("model") for row in outputs}
    require(len(digests) == 1 and None not in digests and "" not in digests, "function outputs did not retain one exact model digest")
    require(models == {model}, "function outputs changed the model identity")
    model_digest = str(next(iter(digests)))

    require(gpu_uuid == THERMAL_GPU_UUID, "physical route requires the exact thermally qualified RTX 4060 UUID")
    gpu = select_gpu(control_observation, gpu_uuid)
    accepted_gpu = thermal_control.get("gpu")
    require(isinstance(accepted_gpu, Mapping), "thermal control GPU identity missing")
    for key in ("uuid", "name", "vbios_version", "driver_version", "pci_bus_id"):
        require(str(accepted_gpu.get(key)) == str(gpu.get(key)), f"thermal control GPU {key} identity differs")
    accepted_model = thermal_control.get("model")
    require(isinstance(accepted_model, Mapping), "thermal control model identity missing")
    require(accepted_model.get("name") == model and accepted_model.get("digest") == model_digest, "thermal control model identity differs")
    accepted_power = thermal_control.get("power")
    require(isinstance(accepted_power, Mapping), "thermal control power identity missing")
    require(float(accepted_power.get("target_watts", 0)) == float(thermal_target_power_limit_watts), "thermal control target power differs")
    require(float(accepted_power.get("default_watts", 0)) == 115.0, "thermal control default power differs")
    accepted_workload = thermal_control.get("workload")
    require(isinstance(accepted_workload, Mapping), "thermal control workload identity missing")
    require(accepted_workload.get("workers") == 2 and accepted_workload.get("sustained_seconds") == 900, "thermal control workload identity differs")
    probe, probe_sha = validate_probe(
        physical_probe_path,
        gpu=gpu,
        model=model,
        model_digest=model_digest,
        endpoint=endpoint,
        thermal_control=thermal_control,
        thermal_control_sha256=thermal_control_sha,
    )
    runtimes = runtime_map(control_observation)
    for name in ("python", "ollama", "nvidia-smi"):
        row = runtimes.get(name)
        require(isinstance(row, Mapping) and row.get("present") is True and row.get("disabled") is False, f"required runtime is not enabled: {name}")
        require(isinstance(row.get("path"), str) and row["path"], f"required runtime path missing: {name}")
    accepted_runtime = thermal_control.get("runtime")
    require(isinstance(accepted_runtime, Mapping), "thermal control runtime identities missing")
    for census_name, control_name in (("python", "python"), ("ollama", "ollama"), ("nvidia-smi", "nvidia_smi")):
        accepted = accepted_runtime.get(control_name)
        require(isinstance(accepted, Mapping), f"thermal control {control_name} runtime identity missing")
        runtime_path = Path(str(runtimes[census_name]["path"])).resolve()
        require(str(runtime_path).lower() == str(Path(str(accepted.get("path"))).resolve()).lower(), f"thermal control {control_name} runtime path differs")
        require(sha256_file(runtime_path) == accepted.get("sha256"), f"thermal control {control_name} runtime digest differs")
    require(Path(str(runtimes["python"]["path"])).name.lower().startswith("python"), "census Python path is invalid")
    require(str(python_executable).lower() == str(runtimes["python"]["path"]).lower(), "selected Python executable differs from census")
    require(executor_path.is_file(), "physical executor script is missing")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    binding_path = output_dir / "physical-binding.json"
    evidence_log = output_dir / "physical-executor-events.jsonl"
    executor_sha = sha256_file(executor_path)
    model_details = probe["ollama"].get("details") if isinstance(probe["ollama"].get("details"), Mapping) else {}
    context_length = int(model_details.get("context_length") or probe["ollama"].get("context_length") or 8192)
    model_size = int(probe["ollama"].get("model_size_bytes") or 0)
    require(model_size > 0, "physical probe model size is missing")
    min_size_vram = int(probe["ollama"]["size_vram"])
    python_version = str(probe.get("python_version") or platform.python_version())
    ollama_version = str(probe["ollama"].get("version") or "")
    require(ollama_version, "physical probe Ollama version is missing")
    require(accepted_runtime.get("ollama_version") == ollama_version, "thermal control Ollama version differs")

    lowering = {
        "operation": "decision.generate",
        "prompt_template_sha256": hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest(),
        "output_schema_sha256": hash_json(DECISION_SCHEMA),
        "executor_sha256": executor_sha,
        "model_digest": model_digest,
    }
    lowering_sha = hash_json(lowering)
    source_receipts = {
        "estate_receipt_sha256": estate_receipt_sha,
        "function_receipt_sha256": function_receipt_sha,
        "physical_probe_sha256": probe_sha,
        "estate_observation_sha256": sha256_file(estate_observation_path),
        "control_host_observation_sha256": sha256_file(control_host_observation_path),
        "function_contract_sha256": sha256_file(contract_path),
        "thermal_profile_public_receipt_sha256": thermal_public_sha,
        "thermal_profile_private_receipt_sha256": thermal_private_sha,
        "thermal_profile_public_controlling_sha256": str(thermal_control["receipts"]["public_sha256"]),
        "thermal_profile_private_controlling_sha256": str(thermal_control["receipts"]["private_sha256"]),
        "thermal_control_manifest_observed_sha256": thermal_control_sha,
        "thermal_control_manifest_expected_sha256": expected_thermal_control_manifest_sha256,
    }
    binding: dict[str, Any] = {
        "schema": BINDING_SCHEMA,
        "backend_id": backend_id,
        "capabilities": ["candidate-generation", "llm-inference", "structured-json"],
        "source_receipts": source_receipts,
        "host": {
            "host_id": "control-host",
            "computer_name": control_observation["system"]["computer_name"],
        },
        "gpu": {
            "uuid": gpu["uuid"],
            "name": gpu["name"],
            "architecture": "cuda-sm89",
            "isa": "NVIDIA Ada SM89",
            "memory_total_mib": int(gpu["memory_total_mib"]),
            "min_loaded_memory_mib": max(1024, int(math.floor(min_size_vram / 1024**2 * 0.75))),
            "driver_version": str(gpu["driver_version"]),
            "pci_bus_id": str(gpu["pci_bus_id"]),
            "vbios_version": str(gpu["vbios_version"]),
            "power_limit_watts": float(gpu["power_limit_watts"]),
        },
        "runtime": {
            "python_executable": str(python_executable.resolve()),
            "python_version": python_version,
            "ollama_executable": str(runtimes["ollama"]["path"]),
            "ollama_version": ollama_version,
            "endpoint": endpoint,
            "model": model,
            "model_digest": model_digest,
            "model_size_bytes": model_size,
            "quantization": str(model_details.get("quantization_level") or "Q4_K_M"),
            "context_length": min(context_length, 32768),
            "keep_alive": "10m",
            "probe_timeout_seconds": 10,
            "inference_timeout_seconds": 180,
            "min_size_vram_bytes": min_size_vram,
        },
        "execution": {
            "executor_path": str(executor_path.resolve()),
            "executor_sha256": executor_sha,
            "backend_family": "cuda",
            "nvidia_smi_path": str(runtimes["nvidia-smi"]["path"]),
            "nvidia_smi_command": (
                list(probe.get("nvidia_smi_command"))
                if isinstance(probe.get("nvidia_smi_command"), list)
                and probe.get("nvidia_smi_command")
                and all(isinstance(item, str) and item for item in probe["nvidia_smi_command"])
                else [str(runtimes["nvidia-smi"]["path"])]
            ),
            "dedicated_ollama_server": True,
            "cuda_visible_devices": gpu["uuid"],
            "ollama_vulkan": "0",
            "power_limit_target_watts": thermal_target_power_limit_watts,
            "thermal_profile_id": THERMAL_PROFILE_ID,
            "thermal_profile_receipt_sha256": thermal_private_sha,
            "thermal_profile_public_receipt_sha256": thermal_public_sha,
            "thermal_profile_public_receipt_path": str(thermal_profile_public_receipt_path.resolve()),
            "thermal_profile_private_receipt_path": str(thermal_profile_private_receipt_path.resolve()),
            "thermal_control_manifest_path": str(thermal_control_manifest_path.resolve()),
            "thermal_control_manifest_observed_sha256": thermal_control_sha,
            "thermal_control_manifest_expected_sha256": expected_thermal_control_manifest_sha256,
            "thermal_coverage_artifacts": list(probe["thermal_profile"]["coverage_artifacts"]),
            "thermal_holder": dict(probe["thermal_profile"]["holder"]),
            "thermal_fan_channels": list(probe["thermal_profile"]["fan_channels"]),
            "gpu_inventory_baseline_mib": {
                str(row["uuid"]): float(row.get("memory_used_mib") or 0)
                for row in probe["gpu_inventory_before"]
                if isinstance(row, Mapping)
            },
            "ollama_process_tree": list(probe["dedicated_server"]["process_tree"]),
            "ollama_root_pid": int(probe["dedicated_server"]["pid"]),
            "process_inventory_command": list(probe.get("process_inventory_command") or []),
            "fan_channels": THERMAL_FAN_CHANNELS,
            "fan_governance": FAN_GOVERNANCE,
            "evidence_log": str(evidence_log),
        },
        "lowering": {**lowering, "lowering_sha256": lowering_sha},
        "physical_qualification": True,
        "production_claim": False,
        "promotion_authorized": False,
    }
    binding_sha = hash_json(binding)
    write_json(binding_path, binding)

    base_registry = load_json(base_registry_path)
    require(base_registry.get("schema") == REGISTRY_SCHEMA, "unsupported base backend registry")
    rows = base_registry.get("backends")
    require(isinstance(rows, list), "base registry backends missing")
    require(not any(isinstance(row, Mapping) and row.get("id") == backend_id for row in rows), "physical backend already exists in base registry")
    toolchain = {
        "python_version": python_version,
        "ollama_version": ollama_version,
        "nvidia_driver": str(gpu["driver_version"]),
        "executor_sha256": executor_sha,
    }
    backend = {
        "schema": BACKEND_SCHEMA,
        "id": backend_id,
        "title": "Physical RTX 4060 Qwen3.5 Ollama backend",
        "execution_class": "accelerator_driver",
        "architecture": "cuda-sm89",
        "isa": "NVIDIA Ada SM89",
        "backend_family": "cuda",
        "runtime_id": "ollama-cuda",
        "runtime_version": ollama_version,
        "model_identity": f"ollama:{model}@sha256:{model_digest}",
        "model_formats": ["gguf-Q4_K_M"],
        "capabilities": binding["capabilities"],
        "effects": ["none", "local_read"],
        "memory_mib": int(gpu["memory_total_mib"]),
        "storage_mib": max(512, int(math.ceil(model_size / 1024**2)) + 1024),
        "network": "local_only",
        "power_limit_w": int(math.ceil(float(thermal_target_power_limit_watts))),
        "thermal_profile_id": THERMAL_PROFILE_ID,
        "thermal_profile_receipt_sha256": thermal_private_sha,
        "thermal_control_manifest_sha256": thermal_control_sha,
        "fan_governance": FAN_GOVERNANCE,
        "energy_class": 2,
        "preference": 5,
        "telemetry": ["elapsed_ms", "energy_mwh", "memory_peak_mib", "status"],
        "driver_command": [
            str(python_executable.resolve()),
            str(executor_path.resolve()),
            "--backend",
            backend_id,
            "--binding",
            str(binding_path),
            "--expected-binding-sha256",
            binding_sha,
        ],
        "toolchain_sha256": hash_json(toolchain),
        "execution_cartridge_id": f"exec.cuda-sm89-qwen35-{binding_sha[:16]}",
        "execution_cartridge_sha256": binding_sha,
        "lowerings": {"decision.generate": lowering_sha},
        "physical_qualification": True,
        "notes": (
            "Built only from a PASS three-host census, a PASS exact-function replay, and a PASS "
            "dedicated RTX 4060/Ollama residency probe. Task-specific acceptance remains controller-owned."
        ),
    }
    registry = dict(base_registry)
    registry["backends"] = [*rows, backend]
    registry["claim_boundary"] = (
        str(base_registry.get("claim_boundary") or "")
        + " The physical RTX 4060 row is admitted only for the exact measured host, GPU, runtime, model, and binding."
    ).strip()
    registry_path = output_dir / "backend-registry.physical.json"
    write_json(registry_path, registry)

    checks = [
        {"id": "three-host-census-pass", "pass": True, "detail": estate_receipt_sha},
        {"id": "qwen-function-qualified", "pass": True, "detail": function_receipt_sha},
        {"id": "4060-residency-probe-pass", "pass": True, "detail": probe_sha},
        {"id": "exact-model-digest", "pass": True, "detail": model_digest},
        {"id": "binding-content-addressed", "pass": hash_json(binding) == binding_sha, "detail": binding_sha},
        {"id": "no-production-promotion", "pass": not binding["production_claim"] and not binding["promotion_authorized"], "detail": "controller acceptance remains downstream"},
    ]
    build_receipt = {
        "schema": "tier-bench/anchor-physical-backend-build@1",
        "status": "PASS",
        "backend_id": backend_id,
        "backend_manifest_sha256": hash_json(backend),
        "binding_sha256": binding_sha,
        "dedicated_ollama_process": {
            "root_pid": int(probe["dedicated_server"]["pid"]),
            "process_tree": list(probe["dedicated_server"]["process_tree"]),
        },
        "checks": checks,
        "artifacts": [
            {"path": binding_path.name, "sha256": sha256_file(binding_path), "bytes": binding_path.stat().st_size},
            {"path": registry_path.name, "sha256": sha256_file(registry_path), "bytes": registry_path.stat().st_size},
        ],
        "source_receipts": source_receipts,
        "physical_qualification": True,
        "production_claim": False,
        "promotion_authorized": False,
    }
    build_receipt["receipt_sha256"] = hash_json(build_receipt)
    receipt_path = output_dir / "physical-backend-build-receipt.json"
    write_json(receipt_path, build_receipt)
    sums = []
    for path in sorted((binding_path, registry_path, receipt_path), key=lambda item: item.name):
        sums.append(f"{sha256_file(path)}  {path.name}")
    (output_dir / "SHA256SUMS").write_bytes(("\n".join(sums) + "\n").encode("utf-8"))
    return {
        "ok": True,
        "backend_id": backend_id,
        "backend_manifest_sha256": hash_json(backend),
        "binding_sha256": binding_sha,
        "binding": str(binding_path),
        "registry": str(registry_path),
        "receipt": str(receipt_path),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--base-registry", type=Path, required=True)
    result.add_argument("--estate-receipt", type=Path, required=True)
    result.add_argument("--estate-observation", type=Path, required=True)
    result.add_argument("--control-host-observation", type=Path, required=True)
    result.add_argument("--function-receipt", type=Path, required=True)
    result.add_argument("--physical-probe", type=Path, required=True)
    result.add_argument("--executor", type=Path, required=True)
    result.add_argument("--python", type=Path, default=Path(sys.executable))
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--backend-id", default="backend.cuda4060-qwen35-physical")
    result.add_argument("--thermal-profile-public-receipt", type=Path, required=True)
    result.add_argument("--thermal-profile-private-receipt", type=Path, required=True)
    result.add_argument("--thermal-control-manifest", type=Path, required=True)
    result.add_argument("--expected-thermal-control-manifest-sha256", required=True)
    result.add_argument("--thermal-target-power-limit-watts", type=float, default=90.0)
    result.add_argument("--gpu-uuid")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        output = build(
            base_registry_path=args.base_registry.resolve(),
            estate_receipt_path=args.estate_receipt.resolve(),
            estate_observation_path=args.estate_observation.resolve(),
            control_host_observation_path=args.control_host_observation.resolve(),
            function_receipt_path=args.function_receipt.resolve(),
            physical_probe_path=args.physical_probe.resolve(),
            executor_path=args.executor.resolve(),
            python_executable=args.python.resolve(),
            output_dir=args.output_dir.resolve(),
            backend_id=args.backend_id,
            gpu_uuid=args.gpu_uuid,
            thermal_profile_public_receipt_path=args.thermal_profile_public_receipt,
            thermal_profile_private_receipt_path=args.thermal_profile_private_receipt,
            thermal_control_manifest_path=args.thermal_control_manifest,
            expected_thermal_control_manifest_sha256=args.expected_thermal_control_manifest_sha256,
            thermal_target_power_limit_watts=args.thermal_target_power_limit_watts,
        )
    except (BuildError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"build-anchor-4060: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
