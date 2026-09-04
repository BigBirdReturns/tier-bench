from __future__ import annotations

import base64
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from astra_stage2.canonical import Stage2Error, sha256_bytes, sha256_object, strict_json_load
from astra_stage2.control_identity import (
    GENERATOR_MANIFEST_SHA256,
    LAW_BLOB_SHA1,
    LAW_COMMIT_SHA1,
    LAW_TREE_SHA1,
    PUBLIC_CONTROLS,
    SCAFFOLD_HEAD_SHA1,
    SCAFFOLD_TREE_SHA1,
    SCHEMA_HARDWARE_TOPOLOGY,
    STAGE1_JOIN_HEAD_SHA1,
    _assert_public_safe,
    _hardware_manifest,
    bind_control_set,
    binding_template,
    inventory_binding_config,
    probe_hardware,
    validate_binding_config,
    verify_control_set,
)


class ControlIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="astra-control-id-test-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.config = binding_template()
        self.config["binding_id"] = "astra-stage2-controls-test"

        for index, control in enumerate(self.config["controls"]):
            role = control["role"]
            revision = control["checkpoint_revision_sha1"]

            model_root = self.root / "models" / revision
            model_root.mkdir(parents=True)
            (model_root / "config.json").write_text(
                json.dumps({"role": role, "private": "PRIVATE_TRANSCRIPT_CANARY"}),
                encoding="utf-8",
            )
            (model_root / "tokenizer.json").write_text(
                json.dumps({"tokenizer": role}),
                encoding="utf-8",
            )
            (model_root / "model-00001-of-00002.safetensors").write_bytes(
                f"weights-a-{role}".encode()
            )
            (model_root / "model-00002-of-00002.safetensors").write_bytes(
                f"weights-b-{role}".encode()
            )
            (model_root / "model.safetensors.index.json").write_text(
                json.dumps(
                    {
                        "metadata": {"total_size": 2},
                        "weight_map": {
                            "a": "model-00001-of-00002.safetensors",
                            "b": "model-00002-of-00002.safetensors",
                        },
                    }
                ),
                encoding="utf-8",
            )

            hardware_root = self.root / "hardware" / role
            hardware_root.mkdir(parents=True)
            (hardware_root / "platform.json").write_text(
                json.dumps({"system": "Synthetic", "role": role}),
                encoding="utf-8",
            )
            (hardware_root / "nvidia-query.csv").write_text(
                f"{index}, Synthetic GPU {index}, GPU-private-{index}, "
                f"0000:0{index}:00.0, 24576, 999.0\n",
                encoding="utf-8",
            )
            topology_stdout = f"GPU{index} X\n".encode("utf-8")
            topology_stderr = b""
            topology_row = {
                "index": index,
                "name": f"Synthetic GPU {index}",
                "uuid": f"GPU-private-{index}",
                "pci_bus_id": f"0000:0{index}:00.0",
                "memory_mib": 24576,
                "driver": "999.0",
            }
            (hardware_root / "nvidia-topology.json").write_text(
                json.dumps(
                    {
                        "schema": SCHEMA_HARDWARE_TOPOLOGY,
                        "platform_system": "Synthetic",
                        "method": "NVIDIA_SMI_TOPOLOGY_MATRIX",
                        "selected_device_indices": [index],
                        "selected_device_rows_sha256": sha256_object([topology_row]),
                        "native_command": ["nvidia-smi", "topo", "-m"],
                        "native_exit_code": 0,
                        "native_stdout": {
                            "bytes": len(topology_stdout),
                            "sha256": sha256_bytes(topology_stdout),
                            "base64": base64.b64encode(topology_stdout).decode("ascii"),
                        },
                        "native_stderr": {
                            "bytes": len(topology_stderr),
                            "sha256": sha256_bytes(topology_stderr),
                            "base64": base64.b64encode(topology_stderr).decode("ascii"),
                        },
                        "native_matrix_observed": True,
                        "interdevice_links_required": False,
                    }
                ),
                encoding="utf-8",
            )

            source_root = self.root / "source" / role
            source_root.mkdir(parents=True)
            control["source_root"] = str(source_root)
            control["model_root"] = str(model_root)
            control["model_config_paths"] = ["config.json"]
            control["tokenizer_paths"] = ["tokenizer.json"]
            control["weight_index_path"] = "model.safetensors.index.json"
            control["weight_paths"] = [
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
            ]

            runtime_root = self.root / "runtime" / role
            runtime_root.mkdir(parents=True)
            if os.name == "nt":
                source_executable = Path(
                    os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
                )
                runtime_executable = runtime_root / "runtime-probe.exe"
                shutil.copy2(source_executable, runtime_executable)
                probe_args = [
                    "/d",
                    "/s",
                    "/c",
                    "echo SyntheticRuntime 1.0 test-build",
                ]
            else:
                source_executable = Path("/bin/sh")
                runtime_executable = runtime_root / "runtime-probe"
                shutil.copy2(source_executable, runtime_executable)
                runtime_executable.chmod(0o755)
                probe_args = [
                    "-c",
                    "printf 'SyntheticRuntime 1.0 test-build\\n'",
                ]

            (runtime_root / "runtime.json").write_text(
                json.dumps({"mode": "deterministic"}),
                encoding="utf-8",
            )
            control["runtime"] = {
                "root": str(runtime_root),
                "name": "SyntheticRuntime",
                "version": "1.0",
                "build": "test-build",
                "executable_path": runtime_executable.name,
                "configuration_paths": ["runtime.json"],
                "configuration": {"mode": "deterministic"},
                "probe_args": probe_args,
                "required_probe_substrings": [
                    "SyntheticRuntime",
                    "1.0",
                    "test-build",
                ],
                "probe_timeout_seconds": 30,
            }
            control["hardware"] = {
                "evidence_root": str(hardware_root),
                "platform_path": "platform.json",
                "device_query_path": "nvidia-query.csv",
                "topology_path": "nvidia-topology.json",
                "selected_device_indices": [index],
            }
            control["effort_mapping"] = {
                "low": {
                    "arguments": ["--effort", "low"],
                    "environment": {},
                    "configuration": {"steps": 1},
                },
                "high": {
                    "arguments": ["--effort", "high"],
                    "environment": {},
                    "configuration": {"steps": 2},
                },
            }

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def repository_coordinates() -> dict[str, object]:
        return {
            "repository_root": "/private/repo",
            "head_sha1": "f" * 40,
            "tree_sha1": "e" * 40,
            "law_blob_sha1": LAW_BLOB_SHA1,
            "implementation_blobs": {},
            "generator_manifest_sha256": GENERATOR_MANIFEST_SHA256,
        }

    @staticmethod
    def source_manifest(
        root: Path,
        repository: str,
        commit: str,
    ) -> dict[str, object]:
        entry = {
            "name": "source.py",
            "bytes": 7,
            "sha256": sha256_bytes(b"source\n"),
        }
        return {
            "repository": repository,
            "commit_sha1": commit,
            "tree_sha1": "a" * 40,
            "origin_sha256": sha256_bytes(repository.encode()),
            "file_count": 1,
            "total_bytes": 7,
            "files": [entry],
            "content_manifest_sha256": sha256_object([entry]),
        }

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for child in value for item in ControlIdentityTests._strings(child)]
        if isinstance(value, dict):
            return [item for child in value.values() for item in ControlIdentityTests._strings(child)]
        return []

    def bind(self, config=None, name="bound"):
        output = self.root / name
        from astra_stage2.generator import build_generator_manifest as stub_generator

        generator = stub_generator()
        generator["payload_sha256"] = GENERATOR_MANIFEST_SHA256
        with patch(
            "astra_stage2.control_identity.verify_repository_coordinates",
            return_value=self.repository_coordinates(),
        ), patch(
            "astra_stage2.control_identity._tracked_source_manifest",
            side_effect=self.source_manifest,
        ), patch(
            "astra_stage2.control_identity.build_generator_manifest",
            return_value=generator,
        ), patch(
            "astra_stage2.control_identity.validate_generator_manifest",
            side_effect=lambda value: value,
        ), patch(
            "astra_stage2.control_identity.validate_plan",
            side_effect=lambda plan, generator_manifest, control_manifest: plan,
        ):
            receipt = bind_control_set(
                copy.deepcopy(config or self.config),
                repo_root=self.repo,
                output_dir=output,
            )
        return receipt, output

    def test_01_template_pins_all_public_coordinates(self) -> None:
        template = binding_template()
        self.assertEqual(template["law"]["commit_sha1"], LAW_COMMIT_SHA1)
        self.assertEqual(template["law"]["tree_sha1"], LAW_TREE_SHA1)
        self.assertEqual(template["law"]["blob_sha1"], LAW_BLOB_SHA1)
        self.assertEqual(template["scaffold"]["head_sha1"], SCAFFOLD_HEAD_SHA1)
        self.assertEqual(template["scaffold"]["tree_sha1"], SCAFFOLD_TREE_SHA1)
        self.assertEqual(template["stage1_join_head"], STAGE1_JOIN_HEAD_SHA1)
        self.assertEqual(template["generator_manifest_sha256"], GENERATOR_MANIFEST_SHA256)
        self.assertEqual(
            [item["role"] for item in template["controls"]],
            list(PUBLIC_CONTROLS),
        )

    def test_02_inventory_discovers_exact_checkpoint_files(self) -> None:
        draft = copy.deepcopy(self.config)
        for control in draft["controls"]:
            control["model_config_paths"] = []
            control["tokenizer_paths"] = []
            control["weight_index_path"] = None
            control["weight_paths"] = []
        inventoried = inventory_binding_config(draft)
        for control in inventoried["controls"]:
            self.assertEqual(control["model_config_paths"], ["config.json"])
            self.assertEqual(control["tokenizer_paths"], ["tokenizer.json"])
            self.assertEqual(control["weight_index_path"], "model.safetensors.index.json")
            self.assertEqual(len(control["weight_paths"]), 2)

    def test_03_binding_emits_three_controls_and_complete_plan(self) -> None:
        receipt, output = self.bind()
        self.assertEqual(receipt["binding_status"], "BOUND_EXECUTABLE_IDENTITIES")
        self.assertEqual(receipt["control_count"], 3)
        self.assertEqual(receipt["observation_count"], 648)
        self.assertEqual(strict_json_load(output / "calibration-plan.json")["observation_count"], 648)
        self.assertEqual(
            strict_json_load(output / "control-manifest.json")["status"],
            "BOUND_EMPIRICAL_IDENTITIES",
        )

    def test_04_public_receipt_has_no_private_path_or_canary(self) -> None:
        _, output = self.bind(name="path-safe")

        public_values: list[str] = []
        for path in sorted((output / "public").glob("*.json")):
            public_values.extend(self._strings(strict_json_load(path)))
        public_text = "\n".join(public_values)
        self.assertNotIn("PRIVATE_TRANSCRIPT_CANARY", public_text)
        self.assertNotIn("GPU-private", public_text)

        expected_private_roots = {
            str(Path(control["source_root"]).resolve())
            for control in self.config["controls"]
        } | {
            str(Path(control["model_root"]).resolve())
            for control in self.config["controls"]
        } | {
            str(Path(control["runtime"]["root"]).resolve())
            for control in self.config["controls"]
        } | {
            str(Path(control["hardware"]["evidence_root"]).resolve())
            for control in self.config["controls"]
        }
        for root in expected_private_roots:
            self.assertNotIn(root, public_values)

        observed_private_roots: set[str] = set()
        for path in sorted((output / "private").glob("*.json")):
            value = strict_json_load(path)
            controls = []
            if isinstance(value, dict) and isinstance(value.get("controls"), list):
                controls.extend(value["controls"])
            elif isinstance(value, dict):
                controls.append(value)
            for control in controls:
                if not isinstance(control, dict):
                    continue
                locator = control.get("private_locator")
                if not isinstance(locator, dict):
                    continue
                for key in (
                    "source_root",
                    "model_root",
                    "runtime_root",
                    "hardware_evidence_root",
                ):
                    raw = locator.get(key)
                    if raw:
                        observed_private_roots.add(str(Path(raw).resolve()))

        self.assertTrue(expected_private_roots.issubset(observed_private_roots))

    def test_05_source_coordinate_substitution_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["source_repository"] = "attacker/repo"
        with self.assertRaisesRegex(Stage2Error, "released law"):
            validate_binding_config(bad)

    def test_06_checkpoint_revision_substitution_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["checkpoint_revision_sha1"] = "0" * 40
        with self.assertRaisesRegex(Stage2Error, "released law"):
            validate_binding_config(bad)

    def test_07_unknown_control_property_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        with self.assertRaisesRegex(Stage2Error, "property set mismatch"):
            validate_binding_config(bad)

    def test_08_weight_index_mismatch_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["weight_paths"] = ["model-00001-of-00002.safetensors"]
        with self.assertRaisesRegex(Stage2Error, "weight index shard set mismatch"):
            self.bind(bad, name="bad-index")

    def test_09_missing_weight_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        path = Path(bad["controls"][0]["model_root"]) / bad["controls"][0]["weight_paths"][0]
        path.unlink()
        with self.assertRaisesRegex(Stage2Error, "not a regular file"):
            self.bind(bad, name="missing-weight")

    @unittest.skipIf(os.name == "nt", "symlink creation is privilege-dependent on Windows")
    def test_10_symlinked_model_file_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        model_root = Path(bad["controls"][0]["model_root"])
        real = model_root / "real-config.json"
        real.write_text("{}", encoding="utf-8")
        link = model_root / "config.json"
        link.unlink()
        link.symlink_to(real)
        with self.assertRaisesRegex(Stage2Error, "symbolic link"):
            self.bind(bad, name="symlink")

    def test_11_equal_effort_mappings_refuse(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["effort_mapping"]["high"] = copy.deepcopy(
            bad["controls"][0]["effort_mapping"]["low"]
        )
        with self.assertRaisesRegex(Stage2Error, "must differ"):
            self.bind(bad, name="same-effort")

    def test_12_runtime_probe_mismatch_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["runtime"]["required_probe_substrings"] = ["IMPOSSIBLE_CANARY"]
        with self.assertRaisesRegex(Stage2Error, "does not contain"):
            self.bind(bad, name="runtime-probe")

    def test_13_hardware_selection_must_exist(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["hardware"]["selected_device_indices"] = [99]
        with self.assertRaisesRegex(Stage2Error, "absent"):
            self.bind(bad, name="hardware-missing")

    def test_14_quantization_none_must_be_explicit(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["quantization"]["parameters"] = {"bits": 4}
        with self.assertRaisesRegex(Stage2Error, "NONE"):
            self.bind(bad, name="quant-none")

    def test_15_adapter_none_must_be_explicit(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["controls"][0]["adapter"]["paths"] = ["patch.py"]
        with self.assertRaisesRegex(Stage2Error, "adapter NONE"):
            self.bind(bad, name="adapter-none")

    def test_16_verify_detects_local_file_drift(self) -> None:
        _, output = self.bind(name="verify-drift")
        config = copy.deepcopy(self.config)
        model_config = Path(config["controls"][0]["model_root"]) / "config.json"
        model_config.write_text('{"changed":true}', encoding="utf-8")
        from astra_stage2.generator import build_generator_manifest as stub_generator

        generator = stub_generator()
        generator["payload_sha256"] = GENERATOR_MANIFEST_SHA256
        with patch(
            "astra_stage2.control_identity.verify_repository_coordinates",
            return_value=self.repository_coordinates(),
        ), patch(
            "astra_stage2.control_identity._tracked_source_manifest",
            side_effect=self.source_manifest,
        ), patch(
            "astra_stage2.control_identity.build_generator_manifest",
            return_value=generator,
        ), patch(
            "astra_stage2.control_identity.validate_generator_manifest",
            side_effect=lambda value: value,
        ), patch(
            "astra_stage2.control_identity.validate_plan",
            side_effect=lambda plan, generator_manifest, control_manifest: plan,
        ):
            with self.assertRaisesRegex(Stage2Error, "does not reproduce"):
                verify_control_set(config, repo_root=self.repo, output_dir=output)

    def test_17_revision_requires_snapshot_name_or_marker(self) -> None:
        bad = copy.deepcopy(self.config)
        old_root = Path(bad["controls"][0]["model_root"])
        copied = self.root / "models" / "copied-checkpoint"
        copied.mkdir()
        for item in old_root.iterdir():
            if item.is_file():
                (copied / item.name).write_bytes(item.read_bytes())
        bad["controls"][0]["model_root"] = str(copied)
        with self.assertRaisesRegex(Stage2Error, "revision is not evidenced"):
            self.bind(bad, name="no-revision")

    def test_18_exact_revision_marker_allows_copied_snapshot(self) -> None:
        copied_config = copy.deepcopy(self.config)
        old_root = Path(copied_config["controls"][0]["model_root"])
        copied = self.root / "models" / "copied-with-marker"
        copied.mkdir()
        for item in old_root.iterdir():
            if item.is_file():
                (copied / item.name).write_bytes(item.read_bytes())
        revision = copied_config["controls"][0]["checkpoint_revision_sha1"]
        (copied / "REVISION").write_text(revision, encoding="utf-8")
        copied_config["controls"][0]["model_root"] = str(copied)
        copied_config["controls"][0]["revision_marker_path"] = "REVISION"
        receipt, _ = self.bind(copied_config, name="marker")
        self.assertEqual(receipt["control_count"], 3)

    def test_19_public_safety_rejects_injected_private_root(self) -> None:
        with self.assertRaisesRegex(Stage2Error, "leaks a private root"):
            _assert_public_safe({"value": str(self.root / "secret")}, [str(self.root)])

    def test_20_law_blob_substitution_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        bad["law"]["blob_sha1"] = "0" * 40
        with self.assertRaisesRegex(Stage2Error, "law blob"):
            validate_binding_config(bad)


    @staticmethod
    def _completed(args: list[str], returncode: int, stdout: bytes, stderr: bytes = b""):
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)

    def test_21_native_topology_matrix_is_canonical_and_bound(self) -> None:
        executable = self.root / "nvidia-smi"
        executable.write_bytes(b"synthetic-nvidia-smi")
        output = self.root / "probe-native"
        query = self._completed(
            [str(executable)],
            0,
            b"0, Native GPU, GPU-native, 0000:01:00.0, 24576, 999.0\n",
        )
        topology = self._completed(
            [str(executable), "topo", "-m"],
            0,
            b"        GPU0\nGPU0     X\n",
        )
        with patch(
            "astra_stage2.control_identity.subprocess.run",
            side_effect=lambda args, **kwargs: topology if 'topo' in args else query,
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Linux",
        ):
            receipt = probe_hardware(
                output_dir=output,
                nvidia_smi=str(executable),
                device_indices=[0],
            )
        record = strict_json_load(output / "nvidia-topology.json")
        self.assertEqual(record["schema"], SCHEMA_HARDWARE_TOPOLOGY)
        self.assertEqual(record["method"], "NVIDIA_SMI_TOPOLOGY_MATRIX")
        self.assertTrue(record["native_matrix_observed"])
        self.assertFalse(record["interdevice_links_required"])
        self.assertEqual(receipt["topology_method"], record["method"])
        self.assertEqual(receipt["provider_or_model_calls"], 0)

    def test_22_windows_single_device_topology_fallback_is_explicit(self) -> None:
        executable = self.root / "nvidia-smi.exe"
        executable.write_bytes(b"synthetic-nvidia-smi")
        output = self.root / "probe-windows-single"
        query = self._completed(
            [str(executable)],
            0,
            b"0, Windows GPU, GPU-windows, 00000000:01:00.0, 24576, 999.0\n",
        )
        topology = self._completed(
            [str(executable), "topo", "-m"],
            255,
            b"",
            b"ERROR: Invalid Argument\n",
        )
        with patch(
            "astra_stage2.control_identity.subprocess.run",
            side_effect=lambda args, **kwargs: topology if 'topo' in args else query,
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Windows",
        ):
            receipt = probe_hardware(
                output_dir=output,
                nvidia_smi=str(executable),
                device_indices=[0],
            )
        record = strict_json_load(output / "nvidia-topology.json")
        self.assertEqual(
            record["method"],
            "WINDOWS_SINGLE_SELECTED_DEVICE_DECLARATION",
        )
        self.assertEqual(record["native_exit_code"], 255)
        self.assertFalse(record["native_matrix_observed"])
        self.assertFalse(record["interdevice_links_required"])
        self.assertEqual(receipt["native_topology_exit_code"], 255)
        self.assertEqual(receipt["provider_or_model_calls"], 0)

    def test_23_windows_topology_fallback_refuses_multi_device_selection(self) -> None:
        executable = self.root / "nvidia-smi-multi.exe"
        executable.write_bytes(b"synthetic-nvidia-smi")
        output = self.root / "probe-windows-multi"
        query = self._completed(
            [str(executable)],
            0,
            (
                b"0, Windows GPU 0, GPU-0, 00000000:01:00.0, 24576, 999.0\n"
                b"1, Windows GPU 1, GPU-1, 00000000:02:00.0, 24576, 999.0\n"
            ),
        )
        topology = self._completed(
            [str(executable), "topo", "-m"],
            255,
            b"",
            b"ERROR: Invalid Argument\n",
        )
        with patch(
            "astra_stage2.control_identity.subprocess.run",
            side_effect=lambda args, **kwargs: topology if 'topo' in args else query,
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Windows",
        ):
            with self.assertRaisesRegex(Stage2Error, "multi-device selection"):
                probe_hardware(
                    output_dir=output,
                    nvidia_smi=str(executable),
                    device_indices=[0, 1],
                )

    def test_24_topology_record_tamper_refuses_hardware_manifest(self) -> None:
        executable = self.root / "nvidia-smi-tamper.exe"
        executable.write_bytes(b"synthetic-nvidia-smi")
        output = self.root / "probe-tamper"
        query = self._completed(
            [str(executable)],
            0,
            b"0, Windows GPU, GPU-windows, 00000000:01:00.0, 24576, 999.0\n",
        )
        topology = self._completed(
            [str(executable), "topo", "-m"],
            255,
            b"",
            b"ERROR: Invalid Argument\n",
        )
        with patch(
            "astra_stage2.control_identity.subprocess.run",
            side_effect=lambda args, **kwargs: topology if 'topo' in args else query,
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Windows",
        ):
            probe_hardware(
                output_dir=output,
                nvidia_smi=str(executable),
                device_indices=[0],
            )
        record_path = output / "nvidia-topology.json"
        record = strict_json_load(record_path)
        record["selected_device_rows_sha256"] = "0" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "rows digest"):
            _hardware_manifest(
                {
                    "evidence_root": str(output),
                    "platform_path": "platform.json",
                    "device_query_path": "nvidia-query.csv",
                    "topology_path": "nvidia-topology.json",
                    "selected_device_indices": [0],
                }
            )


if __name__ == "__main__":
    unittest.main()
