"""Strict contracts for reproducible conditional-memory experiments."""
from __future__ import annotations

from typing import Any

from .conditional_memory_common import (
    MemoryLabError,
    choice,
    digest,
    need_array,
    need_bool,
    need_int,
    need_number,
    need_object,
    need_text,
    safe_id,
)

LAB_SCHEMA = "tier-bench/conditional-memory-lab@1"
PLAN_SCHEMA = "tier-bench/conditional-memory-plan@1"
RECEIPT_SCHEMA = "tier-bench/conditional-memory-trial-receipt@1"
REPORT_SCHEMA = "tier-bench/conditional-memory-report@1"
PROBE_SCHEMA = "tier-bench/conditional-memory-hardware-probe@1"
MONITOR_SCHEMA = "tier-bench/conditional-memory-monitor-sample@1"

ARCHITECTURES = {
    "dense",
    "big_dense",
    "fat_embedding",
    "ple_no_table",
    "ple",
    "engram_lite",
}
DATASET_KINDS = {"synthetic_associations", "uint16_tokens"}
PLACEMENTS = {"vram", "host_ram", "pinned_ram", "mmap"}
TRAIN_DTYPES = {"fp32", "fp16", "bf16"}
AMP_MODES = {"off", "auto", "fp16", "bf16"}
ASSIGNMENTS = {"paired_crossover", "round_robin", "fixed"}
FAILURE_DEFAULTS = {"hold", "open"}


def _dataset(raw: Any, label: str = "lab.dataset") -> dict[str, Any]:
    row = need_object(raw, label)
    kind = choice(row.get("kind"), f"{label}.kind", DATASET_KINDS)
    vocab_size = need_int(row.get("vocab_size"), f"{label}.vocab_size", low=32, high=2**31)
    sequence_length = need_int(
        row.get("sequence_length"), f"{label}.sequence_length", low=8, high=131072
    )
    normalized: dict[str, Any] = {
        "kind": kind,
        "vocab_size": vocab_size,
        "sequence_length": sequence_length,
        "train_sequences": need_int(
            row.get("train_sequences"), f"{label}.train_sequences", low=8, high=10**9
        ),
        "validation_sequences": need_int(
            row.get("validation_sequences"),
            f"{label}.validation_sequences",
            low=4,
            high=10**8,
        ),
        "seed": need_int(row.get("seed", 1729), f"{label}.seed", high=2**31 - 1),
    }
    if kind == "synthetic_associations":
        normalized.update(
            {
                "association_rate": need_number(
                    row.get("association_rate", 0.60),
                    f"{label}.association_rate",
                    high=1.0,
                ),
                "bigram_rate": need_number(
                    row.get("bigram_rate", 0.25), f"{label}.bigram_rate", high=1.0
                ),
                "random_rate": need_number(
                    row.get("random_rate", 0.15), f"{label}.random_rate", high=1.0
                ),
            }
        )
        total = (
            normalized["association_rate"]
            + normalized["bigram_rate"]
            + normalized["random_rate"]
        )
        if abs(total - 1.0) > 1e-9:
            raise MemoryLabError(
                f"{label} association_rate + bigram_rate + random_rate must equal 1"
            )
    else:
        normalized.update(
            {
                "path": need_text(row.get("path"), f"{label}.path", limit=1000),
                "sha256": digest(row.get("sha256"), f"{label}.sha256"),
                "validation_path": (
                    need_text(
                        row.get("validation_path"), f"{label}.validation_path", limit=1000
                    )
                    if row.get("validation_path") is not None
                    else None
                ),
                "validation_sha256": (
                    digest(
                        row.get("validation_sha256"),
                        f"{label}.validation_sha256",
                    )
                    if row.get("validation_sha256") is not None
                    else None
                ),
            }
        )
        if bool(normalized["validation_path"]) != bool(normalized["validation_sha256"]):
            raise MemoryLabError(
                f"{label}.validation_path and validation_sha256 must be supplied together"
            )
    return normalized


