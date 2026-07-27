"""Static and sampled analysis of a local Kimi K3 weight estate."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time
from typing import Any, Iterable, Iterator

from .kimi3_common import (
    BASELINE_SCHEMA,
    DISSECTION_PLAN_SCHEMA,
    KimiObservatoryError,
    MODEL_SCAN_SCHEMA,
    TENSOR_CENSUS_SCHEMA,
    atomic_write_bytes,
    canonical_bytes,
    hash_json,
    is_partial_download,
    load_json,
    now_utc,
    relative_posix,
    sha256_stream,
    stable_file,
    write_json,
)

SAFETENSOR_SUFFIX = ".safetensors"
SMALL_FULL_HASH_LIMIT = 64 * 1024 * 1024
DEFAULT_CHUNK_BYTES = 256 * 1024 * 1024
MAX_SAFETENSORS_HEADER = 512 * 1024 * 1024
JSON_METADATA_NAMES = {
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "preprocessor_config.json",
    "processor_config.json",
    "special_tokens_map.json",
    "chat_template.json",
    "params.json",
}
SOURCE_SUFFIXES = {".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml"}
DTYPE_BYTES = {
    "BOOL": 1,
    "U8": 1,
    "I8": 1,
    "F8_E4M3": 1,
    "F8_E5M2": 1,
    "I16": 2,
    "U16": 2,
    "F16": 2,
    "BF16": 2,
    "I32": 4,
    "U32": 4,
    "F32": 4,
    "I64": 8,
    "U64": 8,
    "F64": 8,
}
ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("vision", re.compile(r"(vision|vit|image|visual|moonvit)", re.I)),
    ("embedding", re.compile(r"(embed|tok_embeddings|word_embeddings)", re.I)),
    ("output", re.compile(r"(lm_head|output_layer|output\.weight|final_logits)", re.I)),
    ("router", re.compile(r"(router|gate|gating|score_correction)", re.I)),
    ("expert_scale", re.compile(r"(scale|amax|inv_scale|weight_scale).*(expert)|expert.*(scale|amax)", re.I)),
    ("expert", re.compile(r"(experts?|moe|ffn).*(weight|bias)|experts?\.", re.I)),
    ("kda", re.compile(r"(kda|delta_attention|linear_attention|gated_delta)", re.I)),
    ("mla", re.compile(r"(mla|latent_attention|kv_a|kv_b|q_a|q_b)", re.I)),
    ("attn_residual", re.compile(r"(attnres|attention_residual|residual_attn|depth_attn)", re.I)),
    ("attention", re.compile(r"(self_attn|attention|q_proj|k_proj|v_proj|o_proj)", re.I)),
    ("normalization", re.compile(r"(norm|ln_|layernorm|rms)", re.I)),
    ("mlp", re.compile(r"(mlp|ffn|up_proj|down_proj|gate_proj)", re.I)),
]
LAYER_PATTERNS = [
    re.compile(r"(?:layers?|blocks?|h)\.(\d+)(?:\.|$)", re.I),
    re.compile(r"(?:layer|block)[_-]?(\d+)(?:\.|_|$)", re.I),
]
EXPERT_PATTERNS = [
    re.compile(r"(?:experts?|expert)\.(\d+)(?:\.|$)", re.I),
    re.compile(r"(?:experts?|expert)[_-]?(\d+)(?:\.|_|$)", re.I),
]


@dataclass(frozen=True)
class TensorRecord:
    name: str
    shard: str
    dtype: str
    shape: list[int]
    data_offsets: list[int]
    data_start: int
    nbytes: int
    role: str
    layer: int | None
    expert: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "shard": self.shard,
            "dtype": self.dtype,
            "shape": self.shape,
            "data_offsets": self.data_offsets,
            "data_start": self.data_start,
            "nbytes": self.nbytes,
            "role": self.role,
            "layer": self.layer,
            "expert": self.expert,
        }


def _file_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "metadata_sha256": hashlib.sha256(
            canonical_bytes(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
        ).hexdigest(),
    }


def _state_path(state_dir: Path, relative: str) -> Path:
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()
    return state_dir / "hashes" / f"{digest}.json"


def _chunk_hashes(
    path: Path,
    *,
    relative: str,
    state_dir: Path,
    chunk_bytes: int,
) -> tuple[list[str], str]:
    identity = _file_identity(path)
    checkpoint_path = _state_path(state_dir, relative)
    chunks: list[str] = []
    if checkpoint_path.exists():
        try:
            checkpoint = load_json(checkpoint_path)
            if (
                checkpoint.get("relative_path") == relative
                and checkpoint.get("size") == identity["size"]
                and checkpoint.get("mtime_ns") == identity["mtime_ns"]
                and checkpoint.get("chunk_bytes") == chunk_bytes
                and isinstance(checkpoint.get("chunks"), list)
                and all(
                    isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item)
                    for item in checkpoint["chunks"]
                )
            ):
                chunks = list(checkpoint["chunks"])
        except KimiObservatoryError:
            chunks = []

    complete_chunks = identity["size"] // chunk_bytes
    if identity["size"] % chunk_bytes:
        complete_chunks += 1
    if len(chunks) > complete_chunks:
        chunks = []

    with path.open("rb") as handle:
        handle.seek(len(chunks) * chunk_bytes)
        while len(chunks) < complete_chunks:
            payload = handle.read(chunk_bytes)
            if not payload:
                raise KimiObservatoryError(f"unexpected EOF while hashing {path}")
            chunks.append(hashlib.sha256(payload).hexdigest())
            if len(chunks) % 8 == 0 or len(chunks) == complete_chunks:
                write_json(
                    checkpoint_path,
                    {
                        "schema": "tier-bench/kimi3-chunk-hash-state@1",
                        "relative_path": relative,
                        "size": identity["size"],
                        "mtime_ns": identity["mtime_ns"],
                        "chunk_bytes": chunk_bytes,
                        "chunks": chunks,
                        "complete": len(chunks) == complete_chunks,
                        "updated_at": now_utc(),
                    },
                )
    tree_digest = hash_json(
        {
            "algorithm": "sha256-chunk-tree-v1",
            "size": identity["size"],
            "chunk_bytes": chunk_bytes,
            "chunks": chunks,
        }
    )
    return chunks, tree_digest


def _classify_role(name: str) -> str:
    for role, pattern in ROLE_PATTERNS:
        if pattern.search(name):
            return role
    return "other"


def _extract_index(name: str, patterns: Iterable[re.Pattern[str]]) -> int | None:
    for pattern in patterns:
        match = pattern.search(name)
        if match:
            return int(match.group(1))
    return None


def parse_safetensors_header(path: Path, *, root: Path) -> tuple[list[TensorRecord], dict[str, Any]]:
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        raw_length = handle.read(8)
        if len(raw_length) != 8:
            raise KimiObservatoryError(f"{path} is too short to be safetensors")
        header_length = struct.unpack("<Q", raw_length)[0]
        if not 2 <= header_length <= MAX_SAFETENSORS_HEADER:
            raise KimiObservatoryError(
                f"{path} has unsafe safetensors header length {header_length}"
            )
        if 8 + header_length > file_size:
            raise KimiObservatoryError(f"{path} safetensors header exceeds file size")
        header_bytes = handle.read(header_length)
    try:
        header = json.loads(header_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KimiObservatoryError(f"invalid safetensors header in {path}: {exc}") from exc
    if not isinstance(header, dict):
        raise KimiObservatoryError(f"safetensors header must be an object: {path}")
    data_start = 8 + header_length
    relative = relative_posix(path, root)
    records: list[TensorRecord] = []
    anomalies: list[str] = []
    maximum_offset = 0
    for name, metadata in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(name, str) or not isinstance(metadata, dict):
            anomalies.append(f"invalid tensor metadata entry: {name!r}")
            continue
        dtype = metadata.get("dtype")
        shape = metadata.get("shape")
        offsets = metadata.get("data_offsets")
        if (
            not isinstance(dtype, str)
            or not isinstance(shape, list)
            or not all(isinstance(dim, int) and dim >= 0 for dim in shape)
            or not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(offset, int) and offset >= 0 for offset in offsets)
            or offsets[1] < offsets[0]
        ):
            anomalies.append(f"invalid tensor record: {name}")
            continue
        maximum_offset = max(maximum_offset, offsets[1])
        nbytes = offsets[1] - offsets[0]
        element_count = math.prod(shape) if shape else 1
        expected = DTYPE_BYTES.get(dtype)
        if expected is not None and element_count * expected != nbytes:
            anomalies.append(
                f"dtype/shape byte mismatch for {name}: "
                f"{element_count}*{expected}!={nbytes}"
            )
        records.append(
            TensorRecord(
                name=name,
                shard=relative,
                dtype=dtype,
                shape=shape,
                data_offsets=offsets,
                data_start=data_start,
                nbytes=nbytes,
                role=_classify_role(name),
                layer=_extract_index(name, LAYER_PATTERNS),
                expert=_extract_index(name, EXPERT_PATTERNS),
            )
        )
    if data_start + maximum_offset > file_size:
        anomalies.append(
            f"tensor data extends beyond shard: {data_start + maximum_offset}>{file_size}"
        )
    return records, {
        "shard": relative,
        "file_size": file_size,
        "header_length": header_length,
        "header_sha256": hashlib.sha256(header_bytes).hexdigest(),
        "data_start": data_start,
        "tensor_count": len(records),
        "maximum_data_offset": maximum_offset,
        "metadata": header.get("__metadata__", {}),
        "anomalies": anomalies,
    }


def _flatten_json(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_json(value[key], child)
    elif isinstance(value, list):
        if len(value) <= 32 and all(not isinstance(item, (dict, list)) for item in value):
            yield prefix, value
        else:
            yield prefix + ".length", len(value)
    else:
        yield prefix, value


def _source_inventory(path: Path, root: Path) -> dict[str, Any]:
    relative = relative_posix(path, root)
    result: dict[str, Any] = {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": sha256_stream(path),
        "kind": path.suffix.lower().lstrip(".") or "text",
    }
    if path.suffix.lower() == ".py" and path.stat().st_size <= 16 * 1024 * 1024:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            result["classes"] = [
                node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            ]
            result["functions"] = [
                node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
            ]
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            result["imports"] = sorted(imports)
            symbols = set(result["classes"]) | set(result["functions"])
            result["architecture_symbols"] = sorted(
                symbol
                for symbol in symbols
                if re.search(
                    r"(KDA|Delta|Attention|Attn|Residual|MoE|Expert|Router|Gate|MLA|Vision|Model)",
                    symbol,
                    re.I,
                )
            )
        except (UnicodeDecodeError, SyntaxError):
            result["parse_error"] = True
    return result


def _read_json_metadata(path: Path, root: Path) -> dict[str, Any]:
    relative = relative_posix(path, root)
    record: dict[str, Any] = {
        "path": relative,
        "sha256": sha256_stream(path),
        "size": path.stat().st_size,
    }
    if path.stat().st_size > 128 * 1024 * 1024:
        record["parse_error"] = "metadata file exceeds 128 MiB"
        return record
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        record["parse_error"] = str(exc)
        return record
    record["top_level_type"] = type(value).__name__
    if isinstance(value, dict):
        selected: dict[str, Any] = {}
        for key, item in _flatten_json(value):
            lowered = key.lower()
            if any(
                token in lowered
                for token in (
                    "architect",
                    "model_type",
                    "hidden",
                    "layer",
                    "expert",
                    "router",
                    "attention",
                    "head",
                    "context",
                    "position",
                    "quant",
                    "dtype",
                    "vision",
                    "vocab",
                )
            ):
                if isinstance(item, (str, int, float, bool, list)) or item is None:
                    selected[key] = item
        record["architecture_fields"] = selected
    return record


def _index_contract(root: Path, observed: dict[str, TensorRecord]) -> dict[str, Any] | None:
    index_path = root / "model.safetensors.index.json"
    if not index_path.exists():
        return None
    raw = load_json(index_path)
    if not isinstance(raw, dict) or not isinstance(raw.get("weight_map"), dict):
        return {
            "path": "model.safetensors.index.json",
            "valid": False,
            "errors": ["weight_map is missing or not an object"],
        }
    weight_map = raw["weight_map"]
    missing_tensors = sorted(set(weight_map) - set(observed))
    unindexed_tensors = sorted(set(observed) - set(weight_map))
    wrong_shards = sorted(
        name
        for name in set(weight_map) & set(observed)
        if weight_map[name] != observed[name].shard
    )
    missing_shards = sorted(
        shard for shard in set(weight_map.values()) if not (root / shard).is_file()
    )
    return {
        "path": "model.safetensors.index.json",
        "valid": not (missing_tensors or unindexed_tensors or wrong_shards or missing_shards),
        "declared_tensor_count": len(weight_map),
        "declared_shard_count": len(set(weight_map.values())),
        "missing_tensors": missing_tensors[:1000],
        "missing_tensors_count": len(missing_tensors),
        "unindexed_tensors": unindexed_tensors[:1000],
        "unindexed_tensors_count": len(unindexed_tensors),
        "wrong_shards": wrong_shards[:1000],
        "wrong_shards_count": len(wrong_shards),
        "missing_shards": missing_shards,
        "metadata": raw.get("metadata", {}),
        "sha256": sha256_stream(index_path),
    }


def scan_model(
    model_root: Path,
    *,
    out_dir: Path,
    state_dir: Path,
    stable_age_seconds: int = 120,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    hash_large_files: bool = False,
    full_hash_large_files: bool = False,
) -> dict[str, Any]:
    model_root = model_root.resolve()
    out_dir = out_dir.resolve()
    state_dir = state_dir.resolve()
    if not model_root.is_dir():
        raise KimiObservatoryError(f"model root is not a directory: {model_root}")
    if out_dir == model_root or model_root in out_dir.parents:
        raise KimiObservatoryError("out_dir must not live inside the model root")
    if chunk_bytes < 1024 * 1024:
        raise KimiObservatoryError("chunk_bytes must be at least 1 MiB")
    out_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    metadata_records: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    shard_headers: list[dict[str, Any]] = []
    tensor_records: list[TensorRecord] = []
    current_time = time.time()

    for path in sorted(model_root.rglob("*")):
        if path.is_symlink():
            pending.append(
                {
                    "path": relative_posix(path, model_root),
                    "reason": "symlink_refused",
                }
            )
            continue
        if not path.is_file():
            continue
        relative = relative_posix(path, model_root)
        identity = _file_identity(path)
        record: dict[str, Any] = {
            "path": relative,
            **identity,
            "suffix": path.suffix.lower(),
            "stable": stable_file(
                path,
                stable_age_seconds=stable_age_seconds,
                current_time=current_time,
            ),
        }
        if is_partial_download(path) or not record["stable"]:
            pending.append(
                {
                    "path": relative,
                    "size": identity["size"],
                    "mtime_ns": identity["mtime_ns"],
                    "reason": "partial_suffix" if is_partial_download(path) else "not_stable_yet",
                }
            )
            files.append(record)
            continue

        if identity["size"] <= SMALL_FULL_HASH_LIMIT:
            record["sha256"] = sha256_stream(path)
            record["hash_kind"] = "full_sha256"
        elif hash_large_files or full_hash_large_files:
            chunks, tree = _chunk_hashes(
                path,
                relative=relative,
                state_dir=state_dir,
                chunk_bytes=chunk_bytes,
            )
            record["chunk_bytes"] = chunk_bytes
            record["chunk_count"] = len(chunks)
            record["chunk_tree_sha256"] = tree
            record["hash_kind"] = "chunk_tree_sha256"
            if full_hash_large_files:
                record["sha256"] = sha256_stream(path)
                record["hash_kind"] = "full_sha256+chunk_tree"
        else:
            record["hash_kind"] = "metadata_only"

        if path.name in JSON_METADATA_NAMES:
            metadata_records.append(_read_json_metadata(path, model_root))
        if path.suffix.lower() in SOURCE_SUFFIXES and path.name not in JSON_METADATA_NAMES:
            if identity["size"] <= 16 * 1024 * 1024:
                source_records.append(_source_inventory(path, model_root))
        if path.suffix.lower() == SAFETENSOR_SUFFIX:
            try:
                tensors, header = parse_safetensors_header(path, root=model_root)
                tensor_records.extend(tensors)
                shard_headers.append(header)
            except KimiObservatoryError as exc:
                shard_headers.append(
                    {
                        "shard": relative,
                        "file_size": identity["size"],
                        "parse_error": str(exc),
                        "anomalies": [str(exc)],
                    }
                )
        files.append(record)

    tensor_path = out_dir / "tensors.jsonl"
    tensor_payload = b"".join(canonical_bytes(row.as_dict()) for row in tensor_records)
    atomic_write_bytes(tensor_path, tensor_payload)
    observed = {row.name: row for row in tensor_records}
    index_contract = _index_contract(model_root, observed)

    role_bytes = Counter()
    dtype_bytes = Counter()
    layer_tensors: dict[int, int] = Counter()
    layer_bytes: dict[int, int] = Counter()
    layer_experts: dict[int, set[int]] = defaultdict(set)
    global_experts: set[int] = set()
    unsupported_dtypes: Counter[str] = Counter()
    shape_counts: Counter[str] = Counter()
    for row in tensor_records:
        role_bytes[row.role] += row.nbytes
        dtype_bytes[row.dtype] += row.nbytes
        shape_counts["x".join(map(str, row.shape))] += 1
        if row.layer is not None:
            layer_tensors[row.layer] += 1
            layer_bytes[row.layer] += row.nbytes
        if row.expert is not None:
            global_experts.add(row.expert)
            if row.layer is not None:
                layer_experts[row.layer].add(row.expert)
        if row.dtype not in DTYPE_BYTES:
            unsupported_dtypes[row.dtype] += 1

    topology_signatures: dict[int, str] = {}
    by_layer_role_shape: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    for row in tensor_records:
        if row.layer is not None:
            normalized_name = re.sub(r"(?<=\.)\d+(?=\.)", "#", row.name)
            by_layer_role_shape[row.layer].append(
                (row.role, row.dtype, "x".join(map(str, row.shape)) + ":" + normalized_name)
            )
    for layer, rows in by_layer_role_shape.items():
        topology_signatures[layer] = hash_json(sorted(rows))

    census = {
        "schema": TENSOR_CENSUS_SCHEMA,
        "model_root_name": model_root.name,
        "created_at": now_utc(),
        "tensor_count": len(tensor_records),
        "tensor_bytes": sum(row.nbytes for row in tensor_records),
        "shard_count": len(shard_headers),
        "roles": dict(sorted(role_bytes.items())),
        "dtypes": dict(sorted(dtype_bytes.items())),
        "unsupported_dtypes": dict(sorted(unsupported_dtypes.items())),
        "layer_count_observed": len(layer_tensors),
        "layers": [
            {
                "layer": layer,
                "tensor_count": layer_tensors[layer],
                "tensor_bytes": layer_bytes[layer],
                "expert_count": len(layer_experts.get(layer, set())),
                "experts": sorted(layer_experts.get(layer, set()))[:2048],
                "topology_sha256": topology_signatures.get(layer),
            }
            for layer in sorted(layer_tensors)
        ],
        "global_expert_count": len(global_experts),
        "global_experts": sorted(global_experts)[:4096],
        "common_shapes": [
            {"shape": shape, "count": count}
            for shape, count in shape_counts.most_common(100)
        ],
        "shards": shard_headers,
        "tensor_index": {
            "path": tensor_path.name,
            "sha256": hashlib.sha256(tensor_payload).hexdigest(),
            "format": "jsonl",
        },
        "index_contract": index_contract,
    }
    census["census_sha256"] = hash_json(
        {key: value for key, value in census.items() if key not in {"created_at", "census_sha256"}}
    )
    write_json(out_dir / "tensor-census.json", census)

    content_bindings: list[dict[str, Any]] = []
    for row in files:
        binding: dict[str, Any] = {
            "path": row["path"],
            "size": row["size"],
            "stable": row["stable"],
            "hash_kind": row.get("hash_kind"),
        }
        if "sha256" in row:
            binding["sha256"] = row["sha256"]
        if "chunk_tree_sha256" in row:
            binding["chunk_tree_sha256"] = row["chunk_tree_sha256"]
            binding["chunk_bytes"] = row.get("chunk_bytes")
            binding["chunk_count"] = row.get("chunk_count")
        content_bindings.append(binding)
    model_estate_sha256 = hash_json(
        {
            "model_root_name": model_root.name,
            "files": content_bindings,
            "pending_files": [
                {
                    "path": row.get("path"),
                    "size": row.get("size"),
                    "reason": row.get("reason"),
                }
                for row in pending
            ],
            "tensor_census_sha256": census["census_sha256"],
            "index_sha256": index_contract.get("sha256") if index_contract else None,
        }
    )

    scan = {
        "schema": MODEL_SCAN_SCHEMA,
        "created_at": now_utc(),
        "model_root": str(model_root),
        "model_root_name": model_root.name,
        "model_estate_sha256": model_estate_sha256,
        "content_bindings": content_bindings,
        "policy": {
            "stable_age_seconds": stable_age_seconds,
            "chunk_bytes": chunk_bytes,
            "hash_large_files": hash_large_files,
            "full_hash_large_files": full_hash_large_files,
            "small_full_hash_limit": SMALL_FULL_HASH_LIMIT,
        },
        "files": files,
        "pending_files": pending,
        "metadata": metadata_records,
        "source_inventory": source_records,
        "tensor_census": {
            "path": "tensor-census.json",
            "sha256": census["census_sha256"],
        },
        "totals": {
            "files": len(files),
            "stable_files": sum(1 for row in files if row["stable"]),
            "pending_files": len(pending),
            "bytes": sum(row["size"] for row in files),
            "fully_hashed_files": sum(
                1 for row in files if str(row.get("hash_kind", "")).startswith("full_sha256")
            ),
            "chunk_tree_files": sum(
                1 for row in files if "chunk_tree" in str(row.get("hash_kind", ""))
            ),
            "metadata_only_files": sum(
                1 for row in files if row.get("hash_kind") == "metadata_only"
            ),
            "safetensor_shards": len(shard_headers),
            "tensors": len(tensor_records),
        },
    }
    scan["scan_sha256"] = hash_json({key: value for key, value in scan.items() if key != "scan_sha256"})
    write_json(out_dir / "model-scan.json", scan)
    return scan


def _work_order(
    identifier: str,
    title: str,
    *,
    stage: str,
    executor: str,
    resources: list[str],
    prerequisites: list[str],
    acceptance: list[str],
    status: str = "READY",
    topics: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "stage": stage,
        "executor": executor,
        "resources": resources,
        "prerequisites": prerequisites,
        "acceptance": acceptance,
        "status": status,
        "topics": topics or [],
        "notes": notes,
    }


def build_dissection_plan(scan: dict[str, Any], census: dict[str, Any]) -> dict[str, Any]:
    if scan.get("schema") != MODEL_SCAN_SCHEMA:
        raise KimiObservatoryError("scan has the wrong schema")
    if census.get("schema") != TENSOR_CENSUS_SCHEMA:
        raise KimiObservatoryError("tensor census has the wrong schema")
    pending = scan["totals"]["pending_files"]
    index = census.get("index_contract")
    index_valid = bool(index and index.get("valid"))
    unsupported = sorted(census.get("unsupported_dtypes", {}))
    has_source = bool(scan.get("source_inventory"))
    orders = [
        _work_order(
            "K3-A00-download-convergence",
            "Wait for all declared shards and metadata to become stable",
            stage="custody",
            executor="deterministic_local",
            resources=["cpu", "storage:model"],
            prerequisites=[],
            acceptance=[
                "pending_files == 0",
                "all index-declared shards exist",
                "no safetensors header parse errors",
            ],
            status="BLOCKED" if pending else "READY",
            topics=["download", "custody", "shards"],
        ),
        _work_order(
            "K3-A01-byte-custody",
            "Create resumable chunk-tree custody for every large shard",
            stage="custody",
            executor="deterministic_local",
            resources=["cpu", "storage:model", "storage:state"],
            prerequisites=["K3-A00-download-convergence"],
            acceptance=[
                "every stable large file has a chunk_tree_sha256",
                "chunk state binds file size and mtime",
                "re-scan produces identical model estate digest",
            ],
            topics=["hashing", "custody"],
        ),
        _work_order(
            "K3-A02-index-concordance",
            "Reconcile the Hugging Face weight map with observed shard headers",
            stage="custody",
            executor="deterministic_local",
            resources=["cpu"],
            prerequisites=["K3-A00-download-convergence"],
            acceptance=[
                "zero missing tensors",
                "zero unindexed tensors",
                "zero wrong shard mappings",
                "zero missing shards",
            ],
            status="READY" if index else "BLOCKED",
            topics=["safetensors", "index", "correctness"],
            notes="Current index contract is valid." if index_valid else "Index is absent or not yet concordant.",
        ),
        _work_order(
            "K3-B01-source-architecture-map",
            "Map KDA, MLA, AttnRes, MoE, router, vision, and quantization source symbols",
            stage="static_dissection",
            executor="deterministic_local",
            resources=["cpu"],
            prerequisites=["K3-A00-download-convergence"],
            acceptance=[
                "source files are hash-bound",
                "architecture symbols are indexed without importing remote code",
                "config fields and source symbols have a concordance report",
            ],
            status="READY" if has_source else "BLOCKED",
            topics=["architecture", "source", "KDA", "AttnRes", "MoE"],
        ),
        _work_order(
            "K3-B02-layer-topology",
            "Compare tensor topology across every transformer layer",
            stage="static_dissection",
            executor="deterministic_local",
            resources=["cpu"],
            prerequisites=["K3-A02-index-concordance"],
            acceptance=[
                "every layer has a topology signature",
                "topology outliers are named",
                "dense, hybrid-attention, and MoE transitions are separated",
            ],
            topics=["layers", "topology"],
        ),
        _work_order(
            "K3-B03-expert-estate",
            "Map routed and shared experts, shard locality, and missing expert IDs",
            stage="static_dissection",
            executor="deterministic_local",
            resources=["cpu"],
            prerequisites=["K3-A02-index-concordance"],
            acceptance=[
                "experts are enumerated per layer",
                "shared experts are separated from routed experts",
                "expert tensors and scale tensors are paired",
                "missing or duplicate expert IDs are reported",
            ],
            topics=["experts", "MoE", "offload"],
        ),
        _work_order(
            "K3-B04-precision-map",
            "Map MXFP4 or other packed weights, scale tensors, and unsupported dtypes",
            stage="static_dissection",
            executor="deterministic_local",
            resources=["cpu"],
            prerequisites=["K3-A02-index-concordance"],
            acceptance=[
                "bytes by dtype are reconciled",
                "packed tensors are paired with scale metadata",
                "unsupported dtypes produce explicit decoder work orders",
            ],
            topics=["MXFP4", "quantization", "dtype"],
            notes=("Unsupported dtypes: " + ", ".join(unsupported)) if unsupported else "",
        ),
        _work_order(
            "K3-C01-numeric-fingerprints",
            "Sample deterministic tensor statistics without loading full shards",
            stage="numeric_dissection",
            executor="deterministic_local",
            resources=["cpu", "storage:model"],
            prerequisites=["K3-A02-index-concordance"],
            acceptance=[
                "sample positions are deterministic and hash-bound",
                "finite rate, zero rate, mean, RMS, and extrema are recorded",
                "unsupported packed dtypes remain explicit",
            ],
            topics=["weights", "statistics", "anomaly"],
        ),
        _work_order(
            "K3-C02-expert-redundancy",
            "Cluster expert fingerprints and identify candidate redundancy",
            stage="numeric_dissection",
            executor="local_3090_or_cpu",
            resources=["gpu:3090", "cpu", "ram"],
            prerequisites=["K3-C01-numeric-fingerprints", "K3-B03-expert-estate"],
            acceptance=[
                "same-layer experts are compared under identical sampling",
                "candidate clusters survive a second independent sample",
                "no pruning claim is made from static similarity alone",
            ],
            topics=["experts", "clustering", "pruning"],
        ),
        _work_order(
            "K3-D01-runtime-module-trace",
            "Trace router, KDA, MLA, AttnRes, vision, and expert module execution",
            stage="runtime_dissection",
            executor="remote_open_weight_full_runtime",
            resources=["remote:multi-gpu", "storage:model"],
            prerequisites=["K3-B01-source-architecture-map", "K3-B03-expert-estate"],
            acceptance=[
                "runtime revision matches the frozen weight estate",
                "module names and tensor shapes are captured",
                "trace overhead is measured",
                "raw prompts remain inside the declared custody boundary",
            ],
            topics=["runtime", "hooks", "router", "KDA", "AttnRes"],
        ),
        _work_order(
            "K3-D02-router-utilization-grid",
            "Measure expert routing frequency, entropy, co-activation, and load imbalance",
            stage="runtime_dissection",
            executor="remote_open_weight_full_runtime",
            resources=["remote:multi-gpu"],
            prerequisites=["K3-D01-runtime-module-trace"],
            acceptance=[
                "baseline grid prompts are frozen",
                "routing is recorded per layer and task family",
                "hot, cold, and task-specialized experts are identified",
                "claims include confidence intervals and run revision",
            ],
            topics=["router", "experts", "utilization"],
        ),
        _work_order(
            "K3-D03-long-context-state",
            "Separate KDA recurrent-state, global-attention, and KV costs over context length",
            stage="runtime_dissection",
            executor="remote_open_weight_full_runtime",
            resources=["remote:multi-gpu"],
            prerequisites=["K3-D01-runtime-module-trace"],
            acceptance=[
                "context lengths and cache states are controlled",
                "prefill, decode, state, KV, and retrieval costs remain separate",
                "correctness is graded at every length",
            ],
            topics=["long-context", "KDA", "KV-cache"],
        ),
        _work_order(
            "K3-E01-expert-offload-simulator",
            "Replay observed routing against 24 GiB VRAM, host RAM, and NVMe tiers",
            stage="desktop_translation",
            executor="deterministic_local",
            resources=["cpu", "ram", "storage:nvme"],
            prerequisites=["K3-D02-router-utilization-grid"],
            acceptance=[
                "simulation uses observed expert traces",
                "PCIe, RAM, and NVMe bandwidth are measured locally",
                "predicted tokens per second include transfer stalls",
            ],
            topics=["3090", "expert-offload", "RAM", "NVMe"],
        ),
        _work_order(
            "K3-E02-ablation-grid",
            "Run bounded expert, layer, KDA, AttnRes, and quantization interventions",
            stage="intervention",
            executor="remote_open_weight_full_runtime",
            resources=["remote:multi-gpu"],
            prerequisites=["K3-D02-router-utilization-grid", "K3-D03-long-context-state"],
            acceptance=[
                "one intervention changes at a time",
                "the frozen baseline grid is rerun",
                "quality, attention, latency, and memory remain separate ledgers",
                "every negative result remains preserved",
            ],
            topics=["ablation", "pruning", "quantization"],
        ),
        _work_order(
            "K3-F01-desktop-capture",
            "Convert recurring K3 residue into local source, adapters, curricula, or verifiers",
            stage="capture",
            executor="tierdistill",
            resources=["gpu:3090", "gpu:4060", "cpu"],
            prerequisites=["K3-E02-ablation-grid"],
            acceptance=[
                "capture artifact runs without the teacher",
                "fresh withheld baseline cells clear",
                "cost and operator attention are lower",
                "capture is admitted through the existing ledger",
            ],
            topics=["distillation", "residue", "desktop"],
        ),
    ]
    plan = {
        "schema": DISSECTION_PLAN_SCHEMA,
        "created_at": now_utc(),
        "scan_sha256": scan["scan_sha256"],
        "model_estate_sha256": scan["model_estate_sha256"],
        "tensor_census_sha256": census.get("census_sha256") or hash_json(census),
        "model_root_name": scan["model_root_name"],
        "laws": [
            "Static similarity cannot establish runtime importance.",
            "Community claims remain untrusted hypotheses until reproduced.",
            "No downloaded Python source is imported during static analysis.",
            "Every intervention is compared against the same frozen baseline grid.",
            "Open weights permit mechanistic tests; they do not make one observed result universal.",
            "Reddit content may inform hypotheses but is never admitted as training data by this system.",
        ],
        "work_orders": orders,
        "totals": {
            "orders": len(orders),
            "ready": sum(1 for row in orders if row["status"] == "READY"),
            "blocked": sum(1 for row in orders if row["status"] == "BLOCKED"),
        },
    }
    plan["plan_sha256"] = hash_json(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    return plan


def _decode_scalar(handle: Any, position: int, dtype: str) -> float | int | bool:
    if dtype == "BOOL":
        handle.seek(position)
        return bool(handle.read(1)[0])
    formats = {
        "U8": "<B",
        "I8": "<b",
        "I16": "<h",
        "U16": "<H",
        "I32": "<i",
        "U32": "<I",
        "I64": "<q",
        "U64": "<Q",
        "F16": "<e",
        "F32": "<f",
        "F64": "<d",
    }
    if dtype == "BF16":
        handle.seek(position)
        raw = handle.read(2)
        bits = struct.unpack("<H", raw)[0] << 16
        return struct.unpack("<f", struct.pack("<I", bits))[0]
    if dtype not in formats:
        raise KimiObservatoryError(f"unsupported dtype for numeric sampling: {dtype}")
    size = struct.calcsize(formats[dtype])
    handle.seek(position)
    raw = handle.read(size)
    if len(raw) != size:
        raise KimiObservatoryError("unexpected EOF while sampling tensor")
    return struct.unpack(formats[dtype], raw)[0]


def numeric_sample(
    model_root: Path,
    *,
    tensor_index: Path,
    patterns: list[str],
    max_tensors: int = 256,
    samples_per_tensor: int = 64,
) -> dict[str, Any]:
    if max_tensors < 1 or samples_per_tensor < 1:
        raise KimiObservatoryError("numeric sample limits must be positive")
    compiled = [re.compile(pattern) for pattern in patterns] if patterns else []
    selected: list[dict[str, Any]] = []
    with tensor_index.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise KimiObservatoryError(
                    f"invalid tensor index at line {line_number}: {exc}"
                ) from exc
            if compiled and not any(pattern.search(row["name"]) for pattern in compiled):
                continue
            selected.append(row)
            if len(selected) >= max_tensors:
                break

    results: list[dict[str, Any]] = []
    handles: dict[str, Any] = {}
    try:
        for row in selected:
            dtype = row["dtype"]
            size = DTYPE_BYTES.get(dtype)
            element_count = math.prod(row["shape"]) if row["shape"] else 1
            base = row["data_start"] + row["data_offsets"][0]
            result: dict[str, Any] = {
                "name": row["name"],
                "shard": row["shard"],
                "dtype": dtype,
                "shape": row["shape"],
                "nbytes": row["nbytes"],
                "role": row["role"],
                "layer": row["layer"],
                "expert": row["expert"],
            }
            if size is None:
                result["status"] = "UNSUPPORTED_DTYPE"
                result["reason"] = "decoder plugin required"
                results.append(result)
                continue
            if element_count <= 0:
                result["status"] = "EMPTY"
                results.append(result)
                continue
            sample_count = min(samples_per_tensor, element_count)
            seed = int(hashlib.sha256(row["name"].encode()).hexdigest()[:16], 16)
            indices = sorted(
                {
                    (seed + index * 0x9E3779B97F4A7C15) % element_count
                    for index in range(sample_count * 2)
                }
            )[:sample_count]
            if row["shard"] not in handles:
                handles[row["shard"]] = (model_root / row["shard"]).open("rb")
            shard = handles[row["shard"]]
            values = [
                _decode_scalar(shard, base + index * size, dtype)
                for index in indices
            ]
            numeric = [float(value) for value in values]
            finite = [value for value in numeric if math.isfinite(value)]
            result.update(
                {
                    "status": "SAMPLED",
                    "sample_count": len(values),
                    "sample_index_sha256": hash_json(indices),
                    "finite_rate": len(finite) / len(values),
                    "zero_rate": sum(value == 0 for value in numeric) / len(values),
                    "min": min(finite) if finite else None,
                    "max": max(finite) if finite else None,
                    "mean": sum(finite) / len(finite) if finite else None,
                    "abs_mean": (
                        sum(abs(value) for value in finite) / len(finite) if finite else None
                    ),
                    "rms": (
                        math.sqrt(sum(value * value for value in finite) / len(finite))
                        if finite
                        else None
                    ),
                }
            )
            results.append(result)
    finally:
        for handle in handles.values():
            handle.close()
    report = {
        "schema": "tier-bench/kimi3-numeric-sample@1",
        "created_at": now_utc(),
        "model_root": str(model_root.resolve()),
        "tensor_index": str(tensor_index.resolve()),
        "patterns": patterns,
        "max_tensors": max_tensors,
        "samples_per_tensor": samples_per_tensor,
        "results": results,
        "totals": {
            "selected": len(selected),
            "sampled": sum(1 for row in results if row["status"] == "SAMPLED"),
            "unsupported": sum(
                1 for row in results if row["status"] == "UNSUPPORTED_DTYPE"
            ),
        },
    }
    report["report_sha256"] = hash_json(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def _collect_grid_receipts(grid_root: Path) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    if not grid_root.exists():
        raise KimiObservatoryError(f"grid root does not exist: {grid_root}")
    for path in sorted(grid_root.rglob("*.json")):
        if path.stat().st_size > 64 * 1024 * 1024:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        schema = value.get("schema")
        if not isinstance(schema, str) or not schema.startswith("tier-bench/"):
            continue
        record: dict[str, Any] = {
            "path": path.relative_to(grid_root).as_posix(),
            "sha256": sha256_stream(path),
            "schema": schema,
        }
        for key in ("state", "task_id", "model", "effort", "arm", "verdict"):
            if key in value and isinstance(value[key], (str, int, float, bool)):
                record[key] = value[key]
        call = value.get("call")
        if isinstance(call, dict):
            for key in (
                "model",
                "effort",
                "outcome",
                "input_tokens",
                "output_tokens",
                "cost_usd",
                "latency_ms",
            ):
                if key in call and isinstance(call[key], (str, int, float, bool)):
                    record[f"call.{key}"] = call[key]
        receipts.append(record)
    return receipts


def freeze_baseline(
    *,
    scan_path: Path,
    census_path: Path,
    plan_path: Path,
    grid_root: Path,
    label: str,
) -> dict[str, Any]:
    scan = load_json(scan_path)
    census = load_json(census_path)
    plan = load_json(plan_path)
    if scan.get("schema") != MODEL_SCAN_SCHEMA:
        raise KimiObservatoryError("scan path does not contain a model scan")
    if census.get("schema") != TENSOR_CENSUS_SCHEMA:
        raise KimiObservatoryError("census path does not contain a tensor census")
    if plan.get("schema") != DISSECTION_PLAN_SCHEMA:
        raise KimiObservatoryError("plan path does not contain a dissection plan")
    if scan["totals"]["pending_files"]:
        raise KimiObservatoryError("cannot freeze a baseline while model files are pending")
    unbound = [
        row["path"]
        for row in scan.get("content_bindings", [])
        if row.get("stable")
        and not row.get("sha256")
        and not row.get("chunk_tree_sha256")
    ]
    if unbound:
        raise KimiObservatoryError(
            "cannot freeze a baseline before every stable file has content custody; "
            f"unbound={unbound[:20]}"
        )
    index = census.get("index_contract")
    if index is not None and not index.get("valid"):
        raise KimiObservatoryError("cannot freeze a baseline with an invalid weight index")
    shard_errors = [
        row.get("shard")
        for row in census.get("shards", [])
        if row.get("parse_error") or row.get("anomalies")
    ]
    if shard_errors:
        raise KimiObservatoryError(
            f"cannot freeze a baseline with safetensors anomalies: {shard_errors[:20]}"
        )
    if plan.get("model_estate_sha256") != scan.get("model_estate_sha256"):
        raise KimiObservatoryError("dissection plan does not bind the supplied model estate")
    receipts = _collect_grid_receipts(grid_root)
    if not receipts:
        raise KimiObservatoryError("grid root contains no tier-bench JSON receipts")
    baseline = {
        "schema": BASELINE_SCHEMA,
        "id": label,
        "created_at": now_utc(),
        "model": {
            "scan_path": str(scan_path.resolve()),
            "scan_sha256": scan["scan_sha256"],
            "model_estate_sha256": scan["model_estate_sha256"],
            "content_bindings_sha256": hash_json(scan.get("content_bindings", [])),
            "tensor_census_path": str(census_path.resolve()),
            "tensor_census_sha256": census.get("census_sha256") or hash_json(census),
            "dissection_plan_path": str(plan_path.resolve()),
            "dissection_plan_sha256": plan["plan_sha256"],
        },
        "grid": {
            "root": str(grid_root.resolve()),
            "receipt_count": len(receipts),
            "receipts": receipts,
            "receipts_sha256": hash_json(receipts),
        },
        "laws": [
            "Every intervention reruns the same frozen task corpus and graders.",
            "A changed model shard, config, tokenizer, runtime, prompt, or grader creates a new baseline.",
            "Community reports may propose tests but cannot alter the frozen baseline retroactively.",
        ],
    }
    baseline["baseline_sha256"] = hash_json(
        {key: value for key, value in baseline.items() if key != "baseline_sha256"}
    )
    return baseline
