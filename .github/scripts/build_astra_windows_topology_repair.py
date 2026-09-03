from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, observed {count}")
    return text.replace(old, new, 1)


# LF checkout law for every hash-bound control-identity surface.
attributes_path = Path(".gitattributes")
attributes = attributes_path.read_text(encoding="utf-8")
block = """

# Astra Stage 2 control-identity execution and qualification sources are
# content-addressed. Force LF in both Git and worktrees so core.autocrlf cannot
# alter raw-byte identities on Windows.
.gitattributes text eol=lf
astra_stage2/control_identity.py text eol=lf
experiments/astra_kxr/stage2/control_identity/binding-template.json text eol=lf
scripts/Invoke-AstraStage2ControlIdentityBinding.ps1 text eol=lf
scripts/astra_stage2_bind_controls.ps1 text eol=lf
scripts/astra_stage2_bind_controls.py text eol=lf
tests/test_astra_stage2_control_identity.py text eol=lf
tests/test_astra_stage2_control_identity_release.py text eol=lf
.github/workflows/astra-stage2-control-identity.yml text eol=lf
.github/workflows/astra-stage2-control-identity-release.yml text eol=lf
"""
if "Astra Stage 2 control-identity execution" not in attributes:
    attributes = attributes.rstrip("\n") + block
attributes_path.write_text(attributes, encoding="utf-8", newline="\n")

# Canonical platform-aware topology evidence.
module_path = Path("astra_stage2/control_identity.py")
module = module_path.read_text(encoding="utf-8")
module = replace_once(
    module,
    'SCHEMA_HARDWARE_PROBE = "tier-bench/astra-stage2-hardware-probe@1"\n',
    'SCHEMA_HARDWARE_PROBE = "tier-bench/astra-stage2-hardware-probe@2"\n'
    'SCHEMA_HARDWARE_TOPOLOGY = "tier-bench/astra-stage2-hardware-topology@1"\n',
    "hardware schema constants",
)
module = replace_once(
    module,
    'EFFORT_MAPPING_FIELDS = frozenset({"low", "high"})\n',
    '''TOPOLOGY_FIELDS = frozenset(
    {
        "schema",
        "platform_system",
        "method",
        "selected_device_indices",
        "selected_device_rows_sha256",
        "native_command",
        "native_exit_code",
        "native_stdout",
        "native_stderr",
        "native_matrix_observed",
        "interdevice_links_required",
    }
)
TOPOLOGY_STREAM_FIELDS = frozenset({"bytes", "sha256", "base64"})
EFFORT_MAPPING_FIELDS = frozenset({"low", "high"})
''',
    "topology field constants",
)