def _model(raw: Any, label: str = "lab.model") -> dict[str, Any]:
    row = need_object(raw, label)
    d_model = need_int(row.get("d_model"), f"{label}.d_model", low=16, high=65536)
    layers = need_int(row.get("layers"), f"{label}.layers", low=1, high=512)
    heads = need_int(row.get("heads"), f"{label}.heads", low=1, high=1024)
    if d_model % heads:
        raise MemoryLabError(f"{label}.d_model must be divisible by heads")
    return {
        "d_model": d_model,
        "layers": layers,
        "heads": heads,
        "ffn_hidden": need_int(
            row.get("ffn_hidden", d_model * 4),
            f"{label}.ffn_hidden",
            low=16,
            high=262144,
        ),
        "dropout": need_number(row.get("dropout", 0.0), f"{label}.dropout", high=0.95),
        "tie_embeddings": need_bool(
            row.get("tie_embeddings", True), f"{label}.tie_embeddings"
        ),
        "bias": need_bool(row.get("bias", False), f"{label}.bias"),
    }


def _training(raw: Any, label: str = "lab.training") -> dict[str, Any]:
    row = need_object(raw, label)
    seeds = [
        need_int(value, f"{label}.seeds[{index}]", high=2**31 - 1)
        for index, value in enumerate(need_array(row.get("seeds"), f"{label}.seeds", nonempty=True))
    ]
    if len(seeds) != len(set(seeds)):
        raise MemoryLabError(f"{label}.seeds must be unique")
    return {
        "seeds": seeds,
        "steps": need_int(row.get("steps"), f"{label}.steps", low=1, high=10**9),
        "batch_size": need_int(
            row.get("batch_size"), f"{label}.batch_size", low=1, high=10**7
        ),
        "learning_rate": need_number(
            row.get("learning_rate"), f"{label}.learning_rate", low=1e-12, high=10.0
        ),
        "weight_decay": need_number(
            row.get("weight_decay", 0.01), f"{label}.weight_decay", high=10.0
        ),
        "warmup_steps": need_int(
            row.get("warmup_steps", 0), f"{label}.warmup_steps", high=10**9
        ),
        "gradient_clip": need_number(
            row.get("gradient_clip", 1.0), f"{label}.gradient_clip", high=10**6
        ),
        "eval_interval": need_int(
            row.get("eval_interval", 100), f"{label}.eval_interval", low=1, high=10**9
        ),
        "amp": choice(row.get("amp", "auto"), f"{label}.amp", AMP_MODES),
        "deterministic": need_bool(
            row.get("deterministic", True), f"{label}.deterministic"
        ),
        "compile": need_bool(row.get("compile", False), f"{label}.compile"),
        "save_checkpoint": need_bool(
            row.get("save_checkpoint", True), f"{label}.save_checkpoint"
        ),
        "optimizer": choice(
            row.get("optimizer", "adamw"), f"{label}.optimizer", {"adamw"}
        ),
    }


def _measurement(raw: Any, label: str = "lab.measurement") -> dict[str, Any]:
    row = need_object(raw, label)
    return {
        "warmup_steps": need_int(
            row.get("warmup_steps", 5), f"{label}.warmup_steps", high=10**6
        ),
        "profile_steps": need_int(
            row.get("profile_steps", 20), f"{label}.profile_steps", low=1, high=10**7
        ),
        "capture_logits": need_bool(
            row.get("capture_logits", True), f"{label}.capture_logits"
        ),
        "trace_access": need_bool(
            row.get("trace_access", True), f"{label}.trace_access"
        ),
        "sample_gpu": need_bool(row.get("sample_gpu", True), f"{label}.sample_gpu"),
    }


def _seat(raw: Any, index: int) -> dict[str, Any]:
    label = f"lab.topology.seats[{index}]"
    row = need_object(raw, label)
    kind = choice(row.get("kind", "cuda"), f"{label}.kind", {"cuda", "cpu"})
    identifier = safe_id(row.get("id"), f"{label}.id")
    uuid_env = row.get("uuid_env")
    if uuid_env is not None:
        uuid_env = need_text(uuid_env, f"{label}.uuid_env", limit=120)
    fixed_uuid = row.get("gpu_uuid")
    if fixed_uuid is not None:
        fixed_uuid = need_text(fixed_uuid, f"{label}.gpu_uuid", limit=120)
    if kind == "cuda" and not uuid_env and not fixed_uuid:
        raise MemoryLabError(f"{label} requires uuid_env or gpu_uuid")
    return {
        "id": identifier,
        "kind": kind,
        "uuid_env": uuid_env,
        "gpu_uuid": fixed_uuid,
        "expected_name_contains": (
            need_text(
                row.get("expected_name_contains"),
                f"{label}.expected_name_contains",
                limit=160,
            )
            if row.get("expected_name_contains") is not None
            else None
        ),
        "require_identity": need_bool(
            row.get("require_identity", kind == "cuda"), f"{label}.require_identity"
        ),
    }


