from __future__ import annotations

import base64
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from astra_stage2.canonical import Stage2Error, sha256_bytes, sha256_object, strict_json_load
from astra_stage2.control_identity import (
    GENERATOR_MANIFEST_SHA256,
    LAW_BLOB_SHA1,
    LAW_COMMIT_SHA1,
    LAW_TREE_SHA1,
    PUBLIC_CONTROLS,
    SCHEMA_HARDWARE_PLATFORM,
    SCHEMA_HARDWARE_PROBE,
    SCHEMA_TOPOLOGY_EVIDENCE,
    SCAFFOLD_HEAD_SHA1,
    SCAFFOLD_TREE_SHA1,
    STAGE1_JOIN_HEAD_SHA1,
    _assert_public_safe,
    bind_control_set,
    binding_template,
    inventory_binding_config,
    probe_hardware,
    validate_binding_config,
    verify_control_set,
)


class ControlIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix=".astra-control-id-test-", dir=Path.cwd()
        )
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.config = binding_template()
        self.config["binding_id"] = "astra-stage2-controls-test"
        for index, control in enumerate(self.config["controls"]):
            revision = control["checkpoint_revision_sha1"]
            model_root = self.root / "models" / revision
            model_root.mkdir(parents=True)
            (model_root / "config.json").write_text(
                json.dumps({"role": control["role"], "private": "PRIVATE_TRANSCRIPT_CANARY"}),
                encoding="utf-8",
            )
            (model_root / "tokenizer.json").write_text(
                json.dumps({"tokenizer": control["role"]}), encoding="utf-8"
            )
            (model_root / "model-00001-of-00002.safetensors").write_bytes(
                f"weights-a-{control['role']}".encode()
            )
            (model_root / "model-00002-of-00002.safetensors").write_bytes(
                f"weights-b-{control['role']}".encode()
            )
            index_value = {
                "metadata": {"total_size": 2},
                "weight_map": {
                    "a": "model-00001-of-00002.safetensors",
                    "b": "model-00002-of-00002.safetensors",
                },
            }
            (model_root / "model.safetensors.index.json").write_text(
                json.dumps(index_value), encoding="utf-8"
            )
            hardware_root = self.root / "hardware" / control["role"]
            hardware_root.mkdir(parents=True)
            query_path = hardware_root / "nvidia-query.csv"
            query_path.write_text(
                f"{index}, Synthetic GPU {index}, GPU-private-{index}, "
                f"0000:0{index}:00.0, 24576, 999.0\n",
                encoding="utf-8",
            )
            platform_record = {
                "schema": SCHEMA_HARDWARE_PLATFORM,
                "system": "Windows",
                "release": "Synthetic",
                "version": "Synthetic",
                "machine": "AMD64",
                "processor": "Synthetic",
                "python_implementation": "CPython",
                "python_version": "3.13.0",
                "selected_device_indices": [index],
                "nvidia_smi_executable_sha256": "a" * 64,
            }
            platform_record["payload_sha256"] = sha256_object(platform_record)
            (hardware_root / "platform.json").write_text(
                json.dumps(platform_record), encoding="utf-8"
            )
            selected_row = {
                "index": index,
                "name": f"Synthetic GPU {index}",
                "uuid": f"GPU-private-{index}",
                "pci_bus_id": f"0000:0{index}:00.0",
                "memory_mib": 24576,
                "driver": "999.0",
            }
            topology_record = {
                "schema": SCHEMA_TOPOLOGY_EVIDENCE,
                "state": "NOT_APPLICABLE_SINGLE_SELECTED_DEVICE",
                "platform": "Windows",
                "method": "PLATFORM_LIMITATION_SINGLE_DEVICE",
                "selected_device_index": index,
                "selected_device_query_row_sha256": sha256_object(selected_row),
                "device_query_sha256": sha256_bytes(query_path.read_bytes()),
                "inter_device_topology_claimed": False,
                "implicit_pooling_claimed": False,
            }
            topology_record["payload_sha256"] = sha256_object(topology_record)
            (hardware_root / "nvidia-topology.json").write_text(
                json.dumps(topology_record), encoding="utf-8"
            )
            control["source_root"] = str(self.root / "source" / control["role"])
            Path(control["source_root"]).mkdir(parents=True)
            control["model_root"] = str(model_root)
            control["model_config_paths"] = ["config.json"]
            control["tokenizer_paths"] = ["tokenizer.json"]
            control["weight_index_path"] = "model.safetensors.index.json"
            control["weight_paths"] = [
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
            ]
            runtime_root = self.root / "runtime" / control["role"]
            runtime_root.mkdir(parents=True)
            runtime_executable = runtime_root / "runtime-probe.py"
            runtime_executable.write_text(
                "#!/usr/bin/env python3\nprint('SyntheticRuntime 1.0 test-build')\n",
                encoding="utf-8",
            )
            runtime_executable.chmod(0o755)
            (runtime_root / "runtime.json").write_text(
                json.dumps({"mode": "deterministic"}), encoding="utf-8"
            )
            probe_args = []
            executable_name = "runtime-probe.py"
            if os.name == "nt":
                executable_name = Path(sys.executable).name
                shutil.copy2(sys.executable, runtime_root / executable_name)
                probe_args = ["runtime-probe.py"]
            control["runtime"] = {
                "root": str(runtime_root),
                "name": "SyntheticRuntime",
                "version": "1.0",
                "build": "test-build",
                "executable_path": executable_name,
                "configuration_paths": ["runtime.json"],
                "configuration": {"mode": "deterministic"},
                "probe_args": probe_args,
                "required_probe_substrings": ["SyntheticRuntime", "1.0", "test-build"],
                "probe_timeout_seconds": 30,
            }
            control["hardware"] = {
                "evidence_root": str(hardware_root),
                "platform_path": "platform.json",
                "device_query_path": "nvidia-query.csv",
                "topology_evidence_path": "nvidia-topology.json",
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
    def source_manifest(root: Path, repository: str, commit: str) -> dict[str, object]:
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
                copy.deepcopy(config or self.config), repo_root=self.repo, output_dir=output
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
        self.assertEqual([item["role"] for item in template["controls"]], list(PUBLIC_CONTROLS))

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
        plan = strict_json_load(output / "calibration-plan.json")
        self.assertEqual(plan["observation_count"], 648)
        manifest = strict_json_load(output / "control-manifest.json")
        self.assertEqual(manifest["status"], "BOUND_EMPIRICAL_IDENTITIES")

    def test_04_public_receipt_has_no_private_path_or_canary(self) -> None:
        _, output = self.bind(name="path-safe")
        public_bytes = b"".join(path.read_bytes() for path in sorted((output / "public").glob("*.json")))
        self.assertNotIn(str(self.root).encode(), public_bytes)
        self.assertNotIn(b"PRIVATE_TRANSCRIPT_CANARY", public_bytes)
        self.assertNotIn(b"GPU-private", public_bytes)
        private_bytes = b"".join(path.read_bytes() for path in sorted((output / "private").glob("*.json")))
        encoded_private_root = json.dumps(str(self.root))[1:-1].encode()
        self.assertIn(encoded_private_root, private_bytes)

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

    def test_10_symlinked_model_file_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        model_root = Path(bad["controls"][0]["model_root"])
        real = model_root / "real-config.json"
        real.write_text("{}", encoding="utf-8")
        link = model_root / "config.json"
        link.unlink()
        try:
            link.symlink_to(real)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                self.skipTest("symlink creation is privilege-dependent on Windows")
            raise
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
    def completed(stdout: bytes = b"", returncode: int = 0) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=b"")

    @staticmethod
    def deterministic_platform(system: str):
        return patch.multiple(
            "astra_stage2.control_identity.platform",
            system=lambda: system,
            release=lambda: "Synthetic release",
            version=lambda: "Synthetic version",
            machine=lambda: "Synthetic machine",
            processor=lambda: "Synthetic processor",
            python_implementation=lambda: "CPython",
            python_version=lambda: "3.13.0",
        )

    def test_21_linux_success_retains_exact_topology_bytes(self) -> None:
        query = b"0, Linux GPU, GPU-linux, 0000:01:00.0, 24576, 999.0\n"
        matrix = b"\tGPU0\nGPU0\tX\n"
        out = self.root / "probe-linux"
        query_command = [
            sys.executable,
            "-i",
            "0",
            "--query-gpu=index,name,uuid,pci.bus_id,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
        selected_row = {
            "index": 0,
            "name": "Linux GPU",
            "uuid": "GPU-linux",
            "pci_bus_id": "0000:01:00.0",
            "memory_mib": 24576,
            "driver": "999.0",
        }
        with self.deterministic_platform("Linux"), patch(
            "astra_stage2.control_identity.subprocess.run",
            side_effect=[self.completed(query), self.completed(matrix)],
        ) as run:
            receipt = probe_hardware(
                output_dir=out, nvidia_smi=sys.executable, device_indices=[0]
            )
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list,
            [
                call(query_command, capture_output=True, check=False),
                call([sys.executable, "topo", "-m"], capture_output=True, check=False),
            ],
        )
        topology = strict_json_load(out / "nvidia-topology.json")
        self.assertEqual(topology["method"], "NVIDIA_SMI_TOPO_MATRIX")
        self.assertEqual(topology["selected_device_indices"], [0])
        self.assertEqual(
            topology["selected_device_query_rows_sha256"], sha256_object([selected_row])
        )
        self.assertEqual(
            topology["matrix_stdout_base64"], base64.b64encode(matrix).decode("ascii")
        )
        self.assertEqual(base64.b64decode(topology["matrix_stdout_base64"]), matrix)
        self.assertEqual(topology["matrix_stdout_sha256"], sha256_bytes(matrix))
        self.assertEqual(receipt["schema"], SCHEMA_HARDWARE_PROBE)

    def test_22_linux_nonzero_topology_refuses(self) -> None:
        query = b"0, Linux GPU, GPU-linux, 0000:01:00.0, 24576, 999.0\n"
        with self.deterministic_platform("Linux"), patch(
            "astra_stage2.control_identity.subprocess.run",
            side_effect=[self.completed(query), self.completed(returncode=9)],
        ):
            with self.assertRaisesRegex(Stage2Error, "topology query failed with exit 9"):
                probe_hardware(
                    output_dir=self.root / "probe-linux-nonzero",
                    nvidia_smi=sys.executable,
                    device_indices=[0],
                )

    def test_23_linux_empty_topology_refuses(self) -> None:
        query = b"0, Linux GPU, GPU-linux, 0000:01:00.0, 24576, 999.0\n"
        with self.deterministic_platform("Linux"), patch(
            "astra_stage2.control_identity.subprocess.run",
            side_effect=[self.completed(query), self.completed(b" \r\n")],
        ):
            with self.assertRaisesRegex(Stage2Error, "empty stdout"):
                probe_hardware(
                    output_dir=self.root / "probe-linux-empty",
                    nvidia_smi=sys.executable,
                    device_indices=[0],
                )

    def test_24_windows_single_device_never_invokes_topology_command(self) -> None:
        query = b"3, Windows GPU, GPU-win, 0000:03:00.0, 24576, 999.0\r\n"
        out = self.root / "probe-windows"
        query_command = [
            sys.executable,
            "-i",
            "3",
            "--query-gpu=index,name,uuid,pci.bus_id,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
        selected_row = {
            "index": 3,
            "name": "Windows GPU",
            "uuid": "GPU-win",
            "pci_bus_id": "0000:03:00.0",
            "memory_mib": 24576,
            "driver": "999.0",
        }
        with self.deterministic_platform("Windows"), patch(
            "astra_stage2.control_identity.subprocess.run",
            return_value=self.completed(query),
        ) as run:
            probe_hardware(output_dir=out, nvidia_smi=sys.executable, device_indices=[3])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(
            run.call_args_list, [call(query_command, capture_output=True, check=False)]
        )
        topology = strict_json_load(out / "nvidia-topology.json")
        self.assertEqual(topology["state"], "NOT_APPLICABLE_SINGLE_SELECTED_DEVICE")
        self.assertEqual(topology["method"], "PLATFORM_LIMITATION_SINGLE_DEVICE")
        self.assertEqual(topology["selected_device_index"], 3)
        self.assertEqual(
            topology["selected_device_query_row_sha256"], sha256_object(selected_row)
        )
        self.assertFalse(topology["inter_device_topology_claimed"])
        self.assertFalse(topology["implicit_pooling_claimed"])

    def test_25_windows_multi_device_refuses_without_topology_source(self) -> None:
        query = (
            b"0, GPU 0, GPU-win-0, 0000:01:00.0, 24576, 999.0\r\n"
            b"1, GPU 1, GPU-win-1, 0000:02:00.0, 24576, 999.0\r\n"
        )
        with self.deterministic_platform("Windows"), patch(
            "astra_stage2.control_identity.subprocess.run",
            return_value=self.completed(query),
        ) as run:
            with self.assertRaisesRegex(Stage2Error, "independently qualified topology source"):
                probe_hardware(
                    output_dir=self.root / "probe-windows-multi",
                    nvidia_smi=sys.executable,
                    device_indices=[0, 1],
                )
        self.assertEqual(run.call_count, 1)

    def test_26_platform_substitution_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        root = Path(bad["controls"][0]["hardware"]["evidence_root"])
        topology = strict_json_load(root / "nvidia-topology.json")
        topology["platform"] = "Linux"
        topology["payload_sha256"] = sha256_object(
            {key: value for key, value in topology.items() if key != "payload_sha256"}
        )
        (root / "nvidia-topology.json").write_text(json.dumps(topology), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "platform does not match"):
            self.bind(bad, name="platform-substitution")

    def test_27_selected_index_mismatch_refuses(self) -> None:
        query = b"1, Wrong GPU, GPU-wrong, 0000:02:00.0, 24576, 999.0\n"
        with self.deterministic_platform("Windows"), patch(
            "astra_stage2.control_identity.subprocess.run",
            return_value=self.completed(query),
        ):
            with self.assertRaisesRegex(Stage2Error, "do not exactly match"):
                probe_hardware(
                    output_dir=self.root / "probe-index-mismatch",
                    nvidia_smi=sys.executable,
                    device_indices=[0],
                )

    def test_28_device_query_digest_drift_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        root = Path(bad["controls"][0]["hardware"]["evidence_root"])
        with (root / "nvidia-query.csv").open("ab") as handle:
            handle.write(b"\n")
        with self.assertRaisesRegex(Stage2Error, "device-query digest mismatch"):
            self.bind(bad, name="query-digest-drift")

    def test_29_topology_record_tamper_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        root = Path(bad["controls"][0]["hardware"]["evidence_root"])
        topology = strict_json_load(root / "nvidia-topology.json")
        topology["state"] = "OBSERVED"
        (root / "nvidia-topology.json").write_text(json.dumps(topology), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "payload hash mismatch"):
            self.bind(bad, name="topology-tamper")

    def test_30_windows_inter_device_authority_widening_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        root = Path(bad["controls"][0]["hardware"]["evidence_root"])
        topology = strict_json_load(root / "nvidia-topology.json")
        topology["inter_device_topology_claimed"] = True
        topology["payload_sha256"] = sha256_object(
            {key: value for key, value in topology.items() if key != "payload_sha256"}
        )
        (root / "nvidia-topology.json").write_text(json.dumps(topology), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "cannot claim inter-device topology"):
            self.bind(bad, name="topology-authority")

    def test_31_implicit_pooling_authority_widening_refuses(self) -> None:
        bad = copy.deepcopy(self.config)
        root = Path(bad["controls"][0]["hardware"]["evidence_root"])
        topology = strict_json_load(root / "nvidia-topology.json")
        topology["implicit_pooling_claimed"] = True
        topology["payload_sha256"] = sha256_object(
            {key: value for key, value in topology.items() if key != "payload_sha256"}
        )
        (root / "nvidia-topology.json").write_text(json.dumps(topology), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "may not claim implicit pooling"):
            self.bind(bad, name="pooling-authority")

    def test_32_duplicate_device_query_index_refuses(self) -> None:
        query = (
            b"0, GPU 0, GPU-a, 0000:01:00.0, 24576, 999.0\n"
            b"0, GPU 0 duplicate, GPU-b, 0000:02:00.0, 24576, 999.0\n"
        )
        with patch(
            "astra_stage2.control_identity.subprocess.run", return_value=self.completed(query)
        ):
            with self.assertRaisesRegex(Stage2Error, "duplicate indices"):
                probe_hardware(
                    output_dir=self.root / "probe-duplicate",
                    nvidia_smi=sys.executable,
                    device_indices=[0],
                )

    def test_33_unknown_platform_refuses_after_mandatory_query(self) -> None:
        query = b"0, GPU 0, GPU-a, 0000:01:00.0, 24576, 999.0\n"
        with self.deterministic_platform("Darwin"), patch(
            "astra_stage2.control_identity.subprocess.run",
            return_value=self.completed(query),
        ) as run:
            with self.assertRaisesRegex(Stage2Error, "unsupported hardware platform"):
                probe_hardware(
                    output_dir=self.root / "probe-platform",
                    nvidia_smi=sys.executable,
                    device_indices=[0],
                )
        self.assertEqual(run.call_count, 1)

    def test_34_missing_selected_device_refuses_before_command(self) -> None:
        with patch("astra_stage2.control_identity.subprocess.run") as run:
            with self.assertRaisesRegex(Stage2Error, "at least one selected"):
                probe_hardware(
                    output_dir=self.root / "probe-no-selection",
                    nvidia_smi=sys.executable,
                    device_indices=[],
                )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