topology_helpers = r'''

def _captured_stream(data: bytes) -> dict[str, Any]:
    return {
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "base64": base64.b64encode(data).decode("ascii"),
    }


def _decode_topology_stream(value: Any, label: str) -> bytes:
    stream = _require_mapping(value, label)
    _require_exact_keys(stream, TOPOLOGY_STREAM_FIELDS, label)
    length = _require_int(stream["bytes"], f"{label}.bytes", minimum=0)
    digest = _require_sha256(stream["sha256"], f"{label}.sha256")
    encoded = _require_string(stream["base64"], f"{label}.base64", nonempty=False)
    try:
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise Stage2Error(f"{label}.base64 is not canonical base64") from exc
    if len(decoded) != length:
        raise Stage2Error(f"{label} byte count does not reproduce")
    if sha256_bytes(decoded) != digest:
        raise Stage2Error(f"{label} SHA-256 does not reproduce")
    return decoded


def _validate_hardware_topology(
    root: Path,
    topology_name: str,
    selected: list[int],
    selected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    topology_path = _resolve_regular_file(
        root,
        topology_name,
        "hardware topology evidence",
    )
    topology = _require_mapping(
        strict_json_load(topology_path),
        "hardware topology evidence",
    )
    _require_exact_keys(topology, TOPOLOGY_FIELDS, "hardware topology evidence")
    if topology.get("schema") != SCHEMA_HARDWARE_TOPOLOGY:
        raise Stage2Error("unexpected hardware topology schema")

    platform_system = _require_string(
        topology["platform_system"],
        "hardware topology platform_system",
    )
    method = _require_string(topology["method"], "hardware topology method")
    topology_selected_raw = _require_list(
        topology["selected_device_indices"],
        "hardware topology selected_device_indices",
    )
    topology_selected = [
        _require_int(
            value,
            f"hardware topology selected_device_indices[{index}]",
            minimum=0,
        )
        for index, value in enumerate(topology_selected_raw)
    ]
    if topology_selected != selected:
        raise Stage2Error("hardware topology selected indices differ from the binding")

    selected_rows_sha256 = _require_sha256(
        topology["selected_device_rows_sha256"],
        "hardware topology selected_device_rows_sha256",
    )
    if selected_rows_sha256 != sha256_object(selected_rows):
        raise Stage2Error("hardware topology selected device rows digest does not reproduce")

    native_command_raw = _require_list(
        topology["native_command"],
        "hardware topology native_command",
    )
    native_command = [
        _require_string(
            value,
            f"hardware topology native_command[{index}]",
        )
        for index, value in enumerate(native_command_raw)
    ]
    if native_command != ["nvidia-smi", "topo", "-m"]:
        raise Stage2Error("hardware topology native command differs from the frozen probe")

    native_exit_code = topology["native_exit_code"]
    if isinstance(native_exit_code, bool) or not isinstance(native_exit_code, int):
        raise Stage2Error("hardware topology native_exit_code must be an integer")
    native_stdout = _decode_topology_stream(
        topology["native_stdout"],
        "hardware topology native_stdout",
    )
    _decode_topology_stream(
        topology["native_stderr"],
        "hardware topology native_stderr",
    )
    native_matrix_observed = topology["native_matrix_observed"]
    interdevice_links_required = topology["interdevice_links_required"]
    if not isinstance(native_matrix_observed, bool):
        raise Stage2Error("hardware topology native_matrix_observed must be boolean")
    if not isinstance(interdevice_links_required, bool):
        raise Stage2Error("hardware topology interdevice_links_required must be boolean")

    if method == "NVIDIA_SMI_TOPOLOGY_MATRIX":
        if native_exit_code != 0:
            raise Stage2Error("native topology matrix requires exit code zero")
        if not native_matrix_observed or not native_stdout.strip():
            raise Stage2Error("native topology matrix requires captured nonempty stdout")
        if interdevice_links_required != (len(selected) > 1):
            raise Stage2Error("native topology inter-device requirement differs from selection")
    elif method == "WINDOWS_SINGLE_SELECTED_DEVICE_DECLARATION":
        if platform_system != "Windows":
            raise Stage2Error("single-device topology declaration is Windows-only")
        if len(selected) != 1:
            raise Stage2Error("Windows topology fallback refuses multi-device selection")
        if native_exit_code == 0:
            raise Stage2Error("Windows topology fallback requires a failed native probe")
        if native_matrix_observed:
            raise Stage2Error("Windows topology fallback cannot claim a native matrix")
        if interdevice_links_required:
            raise Stage2Error("single-device topology cannot require inter-device links")
    else:
        raise Stage2Error(f"unsupported hardware topology method {method!r}")

    return topology
'''
module = replace_once(
    module,
    "\n\ndef _hardware_manifest(hardware: Any) -> tuple[dict[str, Any], Path]:\n",
    topology_helpers + "\n\ndef _hardware_manifest(hardware: Any) -> tuple[dict[str, Any], Path]:\n",
    "topology helper insertion",
)
module = replace_once(
    module,
    '    selected_rows = [by_index[index] for index in selected]\n'
    '    evidence_inventory = _inventory_tree(root, "hardware evidence")\n',
    '    selected_rows = [by_index[index] for index in selected]\n'
    '    topology_record = _validate_hardware_topology(\n'
    '        root, topology_name, selected, selected_rows\n'
    '    )\n'
    '    evidence_inventory = _inventory_tree(root, "hardware evidence")\n',
    "topology semantic validation",
)
module = replace_once(
    module,
    '        "topology": topology_entry,\n'
    '        "evidence_inventory": evidence_inventory,\n',
    '        "topology": topology_entry,\n'
    '        "topology_record": topology_record,\n'
    '        "evidence_inventory": evidence_inventory,\n',
    "topology record binding",
)
start = module.index("def probe_hardware(")
end = module.index("\n\ndef _cli(", start)
new_probe = r'''def probe_hardware(
    output_dir: Path,
    *,
    nvidia_smi: Path,
    selected_device_indices: Sequence[int],
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = nvidia_smi.expanduser().resolve()
    if not executable.is_file():
        raise Stage2Error(f"nvidia-smi executable is absent: {executable}")
    selected = [int(value) for value in selected_device_indices]
    if not selected or len(set(selected)) != len(selected) or any(value < 0 for value in selected):
        raise Stage2Error("selected device indices must be a nonempty unique nonnegative list")

    platform_system = platform.system()
    platform_payload = {
        "system": platform_system,
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    write_json_atomic(output_dir / "platform.json", platform_payload)

    query_args = [
        str(executable),
        "--query-gpu=index,name,uuid,pci.bus_id,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    query = subprocess.run(query_args, capture_output=True, check=False)
    if query.returncode != 0:
        raise Stage2Error(f"nvidia-smi query failed with exit code {query.returncode}")
    query_path = output_dir / "nvidia-query.csv"
    query_path.write_bytes(query.stdout)
    query_rows = _parse_hardware_query(query_path)
    by_index = {row["index"]: row for row in query_rows}
    if any(index not in by_index for index in selected):
        raise Stage2Error("selected hardware index is absent from the captured query")
    selected_rows = [by_index[index] for index in selected]
    selected_rows_sha256 = sha256_object(selected_rows)

    topology_args = [str(executable), "topo", "-m"]
    topology = subprocess.run(topology_args, capture_output=True, check=False)
    if topology.returncode == 0:
        if not topology.stdout.strip():
            raise Stage2Error("nvidia-smi topology returned empty stdout")
        topology_method = "NVIDIA_SMI_TOPOLOGY_MATRIX"
        native_matrix_observed = True
        interdevice_links_required = len(selected) > 1
    elif platform_system == "Windows" and len(selected) == 1:
        topology_method = "WINDOWS_SINGLE_SELECTED_DEVICE_DECLARATION"
        native_matrix_observed = False
        interdevice_links_required = False
    elif platform_system == "Windows":
        raise Stage2Error(
            "Windows native topology is unavailable and multi-device selection cannot be declared"
        )
    else:
        raise Stage2Error(
            f"nvidia-smi topology failed with exit code {topology.returncode}"
        )

    topology_record = {
        "schema": SCHEMA_HARDWARE_TOPOLOGY,
        "platform_system": platform_system,
        "method": topology_method,
        "selected_device_indices": selected,
        "selected_device_rows_sha256": selected_rows_sha256,
        "native_command": ["nvidia-smi", "topo", "-m"],
        "native_exit_code": topology.returncode,
        "native_stdout": _captured_stream(topology.stdout),
        "native_stderr": _captured_stream(topology.stderr),
        "native_matrix_observed": native_matrix_observed,
        "interdevice_links_required": interdevice_links_required,
    }
    write_json_atomic(output_dir / "nvidia-topology.json", topology_record)
    validated_topology = _validate_hardware_topology(
        output_dir,
        "nvidia-topology.json",
        selected,
        selected_rows,
    )

    receipt = {
        "schema": SCHEMA_HARDWARE_PROBE,
        "selected_device_indices": selected,
        "platform_sha256": sha256_file(output_dir / "platform.json"),
        "device_query_sha256": sha256_file(query_path),
        "topology_sha256": sha256_file(output_dir / "nvidia-topology.json"),
        "topology_payload_sha256": sha256_object(validated_topology),
        "topology_method": validated_topology["method"],
        "native_topology_exit_code": validated_topology["native_exit_code"],
        "native_topology_matrix_observed": validated_topology["native_matrix_observed"],
        "interdevice_links_required": validated_topology["interdevice_links_required"],
        "selected_device_rows_sha256": selected_rows_sha256,
        "nvidia_smi_sha256": sha256_file(executable),
        "query_exit_code": query.returncode,
        "provider_or_model_calls": 0,
    }
    write_json_atomic(output_dir / "probe-receipt.json", receipt)
    return receipt
'''
module = module[:start] + new_probe + module[end:]
module_path.write_text(module, encoding="utf-8", newline="\n")