def _topology(raw: Any) -> dict[str, Any]:
    label = "lab.topology"
    row = need_object(raw, label)
    seats = [
        _seat(item, index)
        for index, item in enumerate(need_array(row.get("seats"), f"{label}.seats", nonempty=True))
    ]
    identifiers = [seat["id"] for seat in seats]
    if len(identifiers) != len(set(identifiers)):
        raise MemoryLabError(f"{label}.seats ids must be unique")
    assignment = choice(
        row.get("assignment", "paired_crossover"),
        f"{label}.assignment",
        ASSIGNMENTS,
    )
    fixed_assignments = need_object(row.get("fixed_assignments", {}), f"{label}.fixed_assignments")
    unknown = sorted(set(fixed_assignments.values()) - set(identifiers))
    if unknown:
        raise MemoryLabError(f"{label}.fixed_assignments reference unknown seats: {unknown}")
    return {
        "assignment": assignment,
        "seats": seats,
        "fixed_assignments": {
            safe_id(key, f"{label}.fixed_assignments key"): safe_id(
                value, f"{label}.fixed_assignments[{key}]"
            )
            for key, value in fixed_assignments.items()
        },
        "service_gpu_uuid_env": (
            need_text(
                row.get("service_gpu_uuid_env"),
                f"{label}.service_gpu_uuid_env",
                limit=120,
            )
            if row.get("service_gpu_uuid_env") is not None
            else None
        ),
        "service_gpu_expected_name_contains": (
            need_text(
                row.get("service_gpu_expected_name_contains"),
                f"{label}.service_gpu_expected_name_contains",
                limit=160,
            )
            if row.get("service_gpu_expected_name_contains") is not None
            else None
        ),
    }


def _memory(
    raw: Any,
    *,
    arm_id: str,
    architecture: str,
    model: dict[str, Any],
    vocab: int,
) -> dict[str, Any]:
    label = f"arm {arm_id}.memory"
    row = need_object(raw or {}, label)
    default_dim = model["d_model"]
    raw_rows = row.get("table_rows", "vocab")
    table_rows = vocab if raw_rows == "vocab" else need_int(
        raw_rows, f"{label}.table_rows", low=1, high=10**12
    )
    injection = row.get("injection_layers", "all")
    if injection == "all":
        injection_layers = list(range(model["layers"]))
    else:
        injection_layers = sorted(
            {
                need_int(value, f"{label}.injection_layers", high=model["layers"] - 1)
                for value in need_array(injection, f"{label}.injection_layers", nonempty=True)
            }
        )
    if architecture in {"dense", "big_dense"}:
        table_rows = 0
        injection_layers = []
    prefetch_layers = need_int(
        row.get("prefetch_layers", 0), f"{label}.prefetch_layers", high=512
    )
    cache_bytes = need_int(
        row.get("cache_bytes", 0), f"{label}.cache_bytes", high=2**63 - 1
    )
    if prefetch_layers:
        raise MemoryLabError(
            f"{label}.prefetch_layers is reserved but not implemented in schema version 1"
        )
    if cache_bytes:
        raise MemoryLabError(
            f"{label}.cache_bytes is reserved but not implemented in schema version 1"
        )
    return {
        "table_rows": table_rows,
        "memory_dim": need_int(
            row.get("memory_dim", default_dim),
            f"{label}.memory_dim",
            low=1,
            high=262144,
        ),
        "ngram_order": need_int(
            row.get("ngram_order", 2), f"{label}.ngram_order", low=1, high=8
        ),
        "injection_layers": injection_layers,
        "placement": choice(row.get("placement", "vram"), f"{label}.placement", PLACEMENTS),
        "storage_dtype": choice(
            row.get("storage_dtype", "fp32"), f"{label}.storage_dtype", TRAIN_DTYPES
        ),
        "runtime_dtype": choice(
            row.get("runtime_dtype", "fp32"), f"{label}.runtime_dtype", TRAIN_DTYPES
        ),
        "prefetch_layers": prefetch_layers,
        "cache_bytes": cache_bytes,
        "artifact_path": (
            need_text(row.get("artifact_path"), f"{label}.artifact_path", limit=1000)
            if row.get("artifact_path") is not None
            else None
        ),
    }


