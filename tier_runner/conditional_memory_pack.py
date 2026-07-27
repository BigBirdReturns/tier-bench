"""Portable conditional-memory pack export and placement profiling.

The pack separates learned lookup capacity from the active model checkpoint. It
supports row-group fp16 scales with int8 or packed int4 codes, plus fp32/fp16/
bf16 reference artifacts. The profiler can leave the pack in VRAM, host RAM,
pinned RAM, or an OS-backed memory map and then replay an exact row-key trace.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import time
from typing import Any

import torch

from .conditional_memory_common import (
    MemoryLabError,
    hash_file,
    hash_json,
    load_json,
    now_utc,
    without_hash,
    write_json,
)

PACK_SCHEMA = "tier-bench/conditional-memory-pack@1"
PACK_PROFILE_SCHEMA = "tier-bench/conditional-memory-pack-profile@1"
PACK_EVALUATION_SCHEMA = "tier-bench/conditional-memory-pack-evaluation@1"
PACK_DTYPES = {"fp32", "fp16", "bf16", "int8", "int4"}
PROFILE_PLACEMENTS = {"vram", "host_ram", "pinned_ram", "mmap"}

_TORCH_DTYPE = {
    "fp32": torch.float32,
    "fp16": torch.float16,
    "bf16": torch.bfloat16,
    "int8": torch.int8,
    "int4": torch.uint8,
}


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _tensor_bytes(value: torch.Tensor) -> bytes:
    return value.detach().to("cpu").contiguous().view(torch.uint8).numpy().tobytes()


def _find_table(state: dict[str, torch.Tensor]) -> tuple[str, torch.Tensor]:
    candidates = [
        (key, value)
        for key, value in state.items()
        if key.endswith("memory_table.weight") and isinstance(value, torch.Tensor)
    ]
    if len(candidates) != 1:
        raise MemoryLabError(
            "checkpoint must contain exactly one memory_table.weight tensor; "
            f"found {len(candidates)}"
        )
    return candidates[0][0], candidates[0][1].detach().to("cpu").contiguous()


def _quantize(
    table: torch.Tensor, *, dtype: str, group_size: int
) -> tuple[torch.Tensor, torch.Tensor | None, dict[str, Any]]:
    if dtype not in PACK_DTYPES:
        raise MemoryLabError(f"pack dtype must be one of {sorted(PACK_DTYPES)}")
    rows, width = table.shape
    source = table.float()
    if dtype in {"fp32", "fp16", "bf16"}:
        values = source.to(_TORCH_DTYPE[dtype]).contiguous()
        return values, None, {
            "padded_width": width,
            "groups_per_row": 0,
            "code_row_bytes": width * values.element_size(),
            "scale_row_bytes": 0,
        }
    if group_size < 8 or group_size > 4096 or group_size & (group_size - 1):
        raise MemoryLabError("group_size must be a power of two between 8 and 4096")
    padded_width = math.ceil(width / group_size) * group_size
    padded = torch.zeros(rows, padded_width, dtype=torch.float32)
    padded[:, :width] = source
    groups = padded.view(rows, -1, group_size)
    qmax = 127 if dtype == "int8" else 7
    qmin = -127 if dtype == "int8" else -8
    scales = groups.abs().amax(dim=-1).clamp_min(1e-12) / qmax
    quantized = torch.round(groups / scales.unsqueeze(-1)).clamp(qmin, qmax).to(torch.int8)
    flat = quantized.view(rows, padded_width)
    if dtype == "int8":
        codes = flat.contiguous()
    else:
        shifted = (flat.to(torch.int16) + 8).to(torch.uint8)
        low = shifted[:, 0::2]
        high = shifted[:, 1::2]
        codes = (low | (high << 4)).contiguous()
    scales = scales.to(torch.float16).contiguous()
    return codes, scales, {
        "padded_width": padded_width,
        "groups_per_row": padded_width // group_size,
        "code_row_bytes": codes.shape[1] * codes.element_size(),
        "scale_row_bytes": scales.shape[1] * scales.element_size(),
    }


def dequantize_rows(
    codes: torch.Tensor,
    scales: torch.Tensor | None,
    manifest: dict[str, Any],
    *,
    runtime_dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    dtype = manifest["quantization"]["dtype"]
    width = manifest["table"]["width"]
    if dtype in {"fp32", "fp16", "bf16"}:
        return codes[:, :width].to(runtime_dtype)
    if scales is None:
        raise MemoryLabError("quantized pack has no scale tensor")
    group_size = manifest["quantization"]["group_size"]
    padded_width = manifest["quantization"]["padded_width"]
    if dtype == "int8":
        values = codes.to(torch.float32)
    elif dtype == "int4":
        raw = codes.to(torch.uint8)
        low = (raw & 0x0F).to(torch.int16) - 8
        high = ((raw >> 4) & 0x0F).to(torch.int16) - 8
        values = torch.stack([low, high], dim=-1).reshape(raw.shape[0], padded_width).float()
    else:
        raise MemoryLabError(f"unsupported pack dtype {dtype}")
    grouped = values.view(values.shape[0], -1, group_size)
    restored = grouped * scales.to(values.device, dtype=torch.float32).unsqueeze(-1)
    return restored.view(values.shape[0], padded_width)[:, :width].to(runtime_dtype)


def _quantization_error(
    table: torch.Tensor,
    codes: torch.Tensor,
    scales: torch.Tensor | None,
    *,
    dtype: str,
    group_size: int,
    layout: dict[str, Any],
) -> dict[str, Any]:
    sample_count = min(256, table.shape[0])
    if sample_count == table.shape[0]:
        indices = torch.arange(table.shape[0], dtype=torch.long)
    else:
        indices = torch.linspace(0, table.shape[0] - 1, sample_count).round().long().unique()
    sample_codes = codes.index_select(0, indices)
    sample_scales = scales.index_select(0, indices) if scales is not None else None
    provisional = {
        "table": {"width": table.shape[1]},
        "quantization": {
            "dtype": dtype,
            "group_size": group_size if dtype in {"int8", "int4"} else None,
            **layout,
        },
    }
    restored = dequantize_rows(sample_codes, sample_scales, provisional)
    reference = table.index_select(0, indices).float()
    difference = restored.float() - reference
    return {
        "sample_rows": int(indices.numel()),
        "sample_index_sha256": hashlib.sha256(_tensor_bytes(indices)).hexdigest(),
        "max_abs_error": float(difference.abs().max()),
        "mean_abs_error": float(difference.abs().mean()),
        "rmse": float(torch.sqrt(difference.pow(2).mean())),
    }


def _pack_content(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": manifest["schema"],
        "source": {
            "checkpoint_sha256": manifest["source"]["checkpoint_sha256"],
            "receipt_sha256": manifest["source"]["receipt_sha256"],
            "trial_id": manifest["source"]["trial_id"],
            "arm_id": manifest["source"]["arm_id"],
            "architecture": manifest["source"]["architecture"],
            "table_key": manifest["source"]["table_key"],
        },
        "table": manifest["table"],
        "quantization": manifest["quantization"],
        "files": {
            key: (
                None
                if value is None
                else {
                    "bytes": value["bytes"],
                    "sha256": value["sha256"],
                    "shape": value["shape"],
                    "torch_dtype": value["torch_dtype"],
                }
            )
            for key, value in manifest["files"].items()
        },
    }


def export_pack(
    *,
    receipt_path: Path,
    out_dir: Path,
    dtype: str,
    group_size: int = 128,
) -> dict[str, Any]:
    receipt = load_json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("status") != "completed":
        raise MemoryLabError("pack export requires a completed trial receipt")
    if receipt.get("receipt_sha256") != hash_json(without_hash(receipt, "receipt_sha256")):
        raise MemoryLabError("trial receipt hash does not verify")
    model = receipt.get("model") or {}
    checkpoint_value = model.get("checkpoint_path")
    checkpoint_sha = model.get("checkpoint_sha256")
    if not checkpoint_value or not checkpoint_sha:
        raise MemoryLabError("trial did not preserve a checkpoint")
    checkpoint = Path(checkpoint_value)
    if not checkpoint.exists():
        raise MemoryLabError(f"checkpoint does not exist: {checkpoint}")
    observed_checkpoint = hash_file(checkpoint)
    if observed_checkpoint != checkpoint_sha:
        raise MemoryLabError("checkpoint hash does not match the trial receipt")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise MemoryLabError(f"pack directory is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    except TypeError:
        state = torch.load(checkpoint, map_location="cpu")
    if not isinstance(state, dict):
        raise MemoryLabError("checkpoint state must be a mapping")
    table_key, table = _find_table(state)
    codes, scales, layout = _quantize(table, dtype=dtype, group_size=group_size)
    quality = _quantization_error(
        table,
        codes,
        scales,
        dtype=dtype,
        group_size=group_size,
        layout=layout,
    )
    codes_path = out_dir / "codes.bin"
    _atomic_bytes(codes_path, _tensor_bytes(codes))
    scales_path = out_dir / "scales.bin"
    if scales is not None:
        _atomic_bytes(scales_path, _tensor_bytes(scales))
    manifest: dict[str, Any] = {
        "schema": PACK_SCHEMA,
        "created_at": now_utc(),
        "source": {
            "receipt_path": str(receipt_path.resolve()),
            "receipt_sha256": receipt["receipt_sha256"],
            "checkpoint_path": str(checkpoint.resolve()),
            "checkpoint_sha256": checkpoint_sha,
            "trial_id": receipt["trial_id"],
            "arm_id": receipt["arm_id"],
            "architecture": receipt["architecture"],
            "table_key": table_key,
        },
        "table": {
            "rows": table.shape[0],
            "width": table.shape[1],
            "source_dtype": str(table.dtype),
            "source_values": table.numel(),
            "source_bytes": table.numel() * table.element_size(),
            "source_sha256": hashlib.sha256(_tensor_bytes(table)).hexdigest(),
        },
        "quantization": {
            "dtype": dtype,
            "group_size": group_size if dtype in {"int8", "int4"} else None,
            **layout,
        },
        "quality": quality,
        "files": {
            "codes": {
                "path": "codes.bin",
                "bytes": codes_path.stat().st_size,
                "sha256": hash_file(codes_path),
                "shape": list(codes.shape),
                "torch_dtype": str(codes.dtype),
            },
            "scales": (
                {
                    "path": "scales.bin",
                    "bytes": scales_path.stat().st_size,
                    "sha256": hash_file(scales_path),
                    "shape": list(scales.shape),
                    "torch_dtype": str(scales.dtype),
                }
                if scales is not None
                else None
            ),
        },
    }
    artifact_bytes = sum(
        entry["bytes"] for entry in manifest["files"].values() if entry is not None
    )
    manifest["artifact"] = {
        "bytes": artifact_bytes,
        "compression_ratio_vs_source": (
            manifest["table"]["source_bytes"] / artifact_bytes if artifact_bytes else None
        ),
    }
    manifest["pack_sha256"] = hash_json(_pack_content(manifest))
    manifest["manifest_sha256"] = hash_json(manifest)
    write_json(out_dir / "manifest.json", manifest)
    return manifest


def validate_pack(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema") != PACK_SCHEMA:
        raise MemoryLabError(f"pack manifest schema must be {PACK_SCHEMA}")
    try:
        source = manifest["source"]
        table = manifest["table"]
        quantization = manifest["quantization"]
        files = manifest["files"]
        artifact = manifest["artifact"]
        if not all(isinstance(value, dict) for value in (source, table, quantization, files, artifact)):
            raise MemoryLabError("pack manifest sections must be objects")
        rows = table["rows"]
        width = table["width"]
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise MemoryLabError("pack table.rows must be a positive integer")
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise MemoryLabError("pack table.width must be a positive integer")
        if table["source_values"] != rows * width:
            raise MemoryLabError("pack table source_values does not match rows times width")
        dtype_name = quantization["dtype"]
        if dtype_name not in PACK_DTYPES:
            raise MemoryLabError(f"unsupported pack dtype {dtype_name!r}")
        codes_entry = files.get("codes")
        scales_entry = files.get("scales")
        if not isinstance(codes_entry, dict):
            raise MemoryLabError("pack requires a codes file entry")
        if dtype_name in {"int8", "int4"} and not isinstance(scales_entry, dict):
            raise MemoryLabError("integer pack requires a scales file entry")
        if dtype_name in {"fp32", "fp16", "bf16"} and scales_entry is not None:
            raise MemoryLabError("floating-point pack cannot contain a scales file")
    except KeyError as exc:
        raise MemoryLabError(f"pack manifest is missing field {exc.args[0]!r}") from exc

    observed_manifest = manifest.get("manifest_sha256")
    if observed_manifest != hash_json(without_hash(manifest, "manifest_sha256")):
        raise MemoryLabError("pack manifest hash does not verify")
    if manifest.get("pack_sha256") != hash_json(_pack_content(manifest)):
        raise MemoryLabError("pack content hash does not verify")
    root = manifest_path.resolve().parent
    total_bytes = 0
    for key in ("codes", "scales"):
        entry = files.get(key)
        if entry is None:
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or Path(relative).name != relative:
            raise MemoryLabError(f"pack file path must be one local filename: {relative!r}")
        path = (root / relative).resolve()
        if path.parent != root:
            raise MemoryLabError(f"pack file escapes its manifest directory: {relative!r}")
        expected_bytes = entry.get("bytes")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int):
            raise MemoryLabError(f"pack file bytes must be an integer: {relative!r}")
        if not path.exists() or path.stat().st_size != expected_bytes:
            raise MemoryLabError(f"pack file size mismatch: {path}")
        if hash_file(path) != entry.get("sha256"):
            raise MemoryLabError(f"pack file hash mismatch: {path}")
        shape = entry.get("shape")
        if (
            not isinstance(shape, list)
            or not shape
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in shape)
        ):
            raise MemoryLabError(f"pack file shape is invalid: {relative!r}")
        total_bytes += expected_bytes
    if artifact.get("bytes") != total_bytes:
        raise MemoryLabError("pack artifact byte total does not match its files")
    return manifest, root


def _mapped_tensor(path: Path, *, shape: list[int], dtype: torch.dtype) -> torch.Tensor:
    count = math.prod(shape)
    return torch.from_file(str(path), shared=False, size=count, dtype=dtype).view(*shape)


def _load_pack_tensors(
    manifest: dict[str, Any],
    root: Path,
    *,
    placement: str,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor | None]:
    if placement not in PROFILE_PLACEMENTS:
        raise MemoryLabError(f"placement must be one of {sorted(PROFILE_PLACEMENTS)}")
    dtype_name = manifest["quantization"]["dtype"]
    codes_entry = manifest["files"]["codes"]
    codes_dtype = _TORCH_DTYPE[dtype_name]
    codes_path = root / codes_entry["path"]
    if placement == "mmap":
        codes = _mapped_tensor(codes_path, shape=codes_entry["shape"], dtype=codes_dtype)
    else:
        codes = _mapped_tensor(codes_path, shape=codes_entry["shape"], dtype=codes_dtype).clone()
    scale_entry = manifest["files"].get("scales")
    scales = None
    if scale_entry is not None:
        scale_path = root / scale_entry["path"]
        if placement == "mmap":
            scales = _mapped_tensor(scale_path, shape=scale_entry["shape"], dtype=torch.float16)
        else:
            scales = _mapped_tensor(
                scale_path, shape=scale_entry["shape"], dtype=torch.float16
            ).clone()
    if placement == "vram":
        if device.type != "cuda":
            raise MemoryLabError("vram placement requires a CUDA device")
        codes = codes.to(device)
        scales = scales.to(device) if scales is not None else None
    elif placement == "pinned_ram" and device.type == "cuda":
        codes = codes.pin_memory()
        scales = scales.pin_memory() if scales is not None else None
    return codes, scales


def _key_trace(
    *, rows: int, batch_rows: int, iterations: int, seed: int, pattern: str
) -> torch.Tensor:
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    if pattern == "random":
        return torch.randint(0, rows, (iterations, batch_rows), generator=generator)
    if pattern == "hotset":
        hot = max(1, min(rows, max(16, rows // 100)))
        return torch.randint(0, hot, (iterations, batch_rows), generator=generator)
    if pattern == "sequential":
        values = torch.arange(iterations * batch_rows, dtype=torch.long) % rows
        return values.view(iterations, batch_rows)
    raise MemoryLabError("key pattern must be random, hotset, or sequential")


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def profile_pack(
    *,
    manifest_path: Path,
    placement: str,
    device: torch.device,
    batch_rows: int,
    iterations: int,
    warmup: int,
    seed: int,
    pattern: str,
    out: Path,
    seat_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if out.exists():
        raise MemoryLabError(f"append-only pack profile already exists: {out}")
    if batch_rows < 1:
        raise MemoryLabError("batch_rows must be at least 1")
    if iterations < 1:
        raise MemoryLabError("iterations must be at least 1")
    if warmup < 0:
        raise MemoryLabError("warmup must be non-negative")
    if pattern not in {"random", "hotset", "sequential"}:
        raise MemoryLabError("key pattern must be random, hotset, or sequential")
    manifest, root = validate_pack(manifest_path)
    codes, scales = _load_pack_tensors(
        manifest, root, placement=placement, device=device
    )
    rows = manifest["table"]["rows"]
    trace = _key_trace(
        rows=rows,
        batch_rows=batch_rows,
        iterations=iterations + warmup,
        seed=seed,
        pattern=pattern,
    )
    latencies: list[float] = []
    digest = hashlib.sha256()
    for index, keys in enumerate(trace):
        source_keys = keys.to(codes.device)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        started = time.perf_counter()
        selected_codes = codes.index_select(0, source_keys)
        selected_scales = scales.index_select(0, source_keys) if scales is not None else None
        if selected_codes.device != device:
            selected_codes = selected_codes.to(
                device, non_blocking=placement == "pinned_ram"
            )
            selected_scales = (
                selected_scales.to(device, non_blocking=placement == "pinned_ram")
                if selected_scales is not None
                else None
            )
        values = dequantize_rows(selected_codes, selected_scales, manifest)
        checksum = values.float().sum()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        elapsed = (time.perf_counter() - started) * 1000.0
        digest.update(str(float(checksum.detach().cpu())).encode("ascii"))
        if index >= warmup:
            latencies.append(elapsed)
    code_row_bytes = manifest["quantization"]["code_row_bytes"]
    scale_row_bytes = manifest["quantization"]["scale_row_bytes"]
    compressed_per_iteration = batch_rows * (code_row_bytes + scale_row_bytes)
    logical_per_iteration = batch_rows * manifest["table"]["width"] * 4
    receipt: dict[str, Any] = {
        "schema": PACK_PROFILE_SCHEMA,
        "captured_at": now_utc(),
        "pack_sha256": manifest["pack_sha256"],
        "manifest_path": str(manifest_path.resolve()),
        "placement": placement,
        "device": str(device),
        "seat_resolution": seat_resolution,
        "workload": {
            "pattern": pattern,
            "seed": seed,
            "batch_rows": batch_rows,
            "iterations": iterations,
            "warmup": warmup,
            "unique_rows": int(torch.unique(trace[warmup:]).numel()),
            "key_trace_sha256": hashlib.sha256(_tensor_bytes(trace)).hexdigest(),
        },
        "bytes": {
            "compressed_per_iteration": compressed_per_iteration,
            "logical_fp32_per_iteration": logical_per_iteration,
            "compressed_total": compressed_per_iteration * iterations,
            "logical_fp32_total": logical_per_iteration * iterations,
        },
        "latency_ms": {
            "min": min(latencies),
            "median": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies),
            "mean": sum(latencies) / len(latencies),
        },
        "throughput": {
            "rows_per_second_at_median": batch_rows / (_percentile(latencies, 0.5) / 1000.0),
            "compressed_gib_per_second_at_median": (
                compressed_per_iteration
                / (_percentile(latencies, 0.5) / 1000.0)
                / (1024**3)
            ),
        },
        "output_digest": digest.hexdigest(),
    }
    receipt["profile_sha256"] = hash_json(receipt)
    write_json(out, receipt)
    return receipt


def evaluate_pack(
    *,
    plan: dict[str, Any],
    receipt_path: Path,
    manifest_path: Path,
    device: torch.device,
    out: Path,
    seat_resolution: dict[str, Any] | None = None,
    chunk_rows: int = 4096,
) -> dict[str, Any]:
    """Replay a packed table through the complete model and frozen validation stream.

    The compressed pack is dequantized directly into the checkpoint's existing
    table allocation in bounded row chunks. Placement profiling remains a separate
    receipt so quality loss and data-movement cost cannot conceal one another.
    """
    if out.exists():
        raise MemoryLabError(f"append-only pack evaluation already exists: {out}")
    if chunk_rows < 1:
        raise MemoryLabError("chunk_rows must be at least 1")
    from .conditional_memory_models import ConditionalMemoryLM
    from .conditional_memory_plan import trial_by_id
    from .conditional_memory_report import validate_receipt
    from .conditional_memory_runner import (
        _evaluate,
        _golden_logits,
        materialize_dataset,
        state_dict_sha256,
    )

    receipt = load_json(receipt_path)
    receipt_errors = validate_receipt(receipt, plan)
    if receipt_errors:
        raise MemoryLabError("trial receipt does not verify: " + "; ".join(receipt_errors))
    if receipt["status"] != "completed":
        raise MemoryLabError("pack evaluation requires a completed trial receipt")
    manifest, root = validate_pack(manifest_path)
    if manifest["source"]["receipt_sha256"] != receipt["receipt_sha256"]:
        raise MemoryLabError("pack and evaluation receipt identities differ")
    checkpoint = Path(receipt["model"]["checkpoint_path"])
    if not checkpoint.exists() or hash_file(checkpoint) != receipt["model"]["checkpoint_sha256"]:
        raise MemoryLabError("checkpoint bytes do not match the source receipt")
    trial = trial_by_id(plan, receipt["trial_id"])
    try:
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    except TypeError:
        state = torch.load(checkpoint, map_location="cpu")
    model = ConditionalMemoryLM(trial)
    model.load_state_dict(state, strict=True)
    observed_state = state_dict_sha256(model)
    if observed_state != receipt["model"]["final_state_sha256"]:
        raise MemoryLabError("checkpoint state does not reproduce the source receipt")
    if model.memory_table is None:
        raise MemoryLabError("source trial has no conditional-memory table")
    if [model.memory_table.rows, model.memory_table.width] != [
        manifest["table"]["rows"],
        manifest["table"]["width"],
    ]:
        raise MemoryLabError("pack table dimensions do not match the source model")
    model.configure_device(device)
    codes, scales = _load_pack_tensors(
        manifest, root, placement="mmap", device=torch.device("cpu")
    )
    started = time.perf_counter()
    with torch.no_grad():
        for start in range(0, manifest["table"]["rows"], chunk_rows):
            end = min(start + chunk_rows, manifest["table"]["rows"])
            restored = dequantize_rows(
                codes[start:end],
                scales[start:end] if scales is not None else None,
                manifest,
                runtime_dtype=model.memory_table.weight.dtype,
            )
            model.memory_table.weight.data[start:end].copy_(
                restored.to(model.memory_table.weight.device)
            )
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    replacement_seconds = time.perf_counter() - started
    train, validation, data = materialize_dataset(
        trial["dataset"], trial_seed=trial["seed"]
    )
    del train
    if data["combined_sha256"] != receipt["data"]["combined_sha256"]:
        raise MemoryLabError("current validation stream differs from the source receipt")
    amp = trial["training"]["amp"]
    evaluation = _evaluate(
        model,
        validation,
        batch_size=trial["training"]["batch_size"],
        device=device,
        amp=amp,
    )
    golden = _golden_logits(model, validation, device=device, amp=amp)
    baseline_loss = float(receipt["evaluation"]["validation_loss"])
    packed_loss = float(evaluation["validation_loss"])
    result: dict[str, Any] = {
        "schema": PACK_EVALUATION_SCHEMA,
        "captured_at": now_utc(),
        "plan_sha256": plan["plan_sha256"],
        "trial_id": receipt["trial_id"],
        "receipt_sha256": receipt["receipt_sha256"],
        "pack_sha256": manifest["pack_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "device": str(device),
        "seat_resolution": seat_resolution,
        "execution_mode": "bounded_full-table-dequantization-replay",
        "chunk_rows": chunk_rows,
        "replacement_seconds": replacement_seconds,
        "source_final_state_sha256": observed_state,
        "packed_state_sha256": state_dict_sha256(model),
        "data_sha256": data["combined_sha256"],
        "source_evaluation": receipt["evaluation"],
        "packed_evaluation": evaluation,
        "relative_validation_loss_change": (
            (packed_loss - baseline_loss) / baseline_loss if baseline_loss else None
        ),
        "source_golden": receipt.get("golden"),
        "packed_golden": golden,
        "quantization_quality": manifest["quality"],
    }
    result["evaluation_sha256"] = hash_json(result)
    write_json(out, result)
    return result