# Template and launcher use canonical topology JSON.
template_path = Path(
    "experiments/astra_kxr/stage2/control_identity/binding-template.json"
)
template = template_path.read_text(encoding="utf-8")
occurrences = template.count('"topology_path": "nvidia-topology.txt"')
if occurrences != 3:
    raise SystemExit(f"topology template path count differs: {occurrences}")
template_path.write_text(
    template.replace(
        '"topology_path": "nvidia-topology.txt"',
        '"topology_path": "nvidia-topology.json"',
    ),
    encoding="utf-8",
    newline="\n",
)

launcher_path = Path("scripts/Invoke-AstraStage2ControlIdentityBinding.ps1")
launcher = launcher_path.read_text(encoding="utf-8")
launcher = replace_once(
    launcher,
    "$control.hardware.topology_path = 'nvidia-topology.txt'",
    "$control.hardware.topology_path = 'nvidia-topology.json'",
    "launcher topology path",
)
launcher_path.write_text(launcher, encoding="utf-8", newline="\n")

# Existing fixture topology becomes canonical JSON; add four tests.
test_path = Path("tests/test_astra_stage2_control_identity.py")
tests = test_path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    "import copy\nimport json\nimport os\nimport shutil\nimport tempfile\nimport unittest\n",
    "import base64\nimport copy\nimport json\nimport os\nimport shutil\nimport subprocess\nimport tempfile\nimport unittest\n",
    "test imports",
)
tests = replace_once(
    tests,
    '    SCAFFOLD_TREE_SHA1,\n'
    '    STAGE1_JOIN_HEAD_SHA1,\n'
    '    _assert_public_safe,\n'
    '    bind_control_set,\n',
    '    SCAFFOLD_TREE_SHA1,\n'
    '    SCHEMA_HARDWARE_TOPOLOGY,\n'
    '    STAGE1_JOIN_HEAD_SHA1,\n'
    '    _assert_public_safe,\n'
    '    _hardware_manifest,\n'
    '    bind_control_set,\n',
    "test control-identity imports",
)
tests = replace_once(
    tests,
    '    inventory_binding_config,\n'
    '    validate_binding_config,\n'
    '    verify_control_set,\n',
    '    inventory_binding_config,\n'
    '    probe_hardware,\n'
    '    validate_binding_config,\n'
    '    verify_control_set,\n',
    "test probe import",
)
old_fixture = '''            (hardware_root / "nvidia-topology.txt").write_text(
                f"GPU{index} X\\n",
                encoding="utf-8",
            )
'''
new_fixture = '''            topology_stdout = f"GPU{index} X\\n".encode("utf-8")
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
'''
tests = replace_once(tests, old_fixture, new_fixture, "test topology fixture")
additional_tests = r'''
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
            side_effect=[query, topology],
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Linux",
        ):
            receipt = probe_hardware(
                output,
                nvidia_smi=executable,
                selected_device_indices=[0],
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
            side_effect=[query, topology],
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Windows",
        ):
            receipt = probe_hardware(
                output,
                nvidia_smi=executable,
                selected_device_indices=[0],
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
            side_effect=[query, topology],
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Windows",
        ):
            with self.assertRaisesRegex(Stage2Error, "multi-device selection"):
                probe_hardware(
                    output,
                    nvidia_smi=executable,
                    selected_device_indices=[0, 1],
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
            side_effect=[query, topology],
        ), patch(
            "astra_stage2.control_identity.platform.system",
            return_value="Windows",
        ):
            probe_hardware(
                output,
                nvidia_smi=executable,
                selected_device_indices=[0],
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
'''
tests = replace_once(
    tests,
    '\n\nif __name__ == "__main__":\n    unittest.main()\n',
    "\n" + additional_tests + '\n\nif __name__ == "__main__":\n    unittest.main()\n',
    "additional topology tests",
)
test_path.write_text(tests, encoding="utf-8", newline="\n")

