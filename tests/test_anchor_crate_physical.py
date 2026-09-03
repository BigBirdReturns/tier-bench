#!/usr/bin/env python3
"""Provider-free laws for the physical RTX 4060 Anchor Crate backend."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_anchor_4060_manifest import BuildError, build as build_manifest  # noqa: E402
from tier_runner.anchor_crate_plan import compile_plan  # noqa: E402
from tier_runner.anchor_crate_runtime import backend_conformance, run_cartridge  # noqa: E402
from tier_runner.anchor_crate_schema import validate_backend_registry  # noqa: E402

FIXTURE = ROOT / "labs" / "community-home-lab" / "anchor-crate"
EXECUTOR = ROOT / "examples" / "anchor_crate" / "ollama_4060_executor.py"
MODEL = "qwen3.5:9b-q4_K_M"
MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
GPU_UUID = "GPU-e0b1541d-fc7d-38f5-d4c0-c15a3bd241a0"
OFFTARGET_UUID = "GPU-OTHER-FIXTURE"
THERMAL_PROFILE_ID = "W01-RTX4060-MENACE-A17-THERMAL-V1"
THERMAL_FAN_CHANNELS = [
    "Pump Fan control/1",
    "System Fan #1 control/2",
    "System Fan #3 control/4",
]
FAN_GOVERNANCE = "PawnIO_LibreHardwareMonitor_holder"

spec = importlib.util.spec_from_file_location("ollama_4060_executor", EXECUTOR)
assert spec and spec.loader
executor_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor_module)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(**kwargs: Any) -> dict[str, Any]:
    control_path = Path(kwargs["physical_probe_path"]).parent / "thermal-control-manifest.json"
    kwargs["thermal_control_manifest_path"] = control_path
    kwargs["expected_thermal_control_manifest_sha256"] = file_sha(control_path)
    return build_manifest(**kwargs)


def compact_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def make_receipt(
    root: Path,
    *,
    experiment_id: str,
    supports: list[dict[str, str]],
    artifacts: list[Path],
) -> Path:
    rows = []
    for path in artifacts:
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": file_sha(path),
                "bytes": path.stat().st_size,
            }
        )
    receipt: dict[str, Any] = {
        "schema": "axm-community-lab/experiment-receipt@1",
        "experiment_id": experiment_id,
        "status": "PASS",
        "generated_at": "2026-08-05T00:00:00Z",
        "checks": [{"id": "fixture-pass", "pass": True, "detail": "provider-free fixture"}],
        "artifacts": rows,
        "supports": supports,
        "metadata": {},
        "claim_boundary": "Provider-free physical-binding contract fixture only.",
    }
    receipt["receipt_sha256"] = compact_hash(receipt)
    path = root / "experiment.receipt.json"
    write_json(path, receipt)
    return path


def make_thermal_receipt(
    root: Path,
    *,
    public: bool,
    power_limit_w: float = 90.0,
    pass_profile: bool = True,
    profile_id: str = THERMAL_PROFILE_ID,
    holder_continuously_active: bool = True,
    fan_tachometer_ok: bool = True,
    rerun_required: bool = False,
) -> Path:
    if public:
        receipt = {
            "receipt": "W01-RTX4060-THERMAL-QUALIFICATION-PUBLIC",
            "program": "EOC007/OPERATOR-UNBLOCK-01",
            "profile_id": profile_id,
            "host": "OCTO-W01",
            "terminal": "PASS" if pass_profile else "HOLD",
            "pass": pass_profile,
            "one_line": "provider fixture",
            "operating_point": f"PL {int(power_limit_w)}W (fixture)",
            "spend": 0,
            "provider_calls": 0,
            "authorizes_a17_smoke": pass_profile,
            "rerun_required": rerun_required,
        }
    else:
        receipt = {
            "receipt": "W01-RTX4060-THERMAL-QUALIFICATION-PRIVATE",
            "program": "EOC007/OPERATOR-UNBLOCK-01",
            "profile_id": profile_id,
            "terminal": "PASS" if pass_profile else "HOLD",
            "authorizes_a17": "yes" if pass_profile else "no",
            "result": {"aborted": False},
            "operating_point": {"power_limit_w": power_limit_w},
            "pass_criteria_all_met": {
                "holder_continuously_active": holder_continuously_active,
                "every_mapped_case_fan_stable_nonzero_tachometer": fan_tachometer_ok,
            },
            "rerun_required": rerun_required,
            "provider_calls": 0,
            "spend": 0,
            "stages": {},
        }
    path = root / ("thermal-profile-public.json" if public else "thermal-profile-private.json")
    write_json(path, receipt)
    return path


class FakeState:
    loaded = True
    generated = 0
    state_path: Path | None = None


class FakeOllamaHandler(BaseHTTPRequestHandler):
    server_version = "FakeOllama/1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, value: Any, status: int = 200) -> None:
        payload = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/version":
            self._json({"version": "0.11.10-fixture"})
        elif self.path == "/api/tags":
            self._json(
                {
                    "models": [
                        {
                            "name": MODEL,
                            "model": MODEL,
                            "digest": MODEL_DIGEST,
                            "size": 6_594_474_711,
                            "details": {
                                "family": "qwen35",
                                "parameter_size": "9.7B",
                                "quantization_level": "Q4_K_M",
                            },
                        }
                    ]
                }
            )
        elif self.path == "/api/ps":
            rows = []
            if FakeState.loaded:
                rows.append(
                    {
                        "name": MODEL,
                        "model": MODEL,
                        "digest": MODEL_DIGEST,
                        "size": 6_594_474_711,
                        "size_vram": 6_442_450_944,
                        "context_length": 8192,
                    }
                )
            self._json({"models": rows})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/generate":
            assert body["model"] == MODEL
            assert isinstance(body.get("format"), dict)
            FakeState.generated += 1
            candidate = {
                "asset_id": "A-17",
                "claim": "not_physically_available",
                "blockers": [
                    "on-hand part is not serviceable",
                    "maintenance work order remains open",
                    "replacement due-in is delayed",
                ],
                "evidence_record_ids": ["due-001", "inv-001", "wo-001"],
                "summary": "A-17 remains unavailable under the source-bound readiness constraints.",
                "requires_human_review": True,
            }
            self._json(
                {
                    "model": MODEL,
                    "response": json.dumps(candidate),
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 50,
                    "eval_count": 40,
                    "total_duration": 1_500_000_000,
                    "load_duration": 10_000_000,
                    "prompt_eval_duration": 300_000_000,
                    "eval_duration": 1_000_000_000,
                }
            )
        elif self.path == "/api/show":
            self._json(
                {
                    "details": {
                        "family": "qwen35",
                        "parameter_size": "9.7B",
                        "quantization_level": "Q4_K_M",
                    },
                    "model_info": {"qwen35.context_length": 262144},
                }
            )
        else:
            self._json({"error": "not found"}, 404)


@contextmanager
def fake_ollama() -> Iterator[str]:
    FakeState.loaded = True
    FakeState.generated = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    names = ("OLLAMA_HOST", "CUDA_VISIBLE_DEVICES", "OLLAMA_VULKAN", "OLLAMA_KEEP_ALIVE", "OLLAMA_SCHED_SPREAD")
    saved = {name: os.environ.get(name) for name in names}
    os.environ["OLLAMA_HOST"] = endpoint.removeprefix("http://")
    os.environ["CUDA_VISIBLE_DEVICES"] = GPU_UUID
    os.environ["OLLAMA_VULKAN"] = "0"
    os.environ["OLLAMA_KEEP_ALIVE"] = "10m"
    os.environ.pop("OLLAMA_SCHED_SPREAD", None)
    try:
        yield endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def fake_nvidia_script(root: Path) -> Path:
    path = root / "fake_nvidia_smi.py"
    state = root / "fake_nvidia_state.json"
    normalized_state_path = state.as_posix()
    state.write_text(
        json.dumps(
            {
                "gpu_row": {
                    "uuid": GPU_UUID,
                    "name": "NVIDIA GeForce RTX 4060",
                    "vbios_version": "95.07.29.00.A9",
                    "memory_total_mib": 8188,
                    "memory_used_mib": 6500,
                    "driver_version": "580.97",
                    "pci_bus_id": "00000000:01:00.0",
                    "pstate": "P2",
                    "power_limit_watts": 90.0,
                    "power_min_limit_watts": 70.0,
                    "power_max_limit_watts": 150.0,
                    "power_default_limit_watts": 115.0,
                },
                "gpu_rows": [
                    {
                        "uuid": GPU_UUID,
                        "name": "NVIDIA GeForce RTX 4060",
                        "vbios_version": "95.07.29.00.A9",
                        "memory_total_mib": 8188,
                        "memory_used_mib": 6500,
                        "driver_version": "580.97",
                        "pci_bus_id": "00000000:01:00.0",
                        "pstate": "P2",
                        "power_limit_watts": 90.0,
                    },
                    {
                        "uuid": OFFTARGET_UUID,
                        "name": "NVIDIA GeForce RTX 3090",
                        "vbios_version": "94.02.42.00.01",
                        "memory_total_mib": 24576,
                        "memory_used_mib": 128,
                        "driver_version": "580.97",
                        "pci_bus_id": "00000000:02:00.0",
                        "pstate": "P8",
                        "power_limit_watts": 350.0,
                    },
                ],
                "compute_rows": [
                    {
                        "gpu_uuid": GPU_UUID,
                        "pid": 4242,
                        "process_name": "ollama",
                        "used_memory_mib": 6500,
                    }
                ],
                "process_rows": [
                    {
                        "pid": 4000,
                        "parent_pid": 1,
                        "executable_path": str(Path(sys.executable).resolve()),
                        "creation_time": "2026-09-03T00:00:00.0000000Z",
                    },
                    {
                        "pid": 4242,
                        "parent_pid": 4000,
                        "executable_path": str(Path(sys.executable).resolve()),
                        "creation_time": "2026-09-03T00:00:01.0000000Z",
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    path.write_text(
        "import sys\n"
        "import json\n"
        "from pathlib import Path\n"
        f"state = json.loads(Path(r\"{normalized_state_path}\").read_text(encoding='utf-8'))\n"
        "args = ' '.join(sys.argv[1:])\n"
        "if '--process-inventory' in args:\n"
        "    print(json.dumps(state['process_rows']))\n"
        "elif '--query-gpu=' in args:\n"
        "    rows = [state['gpu_row']] if '-i' in sys.argv else state['gpu_rows']\n"
        "    for row in rows:\n"
        "      print(','.join([\n"
        "        row['uuid'],\n"
        "        row['name'],\n"
        "        row['vbios_version'],\n"
        "        str(row['memory_total_mib']),\n"
        "        str(row['memory_used_mib']),\n"
        "        row['driver_version'],\n"
        "        row['pci_bus_id'],\n"
        "        row['pstate'],\n"
        "        str(row['power_limit_watts']),\n"
        "        str(row.get('power_draw_watts', 75.0)),\n"
        "        str(row.get('utilization_gpu', 80.0)),\n"
        "        str(row.get('power_min_limit_watts', '')),\n"
        "        str(row.get('power_max_limit_watts', '')),\n"
        "        str(row.get('power_default_limit_watts', '')),\n"
        "      ]))\n"
        "elif '--query-compute-apps=' in args:\n"
        "    for row in state['compute_rows']:\n"
        "        print(','.join([row['gpu_uuid'], str(row['pid']), row['process_name'], str(row['used_memory_mib'])]))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    FakeState.state_path = state
    return path


def set_fake_nvidia_state(state_path: Path, **updates: Any) -> None:
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    for key, value in updates.items():
        payload[key] = value
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def control_observation(nvidia_path: str) -> dict[str, Any]:
    python_path = str(Path(sys.executable).resolve())
    return {
        "schema": "axm-community-lab/windows-host-observation@1",
        "observed_at": "2026-08-05T00:00:00Z",
        "host_id": "control-host",
        "system": {"computer_name": "<operator-workstation>"},
        "cpu": [{"name": "Intel fixture"}],
        "memory": {"total_bytes": 32 * 1024**3},
        "storage": {"physical_disks": [{"model": "NVMe fixture"}]},
        "graphics": {
            "adapters": [{"name": "Intel UHD", "vendor_guess": "Intel", "role_candidate": "igpu"}],
            "nvidia": [
                {
                    "uuid": GPU_UUID,
                    "name": "NVIDIA GeForce RTX 4060",
                    "vbios_version": "95.07.29.00.A9",
                    "memory_total_mib": 8188,
                    "driver_version": "580.97",
                    "pci_bus_id": "00000000:01:00.0",
                    "pstate": "P2",
                    "power_limit_watts": 115.0,
                },
                {
                    "uuid": OFFTARGET_UUID,
                    "name": "NVIDIA GeForce RTX 3090",
                    "vbios_version": "94.02.42.00.01",
                    "memory_total_mib": 24576,
                    "driver_version": "580.97",
                    "pci_bus_id": "00000000:02:00.0",
                    "pstate": "P8",
                    "power_limit_watts": 350.0,
                }
            ],
        },
        "network": {"adapters": []},
        "runtime": [
            {"name": "python", "present": True, "path": python_path, "disabled": False, "disabled_reason": None},
            {"name": "git", "present": True, "path": python_path, "disabled": False, "disabled_reason": None},
            {"name": "ollama", "present": True, "path": python_path, "disabled": False, "disabled_reason": None},
            {"name": "nvidia-smi", "present": True, "path": nvidia_path, "disabled": False, "disabled_reason": None},
            {"name": "docker", "present": False, "path": None, "disabled": True, "disabled_reason": "not installed"},
            {"name": "wsl", "present": False, "path": None, "disabled": True, "disabled_reason": "not installed"},
        ],
        "clock": {"stopwatch_frequency_hz": 10_000_000, "samples": []},
    }


def evidence_bundle(root: Path, endpoint: str) -> dict[str, Path]:
    nvidia = fake_nvidia_script(root)
    state_path = FakeState.state_path or (root / "fake_nvidia_state.json")
    estate_root = root / "estate"
    control = estate_root / "inputs" / "control-host.json"
    heavy_a = estate_root / "inputs" / "heavy-host-a.json"
    heavy_b = estate_root / "inputs" / "heavy-host-b.json"
    write_json(control, control_observation(str(nvidia)))
    write_json(heavy_a, {"schema": "axm-community-lab/windows-host-observation@1", "host_id": "heavy-host-a"})
    write_json(heavy_b, {"schema": "axm-community-lab/windows-host-observation@1", "host_id": "heavy-host-b"})
    estate = estate_root / "estate-observation.json"
    write_json(
        estate,
        {
            "schema": "axm-community-lab/estate-observation@1",
            "estate_id": "fixture-estate",
            "host_count_expected": 3,
            "host_count_observed": 3,
            "accelerator_domains_expected": 6,
            "accelerator_domains_resolved": 6,
            "hosts": [],
            "unresolved": {
                "general": [],
                "host_inventory": [],
                "disabled_with_reason": [],
                "device_identity": [],
            },
        },
    )
    estate_receipt = make_receipt(
        estate_root,
        experiment_id="capture-estate-snapshot",
        supports=[
            {"capability": "host_inventory", "tier": "observed"},
            {"capability": "device_identity", "tier": "observed"},
        ],
        artifacts=[estate, control, heavy_a, heavy_b],
    )

    function_root = root / "function"
    contract = function_root / "function-contract.json"
    write_json(
        contract,
        {
            "schema": "axm-community-lab/function-contract@1",
            "id": "qwen-4060-readiness",
            "implementation": {
                "provider": "ollama-local",
                "model": MODEL,
                "endpoint": endpoint,
            },
        },
    )
    output_one = function_root / "attempt-1" / "output.json"
    output_two = function_root / "attempt-2" / "output.json"
    output = {
        "schema": "axm-community-lab/bounded-local-inference-output@1",
        "status": "PASS",
        "model": MODEL,
        "model_digest": MODEL_DIGEST,
        "prompt_sha256": "a" * 64,
        "response": "161",
        "provider": {},
    }
    write_json(output_one, output)
    write_json(output_two, output)
    function_receipt = make_receipt(
        function_root,
        experiment_id="freeze-one-function",
        supports=[{"capability": "function_contract", "tier": "qualified"}],
        artifacts=[contract, output_one, output_two],
    )

    thermal_public = make_thermal_receipt(root, public=True)
    thermal_private = make_thermal_receipt(root, public=False)
    coverage = []
    for name in (
        "qwen-thermal-receipt.json",
        "qwen-telemetry.csv",
        "qwen-casefan-trace.jsonl",
        "case-fan-hold.ps1",
        "qwen-thermal-qualify.ps1",
        "qwen-pl-set.log",
        "qwen-pl-restore.log",
        "W01-RTX4060-THERMAL-PROFILE-CANDIDATE.json",
    ):
        artifact = root / "thermal" / name
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"provider-free thermal fixture: {name}\n", encoding="utf-8")
        coverage.append({"path": str(artifact.resolve()), "sha256": file_sha(artifact)})
    coverage_by_name = {Path(row["path"]).name: row for row in coverage}
    executable_identity = {
        "path": str(Path(sys.executable).resolve()),
        "sha256": file_sha(Path(sys.executable)),
    }
    holder = {
        "executable": executable_identity,
        "lhm": coverage_by_name["qwen-thermal-qualify.ps1"],
        "pawnio": coverage_by_name["qwen-pl-set.log"],
        "policy": coverage_by_name["case-fan-hold.ps1"],
    }
    fan_channels = [
        {
            "channel": "Pump Fan control/1",
            "control_identity": "/lpc/nct6686d/control/1",
            "tachometer_sensor_identity": "/lpc/nct6686d/fan/1",
        },
        {
            "channel": "System Fan #1 control/2",
            "control_identity": "/lpc/nct6686d/control/2",
            "tachometer_sensor_identity": "/lpc/nct6686d/fan/2",
        },
        {
            "channel": "System Fan #3 control/4",
            "control_identity": "/lpc/nct6686d/control/4",
            "tachometer_sensor_identity": "/lpc/nct6686d/fan/4",
        },
    ]
    thermal_control = root / "thermal-control-manifest.json"
    write_json(
        thermal_control,
        {
            "schema": "tier-bench/anchor-thermal-control@1",
            "profile_id": THERMAL_PROFILE_ID,
            "receipts": {
                "public_sha256": file_sha(thermal_public),
                "private_sha256": file_sha(thermal_private),
            },
            "artifacts": coverage,
            "gpu": {
                "uuid": GPU_UUID,
                "name": "NVIDIA GeForce RTX 4060",
                "vbios_version": "95.07.29.00.A9",
                "driver_version": "580.97",
                "pci_bus_id": "00000000:01:00.0",
            },
            "model": {"name": MODEL, "digest": MODEL_DIGEST},
            "runtime": {
                "python": executable_identity,
                "ollama": executable_identity,
                "nvidia_smi": {"path": str(nvidia.resolve()), "sha256": file_sha(nvidia)},
                "ollama_version": "0.11.10-fixture",
            },
            "power": {"target_watts": 90, "default_watts": 115, "minimum_watts": 70},
            "workload": {"workers": 2, "sustained_seconds": 900},
            "holder": holder,
            "fan_trace_path": str((root / "thermal" / "qwen-casefan-trace.jsonl").resolve()),
            "fan_channels": fan_channels,
        },
    )

    probe = root / "physical-probe.json"
    write_json(
        probe,
        {
            "schema": "tier-bench/anchor-4060-physical-probe@1",
            "status": "PASS",
            "endpoint": endpoint,
            "python_version": sys.version.split()[0],
            "nvidia_smi_command": [sys.executable, str(nvidia)],
            "process_inventory_command": [sys.executable, str(nvidia), "--process-inventory"],
            "gpu": {
                "uuid": GPU_UUID,
                "name": "NVIDIA GeForce RTX 4060",
                "vbios_version": "95.07.29.00.A9",
                "memory_total_mib": 8188,
                "memory_used_mib": 6500,
                "driver_version": "580.97",
                "pci_bus_id": "00000000:01:00.0",
                "power_limit_watts": 115.0,
                "compute_processes": [
                    {"gpu_uuid": GPU_UUID, "pid": 4242, "process_name": "ollama", "used_memory_mib": 6500}
                ],
            },
            "gpu_inventory_before": [
                {"uuid": GPU_UUID, "memory_used_mib": 0},
                {"uuid": OFFTARGET_UUID, "memory_used_mib": 128},
            ],
            "thermal_profile": {
                "profile_id": THERMAL_PROFILE_ID,
                "public_receipt_sha256": file_sha(thermal_public),
                "private_receipt_sha256": file_sha(thermal_private),
                "control_manifest_observed_sha256": file_sha(thermal_control),
                "control_manifest_expected_sha256": file_sha(thermal_control),
                "fan_governance": FAN_GOVERNANCE,
                "fan_channels": [
                    {**fan_channels[0], "tachometer_rpm": 2400, "timestamp": "2026-09-03T00:00:04Z"},
                    {**fan_channels[1], "tachometer_rpm": 1800, "timestamp": "2026-09-03T00:00:04Z"},
                    {**fan_channels[2], "tachometer_rpm": 1750, "timestamp": "2026-09-03T00:00:04Z"},
                ],
                "holder": {
                    "active": True,
                    "pid": 1234,
                    **holder,
                    "sensor_age_seconds": 4,
                },
                "coverage_artifacts": coverage,
            },
            "power_control": {
                "minimum_watts": 70,
                "maximum_watts": 150,
                "default_watts": 115,
                "pre_run_watts": 115,
                "applied_watts": 90,
                "application_result": "PASS",
                "restoration_target_watts": 115,
            },
            "ollama": {
                "version": "0.11.10-fixture",
                "model": MODEL,
                "model_digest": MODEL_DIGEST,
                "model_size_bytes": 6_594_474_711,
                "size_vram": 6_442_450_944,
                "context_length": 8192,
                "details": {"quantization_level": "Q4_K_M"},
            },
            "dedicated_server": {
                "pid": 4000,
                "executable": str(Path(sys.executable).resolve()),
                "executable_sha256": file_sha(Path(sys.executable)),
                "creation_time": "2026-09-03T00:00:00.0000000Z",
                "process_tree": [
                    {
                        "pid": 4000,
                        "parent_pid": 1,
                        "executable_path": str(Path(sys.executable).resolve()),
                        "executable_sha256": file_sha(Path(sys.executable)),
                        "creation_time": "2026-09-03T00:00:00.0000000Z",
                    },
                    {
                        "pid": 4242,
                        "parent_pid": 4000,
                        "executable_path": str(Path(sys.executable).resolve()),
                        "executable_sha256": file_sha(Path(sys.executable)),
                        "creation_time": "2026-09-03T00:00:01.0000000Z",
                    },
                ],
            },
            "checks": [{"id": "fixture", "pass": True}],
            "production_claim": False,
            "promotion_authorized": False,
        },
    )
    return {
        "estate_receipt": estate_receipt,
        "estate": estate,
        "control": control,
        "function_receipt": function_receipt,
        "probe": probe,
        "nvidia": nvidia,
        "nvidia_state": state_path,
        "thermal_public": thermal_public,
        "thermal_private": thermal_private,
        "thermal_control": thermal_control,
    }


def build_backend(root: Path, endpoint: str) -> tuple[dict[str, Any], dict[str, Path]]:
    evidence = evidence_bundle(root, endpoint)
    result = build(
        base_registry_path=FIXTURE / "backend_registry.json",
        estate_receipt_path=evidence["estate_receipt"],
        estate_observation_path=evidence["estate"],
        control_host_observation_path=evidence["control"],
        function_receipt_path=evidence["function_receipt"],
        physical_probe_path=evidence["probe"],
        executor_path=EXECUTOR,
        python_executable=Path(sys.executable).resolve(),
        output_dir=root / "physical-backend",
        backend_id="backend.cuda4060-qwen35-physical",
        gpu_uuid=GPU_UUID,
        thermal_profile_public_receipt_path=evidence["thermal_public"],
        thermal_profile_private_receipt_path=evidence["thermal_private"],
        thermal_target_power_limit_watts=90.0,
    )
    return result, evidence


def invoke(
    command: list[str],
    request: dict[str, Any],
    *,
    env_updates: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    for name, value in (env_updates or {}).items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    return subprocess.run(
        command,
        input=json.dumps(request).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        check=False,
        shell=False,
        timeout=30,
        env=environment,
    )


def test_physical_manifest_is_built_only_from_complete_receipts() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        result, evidence = build_backend(Path(temp), endpoint)
        registry = json.loads(Path(result["registry"]).read_text(encoding="utf-8"))
        binding = json.loads(Path(result["binding"]).read_text(encoding="utf-8"))
        normalized = validate_backend_registry(registry)
        physical = next(row for row in normalized["backends"] if row["id"] == result["backend_id"])
        assert physical["architecture"] == "cuda-sm89"
        assert physical["physical_qualification"] is True
        assert physical["memory_mib"] == 8188
        assert physical["model_identity"].endswith(MODEL_DIGEST)
        assert physical["power_limit_w"] == 90
        assert physical["thermal_profile_id"] == THERMAL_PROFILE_ID
        assert physical["fan_governance"] == FAN_GOVERNANCE
        assert "thermal_profile_receipt_sha256" in physical
        assert binding["execution"]["backend_family"] == "cuda"
        assert binding["execution"]["ollama_vulkan"] == "0"
        assert binding["execution"]["cuda_visible_devices"] == GPU_UUID
        assert binding["execution"]["thermal_profile_id"] == THERMAL_PROFILE_ID
        assert binding["execution"]["thermal_profile_receipt_sha256"] == binding["source_receipts"]["thermal_profile_private_receipt_sha256"]
        assert binding["source_receipts"]["thermal_profile_private_receipt_sha256"] == binding["source_receipts"]["thermal_profile_private_controlling_sha256"]
        assert binding["source_receipts"]["thermal_control_manifest_observed_sha256"] == binding["source_receipts"]["thermal_control_manifest_expected_sha256"]
        assert binding["execution"]["ollama_root_pid"] == 4000
        assert {row["pid"] for row in binding["execution"]["ollama_process_tree"]} == {4000, 4242}
        build_receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
        assert build_receipt["dedicated_ollama_process"]["root_pid"] == 4000
        assert binding["execution"]["power_limit_target_watts"] == 90.0
        assert binding["execution"]["fan_governance"] == FAN_GOVERNANCE
        assert binding["execution"]["fan_channels"] == THERMAL_FAN_CHANNELS
        plan = compile_plan(
            json.loads((FIXTURE / "floor.json").read_text(encoding="utf-8")),
            json.loads((FIXTURE / "physical_availability_cartridge.json").read_text(encoding="utf-8")),
            registry,
            bindings={"generate_decision_packet": result["backend_id"]},
        )
        baseline = json.loads((FIXTURE / "plan.cuda-fixture.json").read_text(encoding="utf-8"))
        assert plan["portable_task_id"] == baseline["portable_task_id"]
        assert plan["plan_id"] != baseline["plan_id"]


def test_incomplete_census_refuses_physical_manifest() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        evidence = evidence_bundle(root, endpoint)
        estate = json.loads(evidence["estate"].read_text(encoding="utf-8"))
        estate["host_count_observed"] = 2
        write_json(evidence["estate"], estate)
        # Rebind the changed artifact so the builder reaches the census law rather than failing custody first.
        receipt = json.loads(evidence["estate_receipt"].read_text(encoding="utf-8"))
        for row in receipt["artifacts"]:
            if row["path"] == "estate-observation.json":
                row["sha256"] = file_sha(evidence["estate"])
                row["bytes"] = evidence["estate"].stat().st_size
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = compact_hash(receipt)
        write_json(evidence["estate_receipt"], receipt)
        try:
            build(
                base_registry_path=FIXTURE / "backend_registry.json",
                estate_receipt_path=evidence["estate_receipt"],
                estate_observation_path=evidence["estate"],
                control_host_observation_path=evidence["control"],
                function_receipt_path=evidence["function_receipt"],
                physical_probe_path=evidence["probe"],
                executor_path=EXECUTOR,
                python_executable=Path(sys.executable).resolve(),
                output_dir=root / "out",
                backend_id="backend.cuda4060-qwen35-physical",
                gpu_uuid=GPU_UUID,
                thermal_profile_public_receipt_path=evidence["thermal_public"],
                thermal_profile_private_receipt_path=evidence["thermal_private"],
                thermal_target_power_limit_watts=90.0,
            )
        except BuildError as exc:
            assert "three-host census" in str(exc)
        else:
            raise AssertionError("incomplete census must not mint a physical backend")


def test_physical_manifest_requires_thermal_profile_receipts() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        evidence = evidence_bundle(root, endpoint)
        try:
            build(
                base_registry_path=FIXTURE / "backend_registry.json",
                estate_receipt_path=evidence["estate_receipt"],
                estate_observation_path=evidence["estate"],
                control_host_observation_path=evidence["control"],
                function_receipt_path=evidence["function_receipt"],
                physical_probe_path=evidence["probe"],
                executor_path=EXECUTOR,
                python_executable=Path(sys.executable).resolve(),
                output_dir=root / "out",
                backend_id="backend.cuda4060-qwen35-physical",
                gpu_uuid=GPU_UUID,
            )
        except BuildError as exc:
            assert "both thermal profile receipts" in str(exc)
        else:
            raise AssertionError("thermal profile receipts must be mandatory")


def test_physical_manifest_rejects_thermal_drift() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        evidence = evidence_bundle(root, endpoint)
        public = json.loads(evidence["thermal_public"].read_text(encoding="utf-8"))
        public["profile_id"] = "W01-OTHER"
        write_json(evidence["thermal_public"], public)
        control = json.loads(evidence["thermal_control"].read_text(encoding="utf-8"))
        control["receipts"]["public_sha256"] = file_sha(evidence["thermal_public"])
        write_json(evidence["thermal_control"], control)
        try:
            build(
                base_registry_path=FIXTURE / "backend_registry.json",
                estate_receipt_path=evidence["estate_receipt"],
                estate_observation_path=evidence["estate"],
                control_host_observation_path=evidence["control"],
                function_receipt_path=evidence["function_receipt"],
                physical_probe_path=evidence["probe"],
                executor_path=EXECUTOR,
                python_executable=Path(sys.executable).resolve(),
                output_dir=root / "out",
                backend_id="backend.cuda4060-qwen35-physical",
                gpu_uuid=GPU_UUID,
                thermal_profile_public_receipt_path=evidence["thermal_public"],
                thermal_profile_private_receipt_path=evidence["thermal_private"],
                thermal_target_power_limit_watts=90.0,
            )
        except BuildError as exc:
            assert "thermal profile id mismatch" in str(exc)
        else:
            raise AssertionError("profile drift must not be accepted")


def test_physical_manifest_rejects_unbound_or_unrestored_power_profile() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        evidence = evidence_bundle(root, endpoint)
        private = json.loads(evidence["thermal_private"].read_text(encoding="utf-8"))
        private["operating_point"]["power_limit_w"] = 95.0
        write_json(evidence["thermal_private"], private)
        control = json.loads(evidence["thermal_control"].read_text(encoding="utf-8"))
        control["receipts"]["private_sha256"] = file_sha(evidence["thermal_private"])
        write_json(evidence["thermal_control"], control)
        try:
            build(
                base_registry_path=FIXTURE / "backend_registry.json",
                estate_receipt_path=evidence["estate_receipt"],
                estate_observation_path=evidence["estate"],
                control_host_observation_path=evidence["control"],
                function_receipt_path=evidence["function_receipt"],
                physical_probe_path=evidence["probe"],
                executor_path=EXECUTOR,
                python_executable=Path(sys.executable).resolve(),
                output_dir=root / "out",
                backend_id="backend.cuda4060-qwen35-physical",
                gpu_uuid=GPU_UUID,
                thermal_profile_public_receipt_path=evidence["thermal_public"],
                thermal_profile_private_receipt_path=evidence["thermal_private"],
                thermal_target_power_limit_watts=90.0,
            )
        except BuildError as exc:
            assert "not bound to 90.0W" in str(exc)
        else:
            raise AssertionError("non-90W thermal target must be rejected")


def test_physical_manifest_rejects_sensor_or_holder_failures() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        evidence = evidence_bundle(root, endpoint)
        private = json.loads(evidence["thermal_private"].read_text(encoding="utf-8"))
        private["pass_criteria_all_met"]["every_mapped_case_fan_stable_nonzero_tachometer"] = False
        write_json(evidence["thermal_private"], private)
        control = json.loads(evidence["thermal_control"].read_text(encoding="utf-8"))
        control["receipts"]["private_sha256"] = file_sha(evidence["thermal_private"])
        write_json(evidence["thermal_control"], control)
        try:
            build(
                base_registry_path=FIXTURE / "backend_registry.json",
                estate_receipt_path=evidence["estate_receipt"],
                estate_observation_path=evidence["estate"],
                control_host_observation_path=evidence["control"],
                function_receipt_path=evidence["function_receipt"],
                physical_probe_path=evidence["probe"],
                executor_path=EXECUTOR,
                python_executable=Path(sys.executable).resolve(),
                output_dir=root / "out",
                backend_id="backend.cuda4060-qwen35-physical",
                gpu_uuid=GPU_UUID,
                thermal_profile_public_receipt_path=evidence["thermal_public"],
                thermal_profile_private_receipt_path=evidence["thermal_private"],
                thermal_target_power_limit_watts=90.0,
            )
        except BuildError as exc:
            assert "tachometer" in str(exc)
        else:
            raise AssertionError("tachometer failure must be rejected")


def test_physical_probe_rejects_identity_power_holder_and_coverage_drift() -> None:
    cases = (
        ("card VBIOS", ("gpu", "vbios_version"), "drifted-vbios"),
        ("driver", ("gpu", "driver_version"), "drifted-driver"),
        ("model", ("ollama", "model"), "drifted-model"),
        ("holder", ("thermal_profile", "holder", "active"), False),
        ("PawnIO", ("thermal_profile", "holder", "pawnio", "sha256"), "0" * 64),
        ("stale sensors", ("thermal_profile", "holder", "sensor_age_seconds"), 60),
        ("fan map", ("thermal_profile", "fan_channels", 0, "channel"), "wrong fan"),
        ("tachometer", ("thermal_profile", "fan_channels", 0, "tachometer_rpm"), 0),
        ("legal power", ("power_control", "minimum_watts"), 95),
        ("power application", ("power_control", "application_result"), "FAIL"),
        ("covered artifact", ("thermal_profile", "coverage_artifacts", 0, "sha256"), "0" * 64),
        ("dedicated process", ("gpu", "compute_processes", 0, "pid"), 9999),
        ("process executable", ("dedicated_server", "process_tree", 1, "executable_sha256"), "0" * 64),
    )
    for index, (label, path, replacement) in enumerate(cases):
        with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
            root = Path(temp)
            evidence = evidence_bundle(root, endpoint)
            probe = json.loads(evidence["probe"].read_text(encoding="utf-8"))
            cursor: Any = probe
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = replacement
            write_json(evidence["probe"], probe)
            try:
                build(
                    base_registry_path=FIXTURE / "backend_registry.json",
                    estate_receipt_path=evidence["estate_receipt"],
                    estate_observation_path=evidence["estate"],
                    control_host_observation_path=evidence["control"],
                    function_receipt_path=evidence["function_receipt"],
                    physical_probe_path=evidence["probe"],
                    executor_path=EXECUTOR,
                    python_executable=Path(sys.executable).resolve(),
                    output_dir=root / f"out-{index}",
                    backend_id=f"backend.cuda4060-drift-{index}",
                    gpu_uuid=GPU_UUID,
                    thermal_profile_public_receipt_path=evidence["thermal_public"],
                    thermal_profile_private_receipt_path=evidence["thermal_private"],
                    thermal_target_power_limit_watts=90.0,
                )
            except BuildError:
                pass
            else:
                raise AssertionError(f"{label} drift must be rejected")


def test_thermal_receipt_must_terminal_pass() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        evidence = evidence_bundle(root, endpoint)
        receipt = json.loads(evidence["thermal_public"].read_text(encoding="utf-8"))
        receipt["terminal"] = "HOLD"
        receipt["pass"] = False
        write_json(evidence["thermal_public"], receipt)
        control = json.loads(evidence["thermal_control"].read_text(encoding="utf-8"))
        control["receipts"]["public_sha256"] = file_sha(evidence["thermal_public"])
        write_json(evidence["thermal_control"], control)
        try:
            build(
                base_registry_path=FIXTURE / "backend_registry.json",
                estate_receipt_path=evidence["estate_receipt"],
                estate_observation_path=evidence["estate"],
                control_host_observation_path=evidence["control"],
                function_receipt_path=evidence["function_receipt"],
                physical_probe_path=evidence["probe"],
                executor_path=EXECUTOR,
                python_executable=Path(sys.executable).resolve(),
                output_dir=root / "out",
                backend_id="backend.cuda4060-hold",
                gpu_uuid=GPU_UUID,
                thermal_profile_public_receipt_path=evidence["thermal_public"],
                thermal_profile_private_receipt_path=evidence["thermal_private"],
                thermal_target_power_limit_watts=90.0,
            )
        except BuildError as exc:
            assert "terminal PASS" in str(exc)
        else:
            raise AssertionError("non-PASS thermal receipt must be rejected")


def test_external_thermal_authority_rejects_self_consistent_substitution() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        evidence = evidence_bundle(root, endpoint)
        expected_control_sha256 = file_sha(evidence["thermal_control"])
        control = json.loads(evidence["thermal_control"].read_text(encoding="utf-8"))
        control["profile_id"] = "attacker-selected-profile"
        write_json(evidence["thermal_control"], control)
        try:
            build_manifest(
                base_registry_path=FIXTURE / "backend_registry.json",
                estate_receipt_path=evidence["estate_receipt"],
                estate_observation_path=evidence["estate"],
                control_host_observation_path=evidence["control"],
                function_receipt_path=evidence["function_receipt"],
                physical_probe_path=evidence["probe"],
                executor_path=EXECUTOR,
                python_executable=Path(sys.executable).resolve(),
                output_dir=root / "out",
                backend_id="backend.cuda4060-substitution",
                gpu_uuid=GPU_UUID,
                thermal_profile_public_receipt_path=evidence["thermal_public"],
                thermal_profile_private_receipt_path=evidence["thermal_private"],
                thermal_control_manifest_path=evidence["thermal_control"],
                expected_thermal_control_manifest_sha256=expected_control_sha256,
                thermal_target_power_limit_watts=90.0,
            )
        except BuildError as exc:
            assert "controlling identity mismatch" in str(exc)
        else:
            raise AssertionError("caller-selected thermal control substitution must be rejected")


def test_physical_executor_refuses_binding_and_residency_drift() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        result, evidence = build_backend(root, endpoint)
        registry = json.loads(Path(result["registry"]).read_text(encoding="utf-8"))
        backend = next(row for row in registry["backends"] if row["id"] == result["backend_id"])
        binding = json.loads(Path(result["binding"]).read_text(encoding="utf-8"))
        request = {
            "schema": "tier-bench/anchor-executor-request@1",
            "request_id": "request-1",
            "backend_id": backend["id"],
            "operation": "probe",
            "payload": {"required_capabilities": ["structured-json"]},
        }
        bad = list(backend["driver_command"])
        bad[-1] = "0" * 64
        completed = invoke(bad, request)
        assert completed.returncode != 0
        assert json.loads(completed.stdout)["status"] == "error"

        completed = invoke(backend["driver_command"], request)
        assert completed.returncode == 0
        assert json.loads(completed.stdout)["status"] == "ok"
        state = json.loads(evidence["nvidia_state"].read_text(encoding="utf-8"))
        bound_process_rows = copy.deepcopy(state["process_rows"])
        set_fake_nvidia_state(
            evidence["nvidia_state"],
            compute_rows=[{"gpu_uuid": GPU_UUID, "pid": 9999, "process_name": "ollama", "used_memory_mib": 6500}],
            process_rows=[
                *bound_process_rows,
                {
                    "pid": 9999,
                    "parent_pid": 1,
                    "executable_path": str(Path(sys.executable).resolve()),
                    "creation_time": "2026-09-03T00:00:02.0000000Z",
                },
            ],
        )
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "launched Ollama tree" in " ".join(json.loads(completed.stdout)["advisory"])
        set_fake_nvidia_state(
            evidence["nvidia_state"],
            compute_rows=[{"gpu_uuid": GPU_UUID, "pid": 4242, "process_name": "ollama", "used_memory_mib": 6500}],
            process_rows=bound_process_rows,
        )
        creation_drift = copy.deepcopy(bound_process_rows)
        creation_drift[1]["creation_time"] = "2026-09-03T00:10:00.0000000Z"
        set_fake_nvidia_state(evidence["nvidia_state"], process_rows=creation_drift)
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "creation time changed" in " ".join(json.loads(completed.stdout)["advisory"])
        set_fake_nvidia_state(evidence["nvidia_state"], process_rows=bound_process_rows)
        for updates, expected in (
            ({"OLLAMA_VULKAN": None}, "OLLAMA_VULKAN"),
            ({"OLLAMA_VULKAN": "1"}, "OLLAMA_VULKAN"),
            ({"OLLAMA_SCHED_SPREAD": "1"}, "SCHED_SPREAD"),
            ({"CUDA_VISIBLE_DEVICES": OFFTARGET_UUID}, "CUDA_VISIBLE_DEVICES"),
        ):
            completed = invoke(backend["driver_command"], request, env_updates=updates)
            assert completed.returncode != 0
            assert expected in " ".join(json.loads(completed.stdout)["advisory"])

        FakeState.loaded = False
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "not resident" in " ".join(json.loads(completed.stdout)["advisory"])
        FakeState.loaded = True

        bad_binding = copy.deepcopy(binding)
        bad_binding["execution"]["backend_family"] = "rocm"
        path = Path(result["binding"])
        write_json(path, bad_binding)
        bad_binding_command = list(backend["driver_command"])
        bad_binding_command[-1] = executor_module.hash_json(bad_binding)
        completed = invoke(bad_binding_command, request)
        assert completed.returncode != 0
        assert "backend family" in " ".join(json.loads(completed.stdout)["advisory"]).lower()
        write_json(path, binding)

        off_target = [
            {
                "gpu_uuid": OFFTARGET_UUID,
                "pid": 4242,
                "process_name": "ollama",
                "used_memory_mib": 6500,
            }
        ]
        set_fake_nvidia_state(evidence["nvidia_state"], compute_rows=off_target)
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "target-specific" in " ".join(json.loads(completed.stdout)["advisory"]).lower()

        zero_mem = [
            {
                "gpu_uuid": GPU_UUID,
                "pid": 4242,
                "process_name": "ollama",
                "used_memory_mib": 0,
            }
        ]
        set_fake_nvidia_state(evidence["nvidia_state"], compute_rows=zero_mem)
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "resident" in " ".join(json.loads(completed.stdout)["advisory"]).lower()

        set_fake_nvidia_state(
            evidence["nvidia_state"],
            compute_rows=[{"gpu_uuid": GPU_UUID, "pid": 4242, "process_name": "ollama", "used_memory_mib": 6500}],
            gpu_rows=[
                {
                    "uuid": GPU_UUID,
                    "name": "NVIDIA GeForce RTX 4060",
                    "vbios_version": "95.07.29.00.A9",
                    "memory_total_mib": 8188,
                    "memory_used_mib": 6500,
                    "driver_version": "580.97",
                    "pci_bus_id": "00000000:01:00.0",
                    "pstate": "P2",
                    "power_limit_watts": 90.0,
                },
                {
                    "uuid": OFFTARGET_UUID,
                    "name": "NVIDIA GeForce RTX 3090",
                    "vbios_version": "94.02.42.00.01",
                    "memory_total_mib": 24576,
                    "memory_used_mib": 7000,
                    "driver_version": "580.97",
                    "pci_bus_id": "00000000:02:00.0",
                    "pstate": "P2",
                    "power_limit_watts": 350.0,
                },
            ],
        )
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "non-target GPU" in " ".join(json.loads(completed.stdout)["advisory"])

        evidence["thermal_private"].write_text("{}\n", encoding="utf-8")
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "thermal receipt digest drift" in " ".join(json.loads(completed.stdout)["advisory"])


def test_actual_executor_path_runs_reference_cartridge_under_controller() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        result, _ = build_backend(root, endpoint)
        registry = json.loads(Path(result["registry"]).read_text(encoding="utf-8"))
        report = backend_conformance(
            registry,
            backend_id=result["backend_id"],
            controller_cwd=ROOT,
        )
        assert report["passed"] is True
        assert report["physical_qualification"] is True
        run = run_cartridge(
            json.loads((FIXTURE / "floor.json").read_text(encoding="utf-8")),
            json.loads((FIXTURE / "physical_availability_cartridge.json").read_text(encoding="utf-8")),
            registry,
            run_root=root / "run",
            controller_cwd=ROOT,
            bindings={"generate_decision_packet": result["backend_id"]},
        )
        assert run["status"] == "accepted"
        assert run["final_product"]["decision_packet"]["claim"] == "not_physically_available"
        assert run["final_product"]["decision_packet"]["requires_human_review"] is True
        assert FakeState.generated >= 2  # conformance plus task run
        physical_receipt = next((root / "run" / "receipts").glob("0002-*.json"))
        receipt = json.loads(physical_receipt.read_text(encoding="utf-8"))
        assert receipt["backend"]["physical_qualification"] is True
        assert receipt["telemetry"]["memory_peak_mib"] >= 6000
        assert receipt["accepted"] is True


def test_execute_refuses_all_live_drift_before_provider_generation() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        result, evidence = build_backend(root, endpoint)
        registry = validate_backend_registry(json.loads(Path(result["registry"]).read_text(encoding="utf-8")))
        backend = next(row for row in registry["backends"] if row["id"] == result["backend_id"])
        request = {
            "schema": "tier-bench/anchor-executor-request@1",
            "request_id": "hostile-execute",
            "backend_id": backend["id"],
            "operation": "execute",
            "payload": {
                "crate": {"operation": "decision.generate"},
                "inputs": {"node:derive_availability": {"asset_id": "A-17"}},
            },
        }
        state_path = evidence["nvidia_state"]
        pristine = json.loads(state_path.read_text(encoding="utf-8"))

        hostile_states: list[tuple[str, dict[str, Any], dict[str, str | None]]] = []
        hostile_states.append(("environment", pristine, {"OLLAMA_VULKAN": "1"}))

        process_drift = copy.deepcopy(pristine)
        process_drift["compute_rows"] = [
            {"gpu_uuid": GPU_UUID, "pid": 9999, "process_name": "ollama", "used_memory_mib": 6500}
        ]
        process_drift["process_rows"].append(
            {
                "pid": 9999,
                "parent_pid": 1,
                "executable_path": str(Path(sys.executable).resolve()),
                "creation_time": "2026-09-03T00:00:02.0000000Z",
            }
        )
        hostile_states.append(("process-tree", process_drift, {}))

        power_drift = copy.deepcopy(pristine)
        power_drift["gpu_row"]["power_limit_watts"] = 95.0
        power_drift["gpu_rows"][0]["power_limit_watts"] = 95.0
        hostile_states.append(("power", power_drift, {}))

        placement_drift = copy.deepcopy(pristine)
        placement_drift["compute_rows"] = [
            {"gpu_uuid": OFFTARGET_UUID, "pid": 4242, "process_name": "ollama", "used_memory_mib": 6500}
        ]
        hostile_states.append(("placement", placement_drift, {}))

        for label, hostile, environment in hostile_states:
            write_json(state_path, hostile)
            FakeState.generated = 0
            completed = invoke(backend["driver_command"], request, env_updates=environment)
            assert completed.returncode != 0, label
            assert FakeState.generated == 0, label

        write_json(state_path, pristine)
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode == 0
        assert FakeState.generated == 1
        binding = json.loads(Path(result["binding"]).read_text(encoding="utf-8"))
        evidence_event = json.loads(Path(binding["execution"]["evidence_log"]).read_text(encoding="utf-8").splitlines()[-1])
        assert evidence_event["preflight_runtime_state"]["gpu"]["uuid"] == GPU_UUID
        assert evidence_event["postflight_runtime_state"]["gpu"]["uuid"] == GPU_UUID


def test_windows_launcher_executes_provider_free_failure_harness() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if powershell is None:
        assert os.name != "nt"
        return
    launcher = ROOT / "scripts" / "run-anchor-crate-4060-smoke.ps1"
    scenarios = (
        "power-apply-fails",
        "power-restore-fails",
        "holder-preflight-fails",
        "post-load-primary-cleanup-fails",
    )
    for scenario in scenarios:
        command = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
            "-TierBenchRoot",
            ".",
            "-GradientRoot",
            ".",
            "-EstateReceipt",
            ".",
            "-EstateObservation",
            ".",
            "-ControlHostObservation",
            ".",
            "-ThermalProfilePublicReceipt",
            ".",
            "-ThermalProfilePrivateReceipt",
            ".",
            "-ThermalControlManifest",
            ".",
            "-ExpectedThermalControlManifestSha256",
            "0" * 64,
            "-FailureHarnessScenario",
            scenario,
        ]
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert result["scenario"] == scenario
        assert result["smoke_pass_emitted"] is False
        assert result["environment_restored"] is True
        assert result["environment_after_cleanup"] == result["environment_prior"]
        assert result["endpoint_stopped"] is True
        assert result["process_tree_stopped"] is True
        assert result["combined_failure"]

        if scenario == "power-apply-fails":
            assert result["power_application_attempted"] is True
            assert result["power_restoration_attempted"] is True
            assert result["power_restoration_verified"] is True
            assert "90 W application failure" in result["primary_failure"]
        elif scenario == "power-restore-fails":
            assert result["power_restoration_attempted"] is True
            assert result["power_restoration_verified"] is False
            assert "115 W restoration failure" in " ".join(result["cleanup_failures"])
        elif scenario == "holder-preflight-fails":
            assert result["holder_checked_before_model_load"] is True
            assert result["model_load_attempted"] is False
            assert result["power_restoration_attempted"] is False
            assert "holder absent or sensor stale" in result["primary_failure"]
        else:
            assert result["model_load_attempted"] is True
            assert result["power_restoration_attempted"] is True
            assert result["power_restoration_verified"] is True
            assert "post-load primary failure" in result["combined_failure"]
            assert "holder cleanup verification failure" in result["combined_failure"]


def test_launcher_is_present_and_requires_prior_census() -> None:
    launcher = (ROOT / "scripts" / "run-anchor-crate-4060-smoke.ps1").read_text(encoding="utf-8")
    assert "EstateReceipt" in launcher
    assert "host_count_observed -ne 3" in launcher
    assert "CUDA_VISIBLE_DEVICES" in launcher
    assert "OLLAMA_VULKAN = \"0\"" in launcher
    assert "OLLAMA_KEEP_ALIVE" in launcher
    assert "thermalProfilePrivateReceipt" in launcher or "ThermalProfilePrivateReceipt" in launcher
    assert "--thermal-profile-public-receipt" in launcher
    assert "OLLAMA_SCHED_SPREAD" in launcher
    assert "AllowOllamaSchedSpread" not in launcher
    assert "S:\\Scratch" not in launcher
    assert "ExpectedThermalControlManifestSha256" in launcher
    assert "controlling identity mismatch" in launcher
    assert "thermal control artifact digest mismatch" in launcher
    assert "Get-CimInstance Win32_Process" in launcher
    assert "cleanup-result.json" in launcher
    assert launcher.index("    Set-PowerLimit", launcher.index("try {")) < launcher.index("    $server = Start-Process")
    assert launcher.rindex("$smokeReceipt =") > launcher.index("} finally")
    assert "primary_failure" in launcher
    assert "primary failure: $primaryText; cleanup failures: $cleanupText" in launcher
    assert "generate_decision_packet=$BackendId" in launcher
    assert "production_claim = $false" in launcher


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ANCHOR 4060 PHYSICAL TESTS PASS: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