def _arm(raw: Any, index: int, *, base_model: dict[str, Any], vocab: int) -> dict[str, Any]:
    label = f"lab.arms[{index}]"
    row = need_object(raw, label)
    identifier = safe_id(row.get("id"), f"{label}.id")
    architecture = choice(row.get("architecture"), f"{label}.architecture", ARCHITECTURES)
    overrides = need_object(row.get("model_overrides", {}), f"{label}.model_overrides")
    allowed_overrides = {"d_model", "layers", "heads", "ffn_hidden", "dropout", "bias"}
    unknown = sorted(set(overrides) - allowed_overrides)
    if unknown:
        raise MemoryLabError(f"{label}.model_overrides has unknown keys: {unknown}")
    merged = dict(base_model)
    merged.update(overrides)
    model = _model(merged, f"{label}.resolved_model")
    memory = _memory(
        row.get("memory", {}),
        arm_id=identifier,
        architecture=architecture,
        model=model,
        vocab=vocab,
    )
    if architecture == "ple" and memory["table_rows"] < vocab:
        raise MemoryLabError(f"{label}.memory.table_rows must cover the tokenizer vocabulary")
    if architecture == "ple_no_table" and memory["table_rows"] != 0:
        memory["table_rows"] = 0
    if architecture == "fat_embedding" and memory["table_rows"] < vocab:
        raise MemoryLabError(f"{label}.memory.table_rows must cover the tokenizer vocabulary")
    if architecture == "engram_lite" and memory["table_rows"] < 2:
        raise MemoryLabError(f"{label}.memory.table_rows must be at least 2")
    if memory["placement"] == "mmap" and not memory["artifact_path"]:
        raise MemoryLabError(f"{label}.memory.artifact_path is required for mmap placement")
    if memory["placement"] != "mmap" and memory["artifact_path"] is not None:
        raise MemoryLabError(
            f"{label}.memory.artifact_path is accepted only for mmap placement"
        )
    return {
        "id": identifier,
        "architecture": architecture,
        "role": choice(row.get("role", "candidate"), f"{label}.role", {"control", "candidate"}),
        "description": need_text(
            row.get("description", identifier), f"{label}.description", limit=500
        ),
        "model": model,
        "memory": memory,
        "enabled": need_bool(row.get("enabled", True), f"{label}.enabled"),
    }


def _promotion(raw: Any, arm_ids: set[str]) -> dict[str, Any]:
    label = "lab.promotion"
    row = need_object(raw, label)
    baseline = safe_id(row.get("baseline_arm"), f"{label}.baseline_arm")
    if baseline not in arm_ids:
        raise MemoryLabError(f"{label}.baseline_arm is not an enabled arm")
    return {
        "baseline_arm": baseline,
        "min_complete_seeds": need_int(
            row.get("min_complete_seeds", 3),
            f"{label}.min_complete_seeds",
            low=1,
            high=1000,
        ),
        "min_relative_validation_loss_improvement": need_number(
            row.get("min_relative_validation_loss_improvement", 0.02),
            f"{label}.min_relative_validation_loss_improvement",
            high=1.0,
        ),
        "max_p95_step_time_regression": need_number(
            row.get("max_p95_step_time_regression", 0.15),
            f"{label}.max_p95_step_time_regression",
            high=1000.0,
        ),
        "max_peak_memory_regression": need_number(
            row.get("max_peak_memory_regression", 0.10),
            f"{label}.max_peak_memory_regression",
            high=1000.0,
        ),
        "require_seat_balance": need_bool(
            row.get("require_seat_balance", True), f"{label}.require_seat_balance"
        ),
        "require_checkpoint_identity": need_bool(
            row.get("require_checkpoint_identity", True),
            f"{label}.require_checkpoint_identity",
        ),
        "failure_default": choice(
            row.get("failure_default", "hold"),
            f"{label}.failure_default",
            FAILURE_DEFAULTS,
        ),
    }