# Release-level LF law test.
release_test_path = Path("tests/test_astra_stage2_control_identity_release.py")
release_tests = release_test_path.read_text(encoding="utf-8")
lf_test = r'''
    def test_28_hash_bound_control_identity_surfaces_are_forced_lf(self) -> None:
        attributes_path = self.repo / ".gitattributes"
        attributes = attributes_path.read_text(encoding="utf-8")
        paths = (
            ".gitattributes",
            "astra_stage2/control_identity.py",
            "experiments/astra_kxr/stage2/control_identity/binding-template.json",
            "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
            "scripts/astra_stage2_bind_controls.ps1",
            "scripts/astra_stage2_bind_controls.py",
            "tests/test_astra_stage2_control_identity.py",
            "tests/test_astra_stage2_control_identity_release.py",
            ".github/workflows/astra-stage2-control-identity.yml",
            ".github/workflows/astra-stage2-control-identity-release.yml",
        )
        for path in paths:
            self.assertIn(f"{path} text eol=lf", attributes)
            worktree = (self.repo / path).read_bytes()
            blob = subprocess.check_output(
                ["git", "-C", str(self.repo), "cat-file", "blob", f"HEAD:{path}"]
            )
            self.assertEqual(worktree, blob, msg=f"raw worktree/blob mismatch: {path}")
            self.assertNotIn(b"\r\n", worktree, msg=f"CRLF retained: {path}")
'''
release_tests = replace_once(
    release_tests,
    '\n\nif __name__ == "__main__":\n    unittest.main()\n',
    "\n" + lf_test + '\n\nif __name__ == "__main__":\n    unittest.main()\n',
    "release LF test",
)
release_test_path.write_text(release_tests, encoding="utf-8", newline="\n")

