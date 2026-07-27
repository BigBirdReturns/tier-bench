"""Physical PyTorch execution for one sealed conditional-memory trial."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import math
import os
from pathlib import Path
import random
import statistics
import time
import traceback
from typing import Any, Iterator

import torch

from .conditional_memory_common import (
    MemoryLabError,
    hash_file,
    hash_json,
    now_utc,
    write_json,
)
from .conditional_memory_models import ConditionalMemoryLM
from .conditional_memory_schema import RECEIPT_SCHEMA


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _tensor_bytes(value: torch.Tensor) -> bytes:
    return value.detach().to("cpu").contiguous().view(torch.uint8).numpy().tobytes()


def tensor_sha256(value: torch.Tensor) -> str:
    return hashlib.sha256(_tensor_bytes(value)).hexdigest()


def state_dict_sha256(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    state = model.state_dict()
    for key in sorted(state):
        tensor = state[key]
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(b"\0")
        digest.update(_tensor_bytes(tensor))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    names = [
        "conditional_memory_common.py",
        "conditional_memory_schema.py",
        "conditional_memory_plan.py",
        "conditional_memory_hardware.py",
        "conditional_memory_models.py",
        "conditional_memory_pack.py",
        "conditional_memory_runner.py",
        "conditional_memory_report.py",
        "conditional_memory_cli.py",
    ]
    result: dict[str, str] = {}
    for name in names:
        path = root / name
        if path.exists():
            result[name] = hash_file(path)
    return result


def _association_mapping(dataset: dict[str, Any], *, seed: int) -> torch.Tensor:
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    token_count = dataset["vocab_size"] - 2
    return torch.randperm(token_count, generator=generator) + 2


def _make_synthetic_sequences(
    dataset: dict[str, Any],
    *,
    count: int,
    seed: int,
    association_mapping: torch.Tensor,
) -> torch.Tensor:
    """Generate a distinct stream against one frozen association world.

    Train and validation must vary by sequence draw while retaining the same
    token-to-token law. Changing the map between splits would test domain shift,
    not whether a conditional-memory table learned the declared associations.
    """
    vocab = dataset["vocab_size"]
    length = dataset["sequence_length"] + 1
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    token_count = vocab - 2
    current = torch.randint(2, vocab, (count,), generator=generator)
    previous = torch.ones(count, dtype=torch.long)
    sequences = torch.empty((count, length), dtype=torch.long)
    sequences[:, 0] = current
    association_cut = dataset["association_rate"]
    bigram_cut = association_cut + dataset["bigram_rate"]
    for position in range(1, length):
        draw = torch.rand(count, generator=generator)
        associated = association_mapping[current - 2]
        bigram = 2 + (
            (previous * 1_000_003 + current * 97_409 + position * 193) % token_count
        )
        random_token = torch.randint(2, vocab, (count,), generator=generator)
        next_token = torch.where(
            draw < association_cut,
            associated,
            torch.where(draw < bigram_cut, bigram, random_token),
        )
        sequences[:, position] = next_token
        previous, current = current, next_token
    return sequences


def _read_uint16_sequences(
    path: Path, *, sequence_length: int, count: int
) -> torch.Tensor:
    expected_values = count * (sequence_length + 1)
    raw = path.read_bytes()
    if len(raw) < expected_values * 2:
        raise MemoryLabError(
            f"token file {path} has {len(raw)} bytes; need at least {expected_values * 2}"
        )
    # Use a writable bytearray so torch does not expose an immutable Python buffer.
    values = torch.frombuffer(
        bytearray(raw[: expected_values * 2]),
        dtype=torch.uint16,
        count=expected_values,
    ).clone()
    return values.to(torch.long).view(count, sequence_length + 1)


def materialize_dataset(
    dataset: dict[str, Any], *, trial_seed: int
) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    data_seed = (dataset["seed"] * 1_000_003 + trial_seed * 97_409) % (2**31 - 1)
    if dataset["kind"] == "synthetic_associations":
        association_mapping = _association_mapping(dataset, seed=data_seed)
        train = _make_synthetic_sequences(
            dataset,
            count=dataset["train_sequences"],
            seed=(data_seed + 11) % (2**31 - 1),
            association_mapping=association_mapping,
        )
        validation = _make_synthetic_sequences(
            dataset,
            count=dataset["validation_sequences"],
            seed=(data_seed + 1_000_000_007) % (2**31 - 1),
            association_mapping=association_mapping,
        )
        source = {
            "kind": dataset["kind"],
            "source_sha256": None,
            "association_mapping_sha256": tensor_sha256(association_mapping),
        }
    elif dataset["kind"] == "uint16_tokens":
        path = Path(dataset["path"]).expanduser().resolve()
        observed = hash_file(path)
        if observed != dataset["sha256"]:
            raise MemoryLabError(
                "training token file hash mismatch: "
                f"expected {dataset['sha256']}, observed {observed}"
            )
        if dataset.get("validation_path"):
            train = _read_uint16_sequences(
                path,
                sequence_length=dataset["sequence_length"],
                count=dataset["train_sequences"],
            )
            validation_path = Path(dataset["validation_path"]).expanduser().resolve()
            validation_hash = hash_file(validation_path)
            if validation_hash != dataset["validation_sha256"]:
                raise MemoryLabError("validation token file hash mismatch")
            validation = _read_uint16_sequences(
                validation_path,
                sequence_length=dataset["sequence_length"],
                count=dataset["validation_sequences"],
            )
        else:
            combined = _read_uint16_sequences(
                path,
                sequence_length=dataset["sequence_length"],
                count=dataset["train_sequences"] + dataset["validation_sequences"],
            )
            train = combined[: dataset["train_sequences"]].clone()
            validation = combined[dataset["train_sequences"] :].clone()
            validation_hash = observed
        source = {
            "kind": dataset["kind"],
            "source_path": str(path),
            "source_sha256": observed,
            "validation_sha256": validation_hash,
        }
    else:
        raise MemoryLabError(f"unsupported dataset kind {dataset['kind']}")
    if int(train.max()) >= dataset["vocab_size"] or int(validation.max()) >= dataset["vocab_size"]:
        raise MemoryLabError("dataset contains token ids outside the configured vocabulary")
    train_hash = tensor_sha256(train)
    validation_hash = tensor_sha256(validation)
    fingerprint = {
        **source,
        "data_seed": data_seed,
        "train_shape": list(train.shape),
        "validation_shape": list(validation.shape),
        "train_sha256": train_hash,
        "validation_sha256": validation_hash,
        "combined_sha256": hash_json(
            {
                "data_seed": data_seed,
                "train_sha256": train_hash,
                "validation_sha256": validation_hash,
            }
        ),
    }
    return train, validation, fingerprint


def _batches(
    sequences: torch.Tensor,
    *,
    batch_size: int,
    generator: torch.Generator,
) -> Iterator[tuple[torch.Tensor, torch.Tensor]]:
    while True:
        indices = torch.randint(0, sequences.shape[0], (batch_size,), generator=generator)
        batch = sequences.index_select(0, indices)
        yield batch[:, :-1], batch[:, 1:]


def _autocast(device: torch.device, amp: str):
    if amp == "off":
        return nullcontext(), None
    if amp == "auto":
        if device.type == "cuda" and torch.cuda.is_bf16_supported():
            amp = "bf16"
        elif device.type == "cuda":
            amp = "fp16"
        else:
            amp = "off"
    if amp == "off":
        return nullcontext(), None
    dtype = torch.bfloat16 if amp == "bf16" else torch.float16
    return torch.autocast(device_type=device.type, dtype=dtype), amp


def _evaluate(
    model: torch.nn.Module,
    validation: torch.Tensor,
    *,
    batch_size: int,
    device: torch.device,
    amp: str,
) -> dict[str, Any]:
    model.eval()
    losses: list[float] = []
    tokens = 0
    start = time.perf_counter()
    with torch.no_grad():
        for offset in range(0, validation.shape[0], batch_size):
            batch = validation[offset : offset + batch_size]
            x = batch[:, :-1].to(device, non_blocking=device.type == "cuda")
            y = batch[:, 1:].to(device, non_blocking=device.type == "cuda")
            context, _ = _autocast(device, amp)
            with context:
                _, loss = model(x, y)
            assert loss is not None
            losses.append(float(loss.detach().float().cpu()))
            tokens += y.numel()
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - start
    mean_loss = statistics.fmean(losses)
    return {
        "validation_loss": mean_loss,
        "perplexity": math.exp(min(mean_loss, 80.0)),
        "tokens": tokens,
        "elapsed_seconds": elapsed,
        "tokens_per_second": tokens / elapsed if elapsed > 0 else None,
    }


def _golden_logits(
    model: torch.nn.Module,
    validation: torch.Tensor,
    *,
    device: torch.device,
    amp: str,
) -> dict[str, Any]:
    model.eval()
    x = validation[:1, :-1].to(device)
    with torch.no_grad():
        context, _ = _autocast(device, amp)
        with context:
            logits, _ = model(x)
    last = logits[0, -1].detach().float().cpu()
    values, indices = torch.topk(last, k=min(10, last.numel()))
    return {
        "prompt_sha256": tensor_sha256(validation[:1, :-1]),
        "logits_sha256": tensor_sha256(last),
        "top_tokens": [
            {"token_id": int(index), "logit": float(value)}
            for value, index in zip(values, indices)
        ],
    }


def _gpu_sample(seat_resolution: dict[str, Any]) -> dict[str, Any] | None:
    gpu = seat_resolution.get("gpu") if isinstance(seat_resolution, dict) else None
    uuid_value = gpu.get("uuid") if isinstance(gpu, dict) else None
    if not uuid_value:
        return None
    from .conditional_memory_hardware import query_nvidia

    rows = query_nvidia()
    observed = next((row for row in rows if row.get("uuid") == uuid_value), None)
    if observed is None:
        raise MemoryLabError(f"resolved trial GPU {uuid_value!r} disappeared during execution")
    return {"captured_at": now_utc(), "gpu": observed}


def _runtime_identity(device: torch.device) -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": os.sys.version,
        "torch": torch.__version__,
        "cuda_build": torch.version.cuda,
        "device": str(device),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(device)
        result["gpu"] = {
            "name": props.name,
            "total_memory_bytes": props.total_memory,
            "compute_capability": [props.major, props.minor],
            "multi_processor_count": props.multi_processor_count,
        }
    return result


def _attempt_root(
    state_dir: Path, *, plan: dict[str, Any], trial: dict[str, Any], attempt: int
) -> Path:
    slug = trial["id"].replace("/", "__").replace(":", "-")
    return (
        state_dir.resolve()
        / plan["lab_id"]
        / plan["profile"]
        / plan["plan_sha256"][:16]
        / slug
        / f"attempt-{attempt:03d}"
    )


def _save_checkpoint(model: torch.nn.Module, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    state = {key: value.detach().to("cpu") for key, value in model.state_dict().items()}
    torch.save(state, temporary)
    temporary.replace(path)
    return hash_file(path)


def _optimizer_bundle(
    model: ConditionalMemoryLM, training: dict[str, Any]
) -> tuple[list[torch.optim.Optimizer], dict[str, Any]]:
    sparse_parameters = model.sparse_parameters()
    sparse_ids = {id(parameter) for parameter in sparse_parameters}
    decay: list[torch.nn.Parameter] = []
    no_decay: list[torch.nn.Parameter] = []
    seen: set[int] = set()
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad or id(parameter) in sparse_ids or id(parameter) in seen:
            continue
        seen.add(id(parameter))
        if parameter.ndim < 2 or "embedding" in name or "norm" in name:
            no_decay.append(parameter)
        else:
            decay.append(parameter)
    groups: list[dict[str, Any]] = []
    if decay:
        groups.append({"params": decay, "weight_decay": training["weight_decay"]})
    if no_decay:
        groups.append({"params": no_decay, "weight_decay": 0.0})
    if not groups:
        raise MemoryLabError("trial produced no trainable dense parameters")
    optimizers: list[torch.optim.Optimizer] = [
        torch.optim.AdamW(groups, lr=training["learning_rate"])
    ]
    identity: dict[str, Any] = {
        "dense": "adamw",
        "dense_decay_parameters": sum(parameter.numel() for parameter in decay),
        "dense_no_decay_parameters": sum(parameter.numel() for parameter in no_decay),
        "conditional_memory": None,
        "sparse_memory_parameters": 0,
    }
    if sparse_parameters:
        optimizers.append(
            torch.optim.SparseAdam(sparse_parameters, lr=training["learning_rate"])
        )
        identity["conditional_memory"] = "sparse_adam"
        identity["sparse_memory_parameters"] = sum(
            parameter.numel() for parameter in sparse_parameters
        )
    return optimizers, identity


def _set_learning_rate(
    optimizers: list[torch.optim.Optimizer], learning_rate: float
) -> None:
    for optimizer in optimizers:
        for group in optimizer.param_groups:
            group["lr"] = learning_rate


def _zero_grad(optimizers: list[torch.optim.Optimizer]) -> None:
    for optimizer in optimizers:
        optimizer.zero_grad(set_to_none=True)


def _clip_gradients(parameters: list[torch.nn.Parameter], max_norm: float) -> float:
    """Clip dense and sparse gradients under one global norm."""
    squared = 0.0
    present: list[torch.Tensor] = []
    for parameter in parameters:
        gradient = parameter.grad
        if gradient is None:
            continue
        if gradient.is_sparse:
            gradient = gradient.coalesce()
            parameter.grad = gradient
            values = gradient.values()
        else:
            values = gradient
        present.append(values)
        squared += float(values.detach().float().pow(2).sum().cpu())
    total = math.sqrt(squared)
    if not present or max_norm <= 0 or total <= max_norm:
        return total
    scale = max_norm / (total + 1e-12)
    for values in present:
        values.mul_(scale)
    return total


def execute_trial(
    *,
    plan: dict[str, Any],
    trial: dict[str, Any],
    state_dir: Path,
    seat_resolution: dict[str, Any],
    attempt: int = 1,
    force_cpu: bool = False,
) -> dict[str, Any]:
    root = _attempt_root(state_dir, plan=plan, trial=trial, attempt=attempt)
    receipt_path = root / "receipt.json"
    if receipt_path.exists():
        raise MemoryLabError(f"append-only receipt already exists: {receipt_path}")
    root.mkdir(parents=True, exist_ok=True)
    started = {
        "schema": "tier-bench/conditional-memory-trial-start@1",
        "started_at": now_utc(),
        "lab_id": plan["lab_id"],
        "profile": plan["profile"],
        "plan_sha256": plan["plan_sha256"],
        "trial_id": trial["id"],
        "arm_id": trial["arm_id"],
        "seed": trial["seed"],
        "seat": trial["seat"],
        "seat_resolution": seat_resolution,
        "attempt": attempt,
        "source_hashes": _source_hashes(),
    }
    started["start_sha256"] = hash_json(started)
    write_json(root / "started.json", started)
    began = time.perf_counter()
    hardware_before: dict[str, Any] | None = None
    try:
        device = torch.device("cpu" if force_cpu or trial["seat"]["kind"] == "cpu" else "cuda:0")
        if device.type == "cuda" and not torch.cuda.is_available():
            raise MemoryLabError("trial requires CUDA but torch reports no CUDA device")
        training = trial["training"]
        measurement = trial["measurement"]
        random.seed(trial["seed"])
        torch.manual_seed(trial["seed"])
        if device.type == "cuda":
            torch.cuda.manual_seed_all(trial["seed"])
        if training["deterministic"]:
            torch.use_deterministic_algorithms(True, warn_only=True)
            if hasattr(torch.backends, "cudnn"):
                torch.backends.cudnn.benchmark = False
                torch.backends.cudnn.deterministic = True
        hardware_before = (
            _gpu_sample(seat_resolution) if measurement["sample_gpu"] else None
        )
        train, validation, data_fingerprint = materialize_dataset(
            trial["dataset"], trial_seed=trial["seed"]
        )
        model = ConditionalMemoryLM(trial)
        model.configure_device(device)
        initial_state_sha256 = state_dict_sha256(model)
        topology = model.topology_ledger(
            train[: min(2, train.shape[0]), :-1]
            if measurement["trace_access"]
            else None
        )
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        optimizers, optimizer_identity = _optimizer_bundle(model, training)
        compiled_model: torch.nn.Module = model
        if training["compile"]:
            if model.sparse_parameters():
                raise MemoryLabError(
                    "training.compile is not qualified with sparse conditional-memory gradients"
                )
            if not hasattr(torch, "compile"):
                raise MemoryLabError("training.compile requested but torch.compile is unavailable")
            compiled_model = torch.compile(model, dynamic=False)
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        batch_generator = torch.Generator(device="cpu")
        batch_generator.manual_seed(trial["seed"] ^ 0x5F3759DF)
        batches = _batches(
            train,
            batch_size=training["batch_size"],
            generator=batch_generator,
        )
        step_times_ms: list[float] = []
        loss_trace: list[dict[str, Any]] = []
        model.train()
        amp_mode = training["amp"]
        resolved_amp: str | None = None
        scaler = None
        if device.type == "cuda" and amp_mode in {"fp16", "auto"}:
            actual = "bf16" if amp_mode == "auto" and torch.cuda.is_bf16_supported() else "fp16"
            if actual == "fp16":
                scaler = torch.amp.GradScaler("cuda")
        for step in range(1, training["steps"] + 1):
            x_cpu, y_cpu = next(batches)
            x = x_cpu.to(device, non_blocking=device.type == "cuda")
            y = y_cpu.to(device, non_blocking=device.type == "cuda")
            warmup = training["warmup_steps"]
            if warmup and step <= warmup:
                lr_scale = step / warmup
            else:
                progress = (step - warmup) / max(training["steps"] - warmup, 1)
                lr_scale = 0.5 * (1.0 + math.cos(math.pi * min(max(progress, 0.0), 1.0)))
            current_lr = training["learning_rate"] * lr_scale
            _set_learning_rate(optimizers, current_lr)
            _zero_grad(optimizers)
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            started_step = time.perf_counter()
            context, actual_amp = _autocast(device, amp_mode)
            resolved_amp = actual_amp or "off"
            with context:
                _, loss = compiled_model(x, y)
            if loss is None or not torch.isfinite(loss):
                raise MemoryLabError(f"non-finite training loss at step {step}")
            if scaler is not None:
                scaler.scale(loss).backward()
                for optimizer in optimizers:
                    scaler.unscale_(optimizer)
                gradient_norm = _clip_gradients(trainable, training["gradient_clip"])
                for optimizer in optimizers:
                    scaler.step(optimizer)
                scaler.update()
            else:
                loss.backward()
                gradient_norm = _clip_gradients(trainable, training["gradient_clip"])
                for optimizer in optimizers:
                    optimizer.step()
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            elapsed_ms = (time.perf_counter() - started_step) * 1000.0
            step_times_ms.append(elapsed_ms)
            if step == 1 or step % training["eval_interval"] == 0 or step == training["steps"]:
                loss_trace.append(
                    {
                        "step": step,
                        "training_loss": float(loss.detach().float().cpu()),
                        "learning_rate": current_lr,
                        "gradient_norm_before_clip": gradient_norm,
                    }
                )
        measurement_offset = min(measurement["warmup_steps"], max(len(step_times_ms) - 1, 0))
        eligible_profile_values = step_times_ms[measurement_offset:] or step_times_ms
        profile_count = min(measurement["profile_steps"], len(eligible_profile_values))
        profile_values = eligible_profile_values[-profile_count:]
        evaluation = _evaluate(
            compiled_model,
            validation,
            batch_size=training["batch_size"],
            device=device,
            amp=amp_mode,
        )
        golden = (
            _golden_logits(compiled_model, validation, device=device, amp=amp_mode)
            if measurement["capture_logits"]
            else None
        )
        final_state_sha256 = state_dict_sha256(model)
        checkpoint_path = root / "checkpoint.pt"
        checkpoint_sha256 = (
            _save_checkpoint(model, checkpoint_path) if training["save_checkpoint"] else None
        )
        peak_allocated = (
            int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else None
        )
        peak_reserved = (
            int(torch.cuda.max_memory_reserved(device)) if device.type == "cuda" else None
        )
        tokens_per_step = training["batch_size"] * trial["dataset"]["sequence_length"]
        median_ms = statistics.median(profile_values)
        hardware_after = (
            _gpu_sample(seat_resolution) if measurement["sample_gpu"] else None
        )
        performance = {
            "measurement_warmup_steps": measurement_offset,
            "profile_steps": profile_count,
            "step_time_ms": {
                "min": min(profile_values),
                "median": median_ms,
                "p95": _percentile(profile_values, 0.95),
                "max": max(profile_values),
                "mean": statistics.fmean(profile_values),
            },
            "training_tokens_per_second": (
                tokens_per_step / (median_ms / 1000.0) if median_ms > 0 else None
            ),
            "peak_cuda_allocated_bytes": peak_allocated,
            "peak_cuda_reserved_bytes": peak_reserved,
            "wall_seconds": time.perf_counter() - began,
        }
        receipt: dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "status": "completed",
            "started_at": started["started_at"],
            "completed_at": now_utc(),
            "lab_id": plan["lab_id"],
            "profile": plan["profile"],
            "lab_sha256": plan["lab_sha256"],
            "plan_sha256": plan["plan_sha256"],
            "trial_id": trial["id"],
            "arm_id": trial["arm_id"],
            "architecture": trial["architecture"],
            "seed": trial["seed"],
            "seat": trial["seat"],
            "seat_resolution": seat_resolution,
            "attempt": attempt,
            "pair_id": trial["pair_id"],
            "paired_baseline_trial_id": trial["paired_baseline_trial_id"],
            "source_hashes": started["source_hashes"],
            "runtime": _runtime_identity(device),
            "hardware": {"before": hardware_before, "after": hardware_after},
            "data": data_fingerprint,
            "model": {
                "arm": trial["arm"],
                "initial_state_sha256": initial_state_sha256,
                "final_state_sha256": final_state_sha256,
                "checkpoint_path": str(checkpoint_path.resolve()) if checkpoint_sha256 else None,
                "checkpoint_sha256": checkpoint_sha256,
                "topology_ledger": topology,
            },
            "training": {
                "config": training,
                "optimizer_identity": optimizer_identity,
                "resolved_amp": resolved_amp,
                "tokens_seen": training["steps"] * tokens_per_step,
                "loss_trace": loss_trace,
                "final_training_loss": loss_trace[-1]["training_loss"],
            },
            "evaluation": evaluation,
            "golden": golden,
            "performance": performance,
            "failure": None,
        }
        receipt["receipt_sha256"] = hash_json(receipt)
        write_json(receipt_path, receipt)
        return receipt
    except Exception as exc:
        failure = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "failed",
            "started_at": started["started_at"],
            "completed_at": now_utc(),
            "lab_id": plan["lab_id"],
            "profile": plan["profile"],
            "lab_sha256": plan["lab_sha256"],
            "plan_sha256": plan["plan_sha256"],
            "trial_id": trial["id"],
            "arm_id": trial["arm_id"],
            "architecture": trial["architecture"],
            "seed": trial["seed"],
            "seat": trial["seat"],
            "seat_resolution": seat_resolution,
            "attempt": attempt,
            "pair_id": trial["pair_id"],
            "paired_baseline_trial_id": trial["paired_baseline_trial_id"],
            "source_hashes": started["source_hashes"],
            "runtime": None,
            "hardware": {"before": hardware_before, "after": None},
            "data": None,
            "model": None,
            "training": None,
            "evaluation": None,
            "golden": None,
            "performance": {"wall_seconds": time.perf_counter() - began},
            "failure": failure,
        }
        receipt["receipt_sha256"] = hash_json(receipt)
        write_json(receipt_path, receipt)
        return receipt
