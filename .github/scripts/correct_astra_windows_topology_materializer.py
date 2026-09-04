from __future__ import annotations

import sys
from pathlib import Path


path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    'end = module.index("\\n\\ndef _cli(", start)',
    'end = module.index("\\n\\ndef binding_template(", start)',
)

start = text.index("new_probe = r'''def probe_hardware(")
end = text.index("'''\nmodule = module[:start] + new_probe + module[end:]", start)
probe_source = '''def probe_hardware(
    *,
    output_dir: Path,
    nvidia_smi: str | None = None,
    device_indices: Sequence[int] | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise Stage2Error("hardware probe output directory must be absent or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    executable_text = nvidia_smi or shutil.which("nvidia-smi")
    if not executable_text:
        raise Stage2Error("nvidia-smi was not found; pass --nvidia-smi explicitly")
    executable = Path(executable_text).expanduser().resolve()
    if not executable.is_file():
        raise Stage2Error(f"nvidia-smi executable is absent: {executable}")

    requested = [int(value) for value in (device_indices or [])]
    if len(set(requested)) != len(requested) or any(value < 0 for value in requested):
        raise Stage2Error("device indices must be unique nonnegative integers")
    selector = [] if not requested else ["-i", ",".join(str(index) for index in requested)]

    def platform_text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    platform_system = platform_text(platform.system())
    platform_record = {
        "schema": SCHEMA_HARDWARE_PROBE,
        "system": platform_system,
        "release": platform_text(platform.release()),
        "version": platform_text(platform.version()),
        "machine": platform_text(platform.machine()),
        "processor": platform_text(
            os.environ.get("PROCESSOR_IDENTIFIER", platform.machine())
        ),
        "python_implementation": platform_text(platform.python_implementation()),
        "python_version": platform_text(platform.python_version()),
        "selected_device_indices": requested,
        "nvidia_smi_executable_sha256": sha256_file(executable),
    }
    write_json_atomic(output_dir / "platform.json", platform_record)

    query_args = [
        str(executable),
        *selector,
        "--query-gpu=index,name,uuid,pci.bus_id,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    query = subprocess.run(query_args, capture_output=True, check=False)
    if query.returncode != 0:
        raise Stage2Error(f"nvidia-smi device query failed with exit {query.returncode}")
    query_path = output_dir / "nvidia-query.csv"
    query_path.write_bytes(query.stdout)
    query_rows = _parse_hardware_query(query_path)
    selected = requested or [row["index"] for row in query_rows]
    if not selected:
        raise Stage2Error("hardware probe selected no devices")
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
            f"nvidia-smi topology query failed with exit {topology.returncode}"
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
    topology_path = output_dir / "nvidia-topology.json"
    write_json_atomic(topology_path, topology_record)
    validated_topology = _validate_hardware_topology(
        output_dir,
        topology_path.name,
        selected,
        selected_rows,
    )

    receipt = {
        "schema": SCHEMA_HARDWARE_PROBE,
        "platform_sha256": sha256_file(output_dir / "platform.json"),
        "device_query_sha256": sha256_file(query_path),
        "topology_sha256": sha256_file(topology_path),
        "topology_payload_sha256": sha256_object(validated_topology),
        "topology_method": validated_topology["method"],
        "native_topology_exit_code": validated_topology["native_exit_code"],
        "native_topology_matrix_observed": validated_topology["native_matrix_observed"],
        "interdevice_links_required": validated_topology["interdevice_links_required"],
        "selected_device_rows_sha256": selected_rows_sha256,
        "selected_device_indices": selected,
        "nvidia_smi_sha256": sha256_file(executable),
        "query_exit_code": query.returncode,
        "provider_or_model_calls": 0,
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    write_json_atomic(output_dir / "probe-receipt.json", receipt)
    return receipt
'''
replacement = "new_probe = r'''" + probe_source + "'''\n"
text = text[:start] + replacement + text[end + 4 :]

write_anchor = 'module_path.write_text(module, encoding="utf-8", newline="\\n")'
write_replacement = '''module = module.replace(
    '"topology_path": "nvidia-topology.txt"',
    '"topology_path": "nvidia-topology.json"',
)
module_path.write_text(module, encoding="utf-8", newline="\\n")'''
if text.count(write_anchor) != 1:
    raise SystemExit(
        f"module write anchor count differs: {text.count(write_anchor)}"
    )
text = text.replace(write_anchor, write_replacement, 1)

fixture_anchor = '''            control["hardware"] = {
                "evidence_root": str(hardware_root),
                "platform_path": "platform.json",
                "device_query_path": "nvidia-query.csv",
                "topology_path": "nvidia-topology.txt",
                "selected_device_indices": [index],
            }
'''
fixture_replacement = '''            control["hardware"] = {
                "evidence_root": str(hardware_root),
                "platform_path": "platform.json",
                "device_query_path": "nvidia-query.csv",
                "topology_path": "nvidia-topology.json",
                "selected_device_indices": [index],
            }
'''
fixture_insert_anchor = 'test_path.write_text(tests, encoding="utf-8", newline="\\n")'
fixture_insert = '''tests = replace_once(
    tests,
    ''' + repr(fixture_anchor) + ''',
    ''' + repr(fixture_replacement) + ''',
    "test hardware topology path",
)
test_path.write_text(tests, encoding="utf-8", newline="\\n")'''
if text.count(fixture_insert_anchor) != 1:
    raise SystemExit(
        f"test write anchor count differs: {text.count(fixture_insert_anchor)}"
    )
text = text.replace(fixture_insert_anchor, fixture_insert, 1)

text = text.replace(
    "receipt = probe_hardware(\n                output,\n                nvidia_smi=executable,\n                selected_device_indices=[0],\n            )",
    "receipt = probe_hardware(\n                output_dir=output,\n                nvidia_smi=str(executable),\n                device_indices=[0],\n            )",
)
text = text.replace(
    "probe_hardware(\n                    output,\n                    nvidia_smi=executable,\n                    selected_device_indices=[0, 1],\n                )",
    "probe_hardware(\n                    output_dir=output,\n                    nvidia_smi=str(executable),\n                    device_indices=[0, 1],\n                )",
)
text = text.replace(
    "probe_hardware(\n                output,\n                nvidia_smi=executable,\n                selected_device_indices=[0],\n            )",
    "probe_hardware(\n                output_dir=output,\n                nvidia_smi=str(executable),\n                device_indices=[0],\n            )",
)
text = text.replace(
    "probe = probe_hardware(\n                      output,\n                      nvidia_smi=executable,\n                      selected_device_indices=[0],\n                  )",
    "probe = probe_hardware(\n                      output_dir=output,\n                      nvidia_smi=str(executable),\n                      device_indices=[0],\n                  )",
)
path.write_text(text, encoding="utf-8", newline="\n")