# Existing exact-head release workflow now qualifies 32 tests, Windows LF
# materialization, and the explicit Windows single-device topology path.
workflow_path = Path(".github/workflows/astra-stage2-control-identity-release.yml")
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("27-test", "32-test")
workflow = workflow.replace("Ran 27 tests in ", "Ran 32 tests in ")
workflow = workflow.replace("denominator is not 27", "denominator is not 32")
workflow = workflow.replace("tests = 27", "tests = 32")
workflow = workflow.replace('"tests=27"', '"tests=32"')
workflow = workflow.replace('match != ["27"]', 'match != ["32"]')
workflow = workflow.replace('"tests": 27', '"tests": 32')
workflow = workflow.replace('"binder_tests": 20', '"binder_tests": 24')
workflow = workflow.replace('"release_tests": 7', '"release_tests": 8')
workflow = workflow.replace("passed = 26", "passed = 31")
workflow = workflow.replace(
    '          expected = {\n              ".github/workflows/astra-stage2-control-identity-release.yml",',
    '          expected = {\n              ".gitattributes",\n              ".github/workflows/astra-stage2-control-identity-release.yml",',
)
workflow = workflow.replace(
    '              ".github/workflows/astra-stage2-control-identity.yml",\n'
    '              "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",',
    '              ".github/workflows/astra-stage2-control-identity.yml",\n'
    '              "astra_stage2/control_identity.py",\n'
    '              "experiments/astra_kxr/stage2/control_identity/binding-template.json",\n'
    '              "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",',
)

