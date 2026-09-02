"""NVIDIA identity, topology, and monitoring helpers for the memory lab."""
from __future__ import annotations

import csv
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from .conditional_memory_common import (
    MemoryLabError,
    append_jsonl,
    hash_json,
    now_utc,
    write_json,
)
from .conditional_memory_schema import MONITOR_SCHEMA, PROBE_SCHEMA

GPU_FIELDS = (
    "index",
    "uuid",
    "name",
    "memory.total",
    "memory.used",
    "utilization.gpu",
    "power.draw",
    "temperature.gpu",
    "driver_version",
)


def parse_nvidia_csv(text: str, fields: tuple[str, ...] = GPU_FIELDS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in csv.reader(line for line in text.splitlines() if line.strip()):
        if len(raw) != len(fields):
            raise MemoryLabError(
                f"nvidia-smi returned {len(raw)} fields; expected {len(fields)}: {raw!r}"
            )
        row: dict[str, Any] = {}
        for key, value in zip(fields, raw):
            cleaned = value.strip()
            if key in {
                "index",
                "memory.total",
                "memory.used",
                "utilization.gpu",
                "temperature.gpu",
            }:
                try:
                    row[key.replace(".", "_")] = int(float(cleaned))
                except ValueError as exc:
                    raise MemoryLabError(f"cannot parse nvidia-smi {key}: {cleaned!r}") from exc
            elif key == "power.draw":
                try:
                    row["power_draw_w"] = float(cleaned)
                except ValueError:
                    row["power_draw_w"] = None
            else:
                row[key.replace(".", "_")] = cleaned
        rows.append(row)
    return rows


def query_nvidia() -> list[dict[str, Any]]:
    argv = [
        "nvidia-smi",
        "--query-gpu=" + ",".join(GPU_FIELDS),
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise MemoryLabError(f"cannot execute nvidia-smi: {exc}") from exc
    if result.returncode:
        raise MemoryLabError(
            f"nvidia-smi failed ({result.returncode}): {result.stderr.strip()}"
        )
    return parse_nvidia_csv(result.stdout)


def resolve_seat_environment(
    seat: dict[str, Any], *, allow_cpu_override: bool = False
) -> dict[str, Any]:
    """Resolve and mask a seat before importing torch.

    CUDA accepts a GPU UUID in CUDA_VISIBLE_DEVICES. The target then appears as cuda:0,
    which prevents ordinal drift when the 4060 and detachable 3090 seats move.
    """
    if allow_cpu_override or seat["kind"] == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        return {
            "seat_id": seat["id"],
            "kind": "cpu",
            "resolved": True,
            "cuda_visible_devices": "",
        }
    uuid_value = seat.get("gpu_uuid")
    if not uuid_value and seat.get("uuid_env"):
        uuid_value = os.environ.get(seat["uuid_env"])
    if not uuid_value:
        if seat.get("require_identity", True):
            raise MemoryLabError(
                f"seat {seat['id']} requires GPU UUID through {seat.get('uuid_env') or 'gpu_uuid'}"
            )
        return {
            "seat_id": seat["id"],
            "kind": "cuda",
            "resolved": False,
            "reason": "no GPU UUID supplied",
        }
    gpus = query_nvidia()
    match = next((gpu for gpu in gpus if gpu["uuid"] == uuid_value), None)
    if match is None:
        raise MemoryLabError(f"seat {seat['id']} UUID {uuid_value!r} is not present")
    expected = seat.get("expected_name_contains")
    if expected and expected.casefold() not in match["name"].casefold():
        raise MemoryLabError(
            f"seat {seat['id']} expected name containing {expected!r}, observed {match['name']!r}"
        )
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = uuid_value
    return {
        "seat_id": seat["id"],
        "kind": "cuda",
        "resolved": True,
        "cuda_visible_devices": uuid_value,
        "gpu": match,
    }


def resolve_service_gpu(
    topology: dict[str, Any], *, allow_cpu_override: bool = False
) -> dict[str, Any] | None:
    env_name = topology.get("service_gpu_uuid_env")
    if not env_name:
        return None
    if allow_cpu_override:
        return {"resolved": False, "reason": "CPU override", "uuid_env": env_name}
    uuid_value = os.environ.get(env_name)
    if not uuid_value:
        raise MemoryLabError(
            f"service GPU requires UUID through environment variable {env_name}"
        )
    gpus = query_nvidia()
    match = next((gpu for gpu in gpus if gpu["uuid"] == uuid_value), None)
    if match is None:
        raise MemoryLabError(f"service GPU UUID {uuid_value!r} is not present")
    expected = topology.get("service_gpu_expected_name_contains")
    if expected and expected.casefold() not in match["name"].casefold():
        raise MemoryLabError(
            "service GPU expected a name containing "
            f"{expected!r}, observed {match['name']!r}"
        )
    return {
        "resolved": True,
        "uuid_env": env_name,
        "gpu": match,
    }


def probe_hardware() -> dict[str, Any]:
    errors: list[str] = []
    try:
        gpus = query_nvidia()
    except MemoryLabError as exc:
        gpus = []
        errors.append(str(exc))
    result = {
        "schema": PROBE_SCHEMA,
        "captured_at": now_utc(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "gpus": gpus,
        "errors": errors,
    }
    result["probe_sha256"] = hash_json(result)
    return result


def monitor(
    *,
    out: Path,
    stop_file: Path,
    interval_seconds: float = 1.0,
    max_seconds: float | None = None,
) -> dict[str, Any]:
    if interval_seconds < 0.1:
        raise MemoryLabError("monitor interval must be at least 0.1 seconds")
    out.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    samples = 0
    errors = 0
    while not stop_file.exists():
        if max_seconds is not None and time.monotonic() - start >= max_seconds:
            break
        captured = now_utc()
        try:
            gpus = query_nvidia()
            sample = {
                "schema": MONITOR_SCHEMA,
                "captured_at": captured,
                "gpus": gpus,
                "error": None,
            }
        except MemoryLabError as exc:
            errors += 1
            sample = {
                "schema": MONITOR_SCHEMA,
                "captured_at": captured,
                "gpus": [],
                "error": str(exc),
            }
        sample["sample_sha256"] = hash_json(sample)
        append_jsonl(out, [sample])
        samples += 1
        time.sleep(interval_seconds)
    summary = {
        "ok": errors == 0,
        "samples": samples,
        "errors": errors,
        "out": str(out.resolve()),
        "stop_file": str(stop_file.resolve()),
        "elapsed_seconds": round(time.monotonic() - start, 6),
    }
    write_json(out.with_suffix(out.suffix + ".summary.json"), summary)
    return summary