def _profile(raw: Any, name: str) -> dict[str, Any]:
    label = f"lab.profiles.{name}"
    row = need_object(raw, label)
    result: dict[str, Any] = {}
    for section in ("dataset", "training", "measurement"):
        value = row.get(section, {})
        result[section] = need_object(value, f"{label}.{section}")
    return result


def validate_lab(raw: Any) -> dict[str, Any]:
    lab = need_object(raw, "lab")
    if lab.get("schema") != LAB_SCHEMA:
        raise MemoryLabError(f"lab.schema must be {LAB_SCHEMA}")
    identifier = safe_id(lab.get("id"), "lab.id")
    dataset = _dataset(lab.get("dataset"))
    model = _model(lab.get("model"))
    training = _training(lab.get("training"))
    measurement = _measurement(lab.get("measurement", {}))
    topology = _topology(lab.get("topology"))
    arms = [
        _arm(item, index, base_model=model, vocab=dataset["vocab_size"])
        for index, item in enumerate(need_array(lab.get("arms"), "lab.arms", nonempty=True))
    ]
    arms = [arm for arm in arms if arm["enabled"]]
    arm_ids = [arm["id"] for arm in arms]
    if len(arm_ids) != len(set(arm_ids)):
        raise MemoryLabError("lab.arms ids must be unique")
    control_count = sum(arm["role"] == "control" for arm in arms)
    if control_count != 1:
        raise MemoryLabError("exactly one enabled arm must have role=control")
    profiles_raw = need_object(lab.get("profiles", {}), "lab.profiles")
    profiles = {
        safe_id(name, "lab.profiles key"): _profile(value, name)
        for name, value in profiles_raw.items()
    }
    default_profile = safe_id(lab.get("default_profile", "default"), "lab.default_profile")
    if default_profile != "default" and default_profile not in profiles:
        raise MemoryLabError("lab.default_profile must be default or name a declared profile")
    promotion = _promotion(lab.get("promotion"), set(arm_ids))
    control_id = next(arm["id"] for arm in arms if arm["role"] == "control")
    if promotion["baseline_arm"] != control_id:
        raise MemoryLabError("promotion.baseline_arm must be the enabled control arm")
    return {
        "schema": LAB_SCHEMA,
        "id": identifier,
        "title": need_text(lab.get("title", identifier), "lab.title", limit=300),
        "purpose": need_text(lab.get("purpose", identifier), "lab.purpose", limit=2000),
        "dataset": dataset,
        "model": model,
        "training": training,
        "measurement": measurement,
        "topology": topology,
        "arms": arms,
        "profiles": profiles,
        "default_profile": default_profile,
        "promotion": promotion,
        "state_root": need_text(
            lab.get("state_root", "<tier-runs-root>/ConditionalMemory"),
            "lab.state_root",
            limit=1000,
        ),
    }


def _merge_section(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    result.update(override)
    return result


def resolve_profile(raw: Any, profile: str | None = None) -> dict[str, Any]:
    """Validate the lab and apply a named bounded profile through the same validators."""
    lab = validate_lab(raw)
    selected = profile or lab["default_profile"]
    if selected == "default":
        result = dict(lab)
        result["profile"] = "default"
        return result
    if selected not in lab["profiles"]:
        raise MemoryLabError(f"unknown profile {selected!r}")
    override = lab["profiles"][selected]
    dataset_raw = _merge_section(lab["dataset"], override["dataset"])
    training_raw = _merge_section(lab["training"], override["training"])
    measurement_raw = _merge_section(lab["measurement"], override["measurement"])
    result = dict(lab)
    result["dataset"] = _dataset(dataset_raw, f"lab.profiles.{selected}.resolved_dataset")
    result["training"] = _training(training_raw, f"lab.profiles.{selected}.resolved_training")
    result["measurement"] = _measurement(
        measurement_raw, f"lab.profiles.{selected}.resolved_measurement"
    )
    result["profile"] = selected
    return result