lf_anchor = "      - name: Run complete 32-test suite on Windows\n"
lf_step = r'''      - name: Verify LF materialization under core.autocrlf=true
        id: lf_checkout
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          $sourceRoot = (Get-Location).Path
          $cloneRoot = Join-Path $env:RUNNER_TEMP 'astra-control-identity-lf-clone'
          git init $cloneRoot
          if ($LASTEXITCODE -ne 0) { throw 'LF test git init failed' }
          git -C $cloneRoot config core.autocrlf true
          git -C $cloneRoot remote add source $sourceRoot
          if ($LASTEXITCODE -ne 0) { throw 'LF test remote add failed' }
          git -C $cloneRoot fetch --no-tags --depth=1 source HEAD
          if ($LASTEXITCODE -ne 0) { throw 'LF test fetch failed' }
          git -C $cloneRoot checkout --detach FETCH_HEAD
          if ($LASTEXITCODE -ne 0) { throw 'LF test checkout failed' }

          $receipt = Join-Path $env:RUNNER_TEMP 'lf-materialization-receipt.json'
          $env:ASTRA_LF_CLONE = $cloneRoot
          $env:ASTRA_LF_RECEIPT = $receipt
          @'
          import hashlib
          import json
          import os
          import pathlib
          import subprocess

          root = pathlib.Path(os.environ["ASTRA_LF_CLONE"])
          paths = [
              ".gitattributes",
              "astra_stage2/control_identity.py",
              "experiments/astra_kxr/stage2/control_identity/binding-template.json",
              "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
              "scripts/astra_stage2_bind_controls.ps1",
              "scripts/astra_stage2_bind_controls.py",
              "tests/test_astra_stage2_control_identity.py",
              "tests/test_astra_stage2_control_identity_release.py",
              ".github/workflows/astra-stage2-control-identity.yml",
              ".github/workflows/astra-stage2-control-identity-release.yml",
          ]
          files = {}
          for path in paths:
              worktree = (root / path).read_bytes()
              blob = subprocess.check_output(
                  ["git", "-C", str(root), "cat-file", "blob", f"HEAD:{path}"]
              )
              if worktree != blob:
                  raise SystemExit(f"worktree/blob mismatch under autocrlf=true: {path}")
              if b"\r\n" in worktree:
                  raise SystemExit(f"CRLF materialized in hash-bound file: {path}")
              files[path] = {
                  "bytes": len(worktree),
                  "sha256": hashlib.sha256(worktree).hexdigest(),
              }
          value = {
              "schema": "tier-bench/astra-stage2-lf-materialization@1",
              "core_autocrlf": True,
              "path_count": len(files),
              "files": files,
              "result": "PASS",
          }
          pathlib.Path(os.environ["ASTRA_LF_RECEIPT"]).write_text(
              json.dumps(value, sort_keys=True, indent=2) + "\n",
              encoding="utf-8",
              newline="\n",
          )
          '@ | python -
          if ($LASTEXITCODE -ne 0) { throw 'LF materialization verification failed' }
          "receipt=$receipt" >> $env:GITHUB_OUTPUT
          Write-Host 'LF_MATERIALIZATION_PASS'

      - name: Run complete 32-test suite on Windows
'''
workflow = replace_once(workflow, lf_anchor, lf_step, "Windows LF step insertion")

