"""Optional runtime probes and desktop expert-cache simulations for Kimi K3."""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from contextlib import AbstractContextManager
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .kimi3_common import (
    KimiObservatoryError,
    append_jsonl,
    hash_json,
    now_utc,
    read_jsonl,
    sha256_stream,
)

TRACE_SCHEMA = "tier-bench/kimi3-runtime-trace@1"
ROUTER_REPORT_SCHEMA = "tier-bench/kimi3-router-report@1"
OFFLOAD_REPORT_SCHEMA = "tier-bench/kimi3-expert-offload-simulation@1"


def _tensor_summary(value: Any, *, samples: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "type": type(value).__name__,
    }
    for attribute in ("shape", "dtype", "device"):
        item = getattr(value, attribute, None)
        if item is not None:
            summary[attribute] = str(item)
    if not hasattr(value, "detach") or not hasattr(value, "numel"):
        return summary
    try:
        tensor = value.detach()
        count = int(tensor.numel())
        summary["numel"] = count
        if count <= 0:
            return summary
        flat = tensor.reshape(-1)
        if count > samples:
            step = max(1, count // samples)
            flat = flat[::step][:samples]
        sample = flat.float().cpu()
        summary["sample_count"] = int(sample.numel())
        summary["finite_rate"] = float(sample.isfinite().float().mean().item())
        finite = sample[sample.isfinite()]
        if int(finite.numel()):
            summary.update(
                {
                    "min": float(finite.min().item()),
                    "max": float(finite.max().item()),
                    "mean": float(finite.mean().item()),
                    "abs_mean": float(finite.abs().mean().item()),
                    "rms": float((finite.square().mean().sqrt()).item()),
                }
            )
    except Exception as exc:  # Probe failures must not break inference.
        summary["summary_error"] = f"{type(exc).__name__}: {exc}"
    return summary


def _walk_tensors(value: Any, *, samples: int, limit: int = 8) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stack = [value]
    while stack and len(result) < limit:
        item = stack.pop(0)
        if isinstance(item, dict):
            stack[0:0] = list(item.values())
        elif isinstance(item, (list, tuple)):
            stack[0:0] = list(item)
        else:
            result.append(_tensor_summary(item, samples=samples))
    return result


def _router_experts(output: Any, *, top_k: int, token_limit: int) -> list[list[int]]:
    candidate = output
    if isinstance(candidate, (list, tuple)) and candidate:
        candidate = candidate[0]
    if isinstance(candidate, dict):
        for key in ("router_logits", "logits", "scores", "gate_logits"):
            if key in candidate:
                candidate = candidate[key]
                break
    if not hasattr(candidate, "detach") or not hasattr(candidate, "shape"):
        return []
    try:
        tensor = candidate.detach()
        if len(tensor.shape) < 1 or int(tensor.shape[-1]) < top_k:
            return []
        flattened = tensor.reshape(-1, tensor.shape[-1])[:token_limit]
        indices = flattened.float().topk(top_k, dim=-1).indices.cpu().tolist()
        return [[int(index) for index in row] for row in indices]
    except Exception:
        return []


class ProbeSession(AbstractContextManager["ProbeSession"]):
    """Attach read-only forward hooks without retaining prompts or activations."""

    def __init__(
        self,
        model: Any,
        *,
        trace_path: Path,
        model_revision: str,
        runtime_revision: str,
        task_family: str,
        prompt_id_sha256: str,
        module_patterns: Iterable[str] = (
            r"router|gate",
            r"kda|delta",
            r"attnres|attention_residual",
            r"mla|latent_attention",
            r"expert",
            r"vision|vit",
        ),
        tensor_samples: int = 64,
        router_top_k: int = 16,
        router_token_limit: int = 256,
    ) -> None:
        import re

        self.model = model
        self.trace_path = trace_path
        self.model_revision = model_revision
        self.runtime_revision = runtime_revision
        self.task_family = task_family
        self.prompt_id_sha256 = prompt_id_sha256
        self.patterns = [re.compile(pattern, re.I) for pattern in module_patterns]
        self.tensor_samples = tensor_samples
        self.router_top_k = router_top_k
        self.router_token_limit = router_token_limit
        self.handles: list[Any] = []
        self.sequence = 0

    def __enter__(self) -> "ProbeSession":
        if not hasattr(self.model, "named_modules"):
            raise KimiObservatoryError("probe model must expose named_modules()")
        for name, module in self.model.named_modules():
            if not name or not any(pattern.search(name) for pattern in self.patterns):
                continue
            self.handles.append(module.register_forward_hook(self._hook(name)))
        return self

    def _hook(self, name: str):
        def callback(module: Any, inputs: Any, output: Any) -> None:
            self.sequence += 1
            lowered = name.lower()
            kind = "router" if ("router" in lowered or "gate" in lowered) else "module"
            event = {
                "schema": TRACE_SCHEMA,
                "sequence": self.sequence,
                "created_at": now_utc(),
                "model_revision": self.model_revision,
                "runtime_revision": self.runtime_revision,
                "task_family": self.task_family,
                "prompt_id_sha256": self.prompt_id_sha256,
                "module": name,
                "module_class": type(module).__name__,
                "kind": kind,
                "inputs": _walk_tensors(
                    inputs,
                    samples=self.tensor_samples,
                ),
                "outputs": _walk_tensors(
                    output,
                    samples=self.tensor_samples,
                ),
                "experts": (
                    _router_experts(
                        output,
                        top_k=self.router_top_k,
                        token_limit=self.router_token_limit,
                    )
                    if kind == "router"
                    else []
                ),
                "taint": "runtime_observation",
            }
            event["event_sha256"] = hash_json(
                {key: value for key, value in event.items() if key != "event_sha256"}
            )
            append_jsonl(self.trace_path, event)

        return callback

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        for handle in self.handles:
            try:
                handle.remove()
            except Exception:
                pass
        self.handles.clear()
        return None


def reduce_router_trace(trace_path: Path) -> dict[str, Any]:
    rows = read_jsonl(trace_path)
    if not rows:
        raise KimiObservatoryError("runtime trace is empty")
    revisions = {
        (row.get("model_revision"), row.get("runtime_revision"))
        for row in rows
        if row.get("schema") == TRACE_SCHEMA
    }
    if len(revisions) != 1:
        raise KimiObservatoryError("runtime trace mixes model or runtime revisions")
    model_revision, runtime_revision = next(iter(revisions))
    counts_by_module: dict[str, Counter[int]] = defaultdict(Counter)
    routes_by_module: dict[str, int] = Counter()
    coactivation: dict[str, Counter[str]] = defaultdict(Counter)
    task_families: Counter[str] = Counter()
    event_errors: list[str] = []
    for row in rows:
        if row.get("schema") != TRACE_SCHEMA:
            continue
        expected = hash_json(
            {key: value for key, value in row.items() if key != "event_sha256"}
        )
        if row.get("event_sha256") != expected:
            event_errors.append(str(row.get("sequence")))
            continue
        task_families[str(row.get("task_family"))] += 1
        module = str(row.get("module"))
        experts = row.get("experts")
        if not isinstance(experts, list):
            continue
        for route in experts:
            if not isinstance(route, list):
                continue
            normalized = [int(expert) for expert in route if isinstance(expert, int)]
            if not normalized:
                continue
            routes_by_module[module] += 1
            counts_by_module[module].update(normalized)
            for left_index, left in enumerate(sorted(set(normalized))):
                for right in sorted(set(normalized))[left_index + 1 :]:
                    coactivation[module][f"{left}:{right}"] += 1
    modules: list[dict[str, Any]] = []
    for module in sorted(counts_by_module):
        counts = counts_by_module[module]
        total = sum(counts.values())
        probabilities = [count / total for count in counts.values()] if total else []
        entropy = -sum(p * math.log2(p) for p in probabilities if p > 0)
        maximum_entropy = math.log2(len(counts)) if len(counts) > 1 else 0.0
        modules.append(
            {
                "module": module,
                "routes": routes_by_module[module],
                "expert_observations": total,
                "unique_experts": len(counts),
                "entropy_bits": entropy,
                "normalized_entropy": entropy / maximum_entropy if maximum_entropy else 0.0,
                "top_experts": [
                    {"expert": expert, "count": count, "share": count / total}
                    for expert, count in counts.most_common(64)
                ],
                "top_coactivations": [
                    {"pair": pair, "count": count}
                    for pair, count in coactivation[module].most_common(64)
                ],
            }
        )
    report = {
        "schema": ROUTER_REPORT_SCHEMA,
        "created_at": now_utc(),
        "trace_path": str(trace_path.resolve()),
        "trace_sha256": sha256_stream(trace_path),
        "model_revision": model_revision,
        "runtime_revision": runtime_revision,
        "task_families": dict(task_families),
        "modules": modules,
        "event_errors": event_errors,
        "totals": {
            "events": len(rows),
            "router_modules": len(modules),
            "invalid_events": len(event_errors),
        },
    }
    report["report_sha256"] = hash_json(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def _trace_routes(trace_path: Path) -> list[int]:
    routes: list[int] = []
    for row in read_jsonl(trace_path):
        if row.get("schema") != TRACE_SCHEMA:
            continue
        experts = row.get("experts")
        if not isinstance(experts, list):
            continue
        for route in experts:
            if isinstance(route, list):
                routes.extend(int(expert) for expert in route if isinstance(expert, int))
    return routes


def simulate_expert_cache(
    trace_path: Path,
    *,
    expert_bytes: int,
    gpu_experts: int,
    ram_experts: int,
    pcie_gbps: float,
    nvme_gbps: float,
    prewarm_experts: int = 0,
) -> dict[str, Any]:
    if expert_bytes <= 0 or gpu_experts < 0 or ram_experts < 0:
        raise KimiObservatoryError("expert bytes and cache capacities are invalid")
    if pcie_gbps <= 0 or nvme_gbps <= 0:
        raise KimiObservatoryError("bandwidths must be positive")
    routes = _trace_routes(trace_path)
    if not routes:
        raise KimiObservatoryError("trace contains no expert routes")

    frequency = Counter(routes)
    gpu: OrderedDict[int, None] = OrderedDict()
    ram: OrderedDict[int, None] = OrderedDict()
    for expert, _ in frequency.most_common(min(prewarm_experts, gpu_experts)):
        gpu[expert] = None

    stats = Counter()
    transfer_bytes = Counter()
    for expert in routes:
        if expert in gpu:
            stats["gpu_hits"] += 1
            gpu.move_to_end(expert)
            continue
        if expert in ram:
            stats["ram_hits"] += 1
            transfer_bytes["ram_to_gpu"] += expert_bytes
            ram.move_to_end(expert)
        else:
            stats["nvme_hits"] += 1
            transfer_bytes["nvme_to_ram"] += expert_bytes
            transfer_bytes["ram_to_gpu"] += expert_bytes
            if ram_experts:
                ram[expert] = None
                ram.move_to_end(expert)
                while len(ram) > ram_experts:
                    ram.popitem(last=False)
        if gpu_experts:
            gpu[expert] = None
            gpu.move_to_end(expert)
            while len(gpu) > gpu_experts:
                evicted, _ = gpu.popitem(last=False)
                if ram_experts:
                    ram[evicted] = None
                    ram.move_to_end(evicted)
                    while len(ram) > ram_experts:
                        ram.popitem(last=False)

    pcie_seconds = transfer_bytes["ram_to_gpu"] / (pcie_gbps * 1e9)
    nvme_seconds = transfer_bytes["nvme_to_ram"] / (nvme_gbps * 1e9)
    total = len(routes)
    result = {
        "schema": OFFLOAD_REPORT_SCHEMA,
        "created_at": now_utc(),
        "trace_path": str(trace_path.resolve()),
        "trace_sha256": sha256_stream(trace_path),
        "inputs": {
            "expert_bytes": expert_bytes,
            "gpu_experts": gpu_experts,
            "ram_experts": ram_experts,
            "pcie_gbps": pcie_gbps,
            "nvme_gbps": nvme_gbps,
            "prewarm_experts": prewarm_experts,
        },
        "routes": total,
        "unique_experts": len(frequency),
        "hits": {
            "gpu": stats["gpu_hits"],
            "ram": stats["ram_hits"],
            "nvme": stats["nvme_hits"],
        },
        "hit_rates": {
            "gpu": stats["gpu_hits"] / total,
            "ram": stats["ram_hits"] / total,
            "nvme": stats["nvme_hits"] / total,
        },
        "transfer_bytes": dict(transfer_bytes),
        "estimated_transfer_seconds": {
            "pcie": pcie_seconds,
            "nvme": nvme_seconds,
            "total": pcie_seconds + nvme_seconds,
        },
        "top_experts": [
            {"expert": expert, "count": count, "share": count / total}
            for expert, count in frequency.most_common(128)
        ],
        "limitations": [
            "This is a trace replay, not an inference benchmark.",
            "It assumes fixed expert byte size and does not include kernel, router, or synchronization cost.",
            "A useful result must be compared with measured local PCIe, RAM, and NVMe bandwidth.",
        ],
    }
    result["report_sha256"] = hash_json(
        {key: value for key, value in result.items() if key != "report_sha256"}
    )
    return result
