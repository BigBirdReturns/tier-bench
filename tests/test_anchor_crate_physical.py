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
import subprocess
import sys
import tempfile
import threading
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_anchor_4060_manifest import BuildError, build  # noqa: E402
from tier_runner.anchor_crate_plan import compile_plan  # noqa: E402
from tier_runner.anchor_crate_runtime import backend_conformance, run_cartridge  # noqa: E402
from tier_runner.anchor_crate_schema import validate_backend_registry  # noqa: E402

FIXTURE = ROOT / "labs" / "community-home-lab" / "anchor-crate"
EXECUTOR = ROOT / "examples" / "anchor_crate" / "ollama_4060_executor.py"
MODEL = "qwen3.5:9b-q4_K_M"
MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
GPU_UUID = "GPU-4060-PHYSICAL-FIXTURE"

spec = importlib.util.spec_from_file_location("ollama_4060_executor", EXECUTOR)
assert spec and spec.loader
executor_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor_module)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


class FakeState:
    loaded = True
    generated = 0


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
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def fake_nvidia_script(root: Path) -> Path:
    path = root / "fake_nvidia_smi.py"
    path.write_text(
        "import sys\n"
        f"print('{GPU_UUID}, NVIDIA GeForce RTX 4060, 8188, 6500, 580.97, 00000000:01:00.0, P2, 115.0, 75.0, 80')\n",
        encoding="utf-8",
    )
    return path


def control_observation(nvidia_path: str) -> dict[str, Any]:
    python_path = str(Path(sys.executable).resolve())
    return {
        "schema": "axm-community-lab/windows-host-observation@1",
        "observed_at": "2026-08-05T00:00:00Z",
        "host_id": "control-host",
        "system": {"computer_name": "BAM-DESKTOP"},
        "cpu": [{"name": "Intel fixture"}],
        "memory": {"total_bytes": 32 * 1024**3},
        "storage": {"physical_disks": [{"model": "NVMe fixture"}]},
        "graphics": {
            "adapters": [{"name": "Intel UHD", "vendor_guess": "Intel", "role_candidate": "igpu"}],
            "nvidia": [
                {
                    "uuid": GPU_UUID,
                    "name": "NVIDIA GeForce RTX 4060",
                    "memory_total_mib": 8188,
                    "driver_version": "580.97",
                    "pci_bus_id": "00000000:01:00.0",
                    "pstate": "P2",
                    "power_limit_watts": 115.0,
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

    probe = root / "physical-probe.json"
    write_json(
        probe,
        {
            "schema": "tier-bench/anchor-4060-physical-probe@1",
            "status": "PASS",
            "endpoint": endpoint,
            "python_version": sys.version.split()[0],
            "nvidia_smi_command": [sys.executable, str(nvidia)],
            "gpu": {
                "uuid": GPU_UUID,
                "name": "NVIDIA GeForce RTX 4060",
                "memory_total_mib": 8188,
                "memory_used_mib": 6500,
                "driver_version": "580.97",
                "pci_bus_id": "00000000:01:00.0",
                "power_limit_watts": 115.0,
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
    )
    return result, evidence


def invoke(command: list[str], request: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        input=json.dumps(request).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        check=False,
        shell=False,
        timeout=30,
    )


def test_physical_manifest_is_built_only_from_complete_receipts() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        result, _ = build_backend(Path(temp), endpoint)
        registry = json.loads(Path(result["registry"]).read_text(encoding="utf-8"))
        normalized = validate_backend_registry(registry)
        physical = next(row for row in normalized["backends"] if row["id"] == result["backend_id"])
        assert physical["architecture"] == "cuda-sm89"
        assert physical["physical_qualification"] is True
        assert physical["memory_mib"] == 8188
        assert physical["model_identity"].endswith(MODEL_DIGEST)
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
            )
        except BuildError as exc:
            assert "three-host census" in str(exc)
        else:
            raise AssertionError("incomplete census must not mint a physical backend")


def test_physical_executor_refuses_binding_and_residency_drift() -> None:
    with tempfile.TemporaryDirectory() as temp, fake_ollama() as endpoint:
        root = Path(temp)
        result, _ = build_backend(root, endpoint)
        registry = json.loads(Path(result["registry"]).read_text(encoding="utf-8"))
        backend = next(row for row in registry["backends"] if row["id"] == result["backend_id"])
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

        FakeState.loaded = False
        completed = invoke(backend["driver_command"], request)
        assert completed.returncode != 0
        assert "not resident" in " ".join(json.loads(completed.stdout)["advisory"])


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


def test_launcher_is_present_and_requires_prior_census() -> None:
    launcher = (ROOT / "scripts" / "run-anchor-crate-4060-smoke.ps1").read_text(encoding="utf-8")
    assert "EstateReceipt" in launcher
    assert "host_count_observed -ne 3" in launcher
    assert "CUDA_VISIBLE_DEVICES" in launcher
    assert "generate_decision_packet=$BackendId" in launcher
    assert "production_claim = $false" in launcher


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ANCHOR 4060 PHYSICAL TESTS PASS: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