topology_anchor = "      - name: Parse launcher with a terminating PowerShell gate\n"
topology_step = r'''      - name: Exercise Windows single-device topology fallback
        id: topology_fallback
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          $receipt = Join-Path $env:RUNNER_TEMP 'windows-topology-fallback-receipt.json'
          $env:ASTRA_TOPOLOGY_RECEIPT = $receipt
          @'
          import json
          import os
          import pathlib
          import subprocess
          import tempfile
          from unittest.mock import patch

          from astra_stage2.control_identity import probe_hardware
          from astra_stage2.canonical import strict_json_load

          with tempfile.TemporaryDirectory(prefix="astra-win-topology-") as temp:
              root = pathlib.Path(temp)
              executable = root / "nvidia-smi.exe"
              executable.write_bytes(b"synthetic-nvidia-smi")
              query = subprocess.CompletedProcess(
                  [str(executable)],
                  0,
                  stdout=(
                      b"0, Windows GPU, GPU-windows, "
                      b"00000000:01:00.0, 24576, 999.0\n"
                  ),
                  stderr=b"",
              )
              topology = subprocess.CompletedProcess(
                  [str(executable), "topo", "-m"],
                  255,
                  stdout=b"",
                  stderr=b"ERROR: Invalid Argument\n",
              )
              output = root / "evidence"
              with patch(
                  "astra_stage2.control_identity.subprocess.run",
                  side_effect=[query, topology],
              ), patch(
                  "astra_stage2.control_identity.platform.system",
                  return_value="Windows",
              ):
                  probe = probe_hardware(
                      output,
                      nvidia_smi=executable,
                      selected_device_indices=[0],
                  )
              record = strict_json_load(output / "nvidia-topology.json")
              assert record["method"] == (
                  "WINDOWS_SINGLE_SELECTED_DEVICE_DECLARATION"
              )
              assert record["native_exit_code"] == 255
              assert record["native_matrix_observed"] is False
              assert record["interdevice_links_required"] is False
              assert probe["provider_or_model_calls"] == 0
              value = {
                  "schema": (
                      "tier-bench/"
                      "astra-stage2-windows-topology-fallback-conformance@1"
                  ),
                  "runner": "windows-2025",
                  "selected_device_indices": [0],
                  "topology_method": record["method"],
                  "native_exit_code": record["native_exit_code"],
                  "native_matrix_observed": False,
                  "interdevice_links_required": False,
                  "topology_sha256": probe["topology_sha256"],
                  "topology_payload_sha256": probe["topology_payload_sha256"],
                  "provider_or_model_calls": 0,
                  "result": "PASS",
              }
              pathlib.Path(os.environ["ASTRA_TOPOLOGY_RECEIPT"]).write_text(
                  json.dumps(value, sort_keys=True, indent=2) + "\n",
                  encoding="utf-8",
                  newline="\n",
              )
          '@ | python -
          if ($LASTEXITCODE -ne 0) { throw 'Windows topology fallback failed' }
          "receipt=$receipt" >> $env:GITHUB_OUTPUT
          Write-Host 'WINDOWS_SINGLE_DEVICE_TOPOLOGY_FALLBACK_PASS'

      - name: Parse launcher with a terminating PowerShell gate
'''
workflow = replace_once(
    workflow,
    topology_anchor,
    topology_step,
    "Windows topology step insertion",
)
workflow = replace_once(
    workflow,
    '          PREFLIGHT_RECEIPT: ${{ steps.preflight.outputs.receipt }}\n',
    '          PREFLIGHT_RECEIPT: ${{ steps.preflight.outputs.receipt }}\n'
    '          LF_RECEIPT: ${{ steps.lf_checkout.outputs.receipt }}\n'
    '          TOPOLOGY_RECEIPT: ${{ steps.topology_fallback.outputs.receipt }}\n',
    "Windows receipt environment",
)
workflow = replace_once(
    workflow,
    "            launcher_preflight = 'PASS'\n"
    "            preflight_downloads = 0\n",
    "            launcher_preflight = 'PASS'\n"
    "            lf_materialization = 'PASS'\n"
    "            windows_single_device_topology_fallback = 'PASS'\n"
    "            preflight_downloads = 0\n",
    "Windows receipt conformance fields",
)
workflow = replace_once(
    workflow,
    '            preflight_receipt_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $env:PREFLIGHT_RECEIPT).Hash.ToLowerInvariant()\n',
    '            preflight_receipt_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $env:PREFLIGHT_RECEIPT).Hash.ToLowerInvariant()\n'
    '            lf_receipt_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $env:LF_RECEIPT).Hash.ToLowerInvariant()\n'
    '            topology_receipt_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $env:TOPOLOGY_RECEIPT).Hash.ToLowerInvariant()\n',
    "Windows receipt hashes",
)
workflow = replace_once(
    workflow,
    '                  "repository_root_discovery_tested": True,\n'
    '                  "predecessor_workflow_successor_scope": True,\n',
    '                  "repository_root_discovery_tested": True,\n'
    '                  "lf_materialization_under_autocrlf_true": True,\n'
    '                  "windows_single_device_topology_fallback": True,\n'
    '                  "hardware_topology_schema": (\n'
    '                      "tier-bench/astra-stage2-hardware-topology@1"\n'
    '                  ),\n'
    '                  "predecessor_workflow_successor_scope": True,\n',
    "qualification topology/LF fields",
)
workflow = replace_once(
    workflow,
    '              "predecessor_workflow_successor_scope": True,\n'
    '              "actual_control_identities": "UNBOUND",\n',
    '              "predecessor_workflow_successor_scope": True,\n'
    '              "lf_materialization_under_autocrlf_true": True,\n'
    '              "windows_single_device_topology_fallback": True,\n'
    '              "hardware_topology_schema": (\n'
    '                  "tier-bench/astra-stage2-hardware-topology@1"\n'
    '              ),\n'
    '              "actual_control_identities": "UNBOUND",\n',
    "publication topology/LF fields",
)
workflow_path.write_text(workflow, encoding="utf-8", newline="\n")

print("materialized Windows topology and LF repair")
