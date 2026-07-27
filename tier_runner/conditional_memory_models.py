"""Small decoder models used by the Conditional Memory Lab.

PyTorch is intentionally optional at package-install time. The zero-model control
plane never imports this module; physical trial commands import it only after the
GPU UUID has been resolved and ``CUDA_VISIBLE_DEVICES`` has been set.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import torch
from torch import nn
import torch.nn.functional as F

from .conditional_memory_common import MemoryLabError


_DTYPE_MAP = {
    "fp32": torch.float32,
    "fp16": torch.float16,
    "bf16": torch.bfloat16,
}


class RMSNorm(nn.Module):
    def __init__(self, width: int, eps: float = 1e-6) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(width))
        self.eps = eps

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        normalized = value.float() * torch.rsqrt(
            value.float().pow(2).mean(-1, keepdim=True) + self.eps
        )
        return normalized.to(value.dtype) * self.weight


class CausalSelfAttention(nn.Module):
    def __init__(self, width: int, heads: int, dropout: float, bias: bool) -> None:
        super().__init__()
        self.width = width
        self.heads = heads
        self.head_dim = width // heads
        self.dropout = dropout
        self.qkv = nn.Linear(width, 3 * width, bias=bias)
        self.out = nn.Linear(width, width, bias=bias)

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        batch, sequence, width = value.shape
        q, k, v = self.qkv(value).chunk(3, dim=-1)
        q = q.view(batch, sequence, self.heads, self.head_dim).transpose(1, 2)
        k = k.view(batch, sequence, self.heads, self.head_dim).transpose(1, 2)
        v = v.view(batch, sequence, self.heads, self.head_dim).transpose(1, 2)
        attended = F.scaled_dot_product_attention(
            q,
            k,
            v,
            dropout_p=self.dropout if self.training else 0.0,
            is_causal=True,
        )
        attended = attended.transpose(1, 2).contiguous().view(batch, sequence, width)
        return self.out(attended)


class TransformerBlock(nn.Module):
    def __init__(self, width: int, heads: int, hidden: int, dropout: float, bias: bool) -> None:
        super().__init__()
        self.attn_norm = RMSNorm(width)
        self.attn = CausalSelfAttention(width, heads, dropout, bias)
        self.ffn_norm = RMSNorm(width)
        self.ffn_up = nn.Linear(width, hidden * 2, bias=bias)
        self.ffn_down = nn.Linear(hidden, width, bias=bias)
        self.dropout = nn.Dropout(dropout)

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        value = value + self.dropout(self.attn(self.attn_norm(value)))
        up, gate = self.ffn_up(self.ffn_norm(value)).chunk(2, dim=-1)
        return value + self.dropout(self.ffn_down(F.silu(gate) * up))


class ConditionalTable(nn.Module):
    """A sparse-gradient table whose rows may remain outside accelerator memory."""

    def __init__(
        self,
        rows: int,
        width: int,
        *,
        placement: str,
        storage_dtype: str,
        runtime_dtype: str,
        artifact_path: str | None = None,
    ) -> None:
        super().__init__()
        if storage_dtype not in _DTYPE_MAP:
            raise MemoryLabError(
                f"physical training supports fp32/fp16/bf16 table storage, not {storage_dtype}"
            )
        if runtime_dtype not in _DTYPE_MAP:
            raise MemoryLabError(
                f"physical lookup supports fp32/fp16/bf16 transfer rows, not {runtime_dtype}"
            )
        self.rows = rows
        self.width = width
        self.placement = placement
        self.storage_dtype_name = storage_dtype
        self.runtime_dtype_name = runtime_dtype
        self.artifact_path = artifact_path
        self.storage_dtype = _DTYPE_MAP[storage_dtype]
        self.runtime_dtype = _DTYPE_MAP[runtime_dtype]
        if placement == "mmap":
            if not artifact_path:
                raise MemoryLabError("mmap placement requires memory.artifact_path")
            path = Path(artifact_path).expanduser().resolve()
            if not path.exists():
                raise MemoryLabError(f"mmap memory artifact does not exist: {path}")
            expected = rows * width
            expected_bytes = expected * torch.empty((), dtype=self.storage_dtype).element_size()
            if path.stat().st_size != expected_bytes:
                raise MemoryLabError(
                    "mmap memory artifact has "
                    f"{path.stat().st_size} bytes; expected {expected_bytes}"
                )
            initial = torch.from_file(
                str(path), shared=False, size=expected, dtype=self.storage_dtype
            ).view(rows, width)
            self.weight = nn.Parameter(initial, requires_grad=False)
        else:
            initial = torch.empty(rows, width, dtype=self.storage_dtype)
            nn.init.normal_(initial, mean=0.0, std=0.02)
            self.weight = nn.Parameter(initial)
        self._target_device = torch.device("cpu")

    @property
    def storage_row_bytes(self) -> int:
        return self.width * torch.empty((), dtype=self.storage_dtype).element_size()

    @property
    def transfer_row_bytes(self) -> int:
        return self.width * torch.empty((), dtype=self.runtime_dtype).element_size()

    def configure(self, target: torch.device) -> None:
        self._target_device = target
        if self.placement == "mmap":
            if self.weight.device.type != "cpu":
                raise MemoryLabError("memory-mapped table unexpectedly left CPU address space")
            return
        if self.placement == "vram":
            self.weight.data = self.weight.data.to(target)
            return
        if self.placement == "host_ram" or target.type == "cpu":
            self.weight.data = self.weight.data.to("cpu")
            return
        if self.placement == "pinned_ram":
            self.weight.data = self.weight.data.to("cpu").pin_memory()
            return
        raise MemoryLabError(f"unsupported table placement {self.placement}")

    def lookup(
        self,
        keys: torch.Tensor,
        target: torch.device,
        *,
        compute_dtype: torch.dtype,
    ) -> torch.Tensor:
        """Select rows before transfer and retain sparse gradients during training."""
        if self.weight.device == keys.device:
            rows = F.embedding(keys, self.weight, sparse=self.weight.requires_grad)
        else:
            cpu_keys = keys.detach().to("cpu", non_blocking=False)
            rows = F.embedding(cpu_keys, self.weight, sparse=self.weight.requires_grad)
        rows = rows.to(self.runtime_dtype)
        if rows.device != target:
            if self.placement == "pinned_ram" and target.type == "cuda" and not rows.is_pinned():
                rows = rows.pin_memory()
            rows = rows.to(target, non_blocking=self.placement == "pinned_ram")
        return rows.to(compute_dtype)

    def export_raw(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tensor = self.weight.detach().to("cpu").contiguous()
        path.write_bytes(tensor.view(torch.uint8).numpy().tobytes())


class ConditionalMemoryLM(nn.Module):
    def __init__(self, trial: dict[str, Any]) -> None:
        super().__init__()
        arm = trial["arm"]
        model = arm["model"]
        memory = arm["memory"]
        dataset = trial["dataset"]
        self.architecture = arm["architecture"]
        self.vocab_size = dataset["vocab_size"]
        self.max_sequence_length = dataset["sequence_length"]
        self.width = model["d_model"]
        self.layers = model["layers"]
        self.memory_dim = memory["memory_dim"]
        self.injection_layers = set(memory["injection_layers"])
        self.ngram_order = memory["ngram_order"]
        self.placement = memory["placement"]
        self.token_embedding = nn.Embedding(self.vocab_size, self.width)
        self.position_embedding = nn.Embedding(self.max_sequence_length, self.width)
        self.blocks = nn.ModuleList(
            TransformerBlock(
                self.width,
                model["heads"],
                model["ffn_hidden"],
                model["dropout"],
                model["bias"],
            )
            for _ in range(self.layers)
        )
        self.final_norm = RMSNorm(self.width)
        self.output = nn.Linear(self.width, self.vocab_size, bias=False)
        if model["tie_embeddings"]:
            self.output.weight = self.token_embedding.weight
        self.memory_table: ConditionalTable | None = None
        self.context_projection: nn.Linear | None = None
        self.fat_projection: nn.Linear | None = None
        self.memory_gates = nn.ModuleList()
        self.memory_outputs = nn.ModuleList()

        table_kwargs = {
            "placement": memory["placement"],
            "storage_dtype": memory["storage_dtype"],
            "runtime_dtype": memory["runtime_dtype"],
            "artifact_path": memory["artifact_path"],
        }
        if self.architecture == "fat_embedding":
            table_width = self.layers * self.memory_dim
            self.memory_table = ConditionalTable(memory["table_rows"], table_width, **table_kwargs)
            self.fat_projection = nn.Linear(table_width, self.width, bias=False)
        elif self.architecture in {"ple", "ple_no_table"}:
            table_width = self.layers * self.memory_dim
            self.context_projection = nn.Linear(self.width, table_width, bias=False)
            if self.architecture == "ple":
                self.memory_table = ConditionalTable(
                    memory["table_rows"], table_width, **table_kwargs
                )
            for _ in range(self.layers):
                self.memory_gates.append(nn.Linear(self.width, self.memory_dim, bias=False))
                output = nn.Linear(self.memory_dim, self.width, bias=False)
                nn.init.zeros_(output.weight)
                self.memory_outputs.append(output)
        elif self.architecture == "engram_lite":
            self.memory_table = ConditionalTable(
                memory["table_rows"], self.memory_dim, **table_kwargs
            )
            for _ in range(self.layers):
                self.memory_gates.append(nn.Linear(self.width, self.memory_dim, bias=False))
                output = nn.Linear(self.memory_dim, self.width, bias=False)
                nn.init.zeros_(output.weight)
                self.memory_outputs.append(output)
        elif self.architecture not in {"dense", "big_dense"}:
            raise MemoryLabError(f"unsupported architecture {self.architecture}")

        self.apply(self._initialize)
        for output in self.memory_outputs:
            nn.init.zeros_(output.weight)

    @staticmethod
    def _initialize(module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def configure_device(self, target: torch.device) -> None:
        """Move the active core without ever staging a host table through VRAM."""
        table = self.memory_table
        if table is not None and table.placement != "vram" and target.type == "cuda":
            weight = table.weight
            table._parameters["weight"] = None
            self.to(target)
            table._parameters["weight"] = weight
            table.configure(target)
            return
        self.to(target)
        if table is not None:
            table.configure(target)

    def sparse_parameters(self) -> list[nn.Parameter]:
        if self.memory_table is None or not self.memory_table.weight.requires_grad:
            return []
        return [self.memory_table.weight]

    def dense_parameters(self) -> list[nn.Parameter]:
        sparse_ids = {id(parameter) for parameter in self.sparse_parameters()}
        return [
            parameter
            for parameter in self.parameters()
            if parameter.requires_grad and id(parameter) not in sparse_ids
        ]

    def _ngram_keys(self, tokens: torch.Tensor, rows: int) -> torch.Tensor:
        keys = torch.zeros_like(tokens, dtype=torch.long)
        for offset in range(self.ngram_order):
            if offset == 0:
                shifted = tokens
            else:
                pad = torch.zeros(
                    tokens.shape[0], offset, device=tokens.device, dtype=tokens.dtype
                )
                shifted = torch.cat([pad, tokens[:, :-offset]], dim=1)
            keys = (keys * 1_000_003 + shifted.long() + 97 * (offset + 1)) % rows
        return keys

    def _memory_values(
        self, tokens: torch.Tensor, base: torch.Tensor, target: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None]:
        if self.architecture == "fat_embedding":
            assert self.memory_table is not None and self.fat_projection is not None
            fat = self.memory_table.lookup(tokens, target, compute_dtype=base.dtype)
            return self.fat_projection(fat), None
        if self.architecture in {"ple", "ple_no_table"}:
            assert self.context_projection is not None
            contextual = self.context_projection(base).view(
                *tokens.shape, self.layers, self.memory_dim
            )
            if self.memory_table is None:
                return None, contextual
            table = self.memory_table.lookup(
                tokens, target, compute_dtype=contextual.dtype
            ).view(*tokens.shape, self.layers, self.memory_dim)
            combined = (contextual + math.sqrt(self.memory_dim) * table) / math.sqrt(2.0)
            return None, combined
        if self.architecture == "engram_lite":
            assert self.memory_table is not None
            keys = self._ngram_keys(tokens, self.memory_table.rows)
            return None, self.memory_table.lookup(keys, target, compute_dtype=base.dtype)
        return None, None

    def forward(
        self,
        tokens: torch.Tensor,
        targets: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        if tokens.ndim != 2:
            raise MemoryLabError("tokens must have shape [batch, sequence]")
        if tokens.shape[1] > self.max_sequence_length:
            raise MemoryLabError("sequence exceeds configured maximum")
        target_device = tokens.device
        positions = torch.arange(tokens.shape[1], device=target_device)
        base = self.token_embedding(tokens)
        value = base + self.position_embedding(positions)[None, :, :]
        fat, layer_memory = self._memory_values(tokens, base, target_device)
        if fat is not None:
            value = value + fat
        for layer_index, block in enumerate(self.blocks):
            value = block(value)
            if layer_index in self.injection_layers and layer_memory is not None:
                memory_slice = (
                    layer_memory[:, :, layer_index, :]
                    if self.architecture in {"ple", "ple_no_table"}
                    else layer_memory
                )
                gate = F.gelu(self.memory_gates[layer_index](value))
                value = value + self.memory_outputs[layer_index](gate * memory_slice)
        logits = self.output(self.final_norm(value))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.reshape(-1, self.vocab_size), targets.reshape(-1))
        return logits, loss

    def topology_ledger(self, example_tokens: torch.Tensor | None = None) -> dict[str, Any]:
        unique_parameters = {id(parameter): parameter for parameter in self.parameters()}
        stored = sum(parameter.numel() for parameter in unique_parameters.values())
        stored_bytes = sum(
            parameter.numel() * parameter.element_size()
            for parameter in unique_parameters.values()
        )
        memory_parameters = self.memory_table.weight.numel() if self.memory_table is not None else 0
        memory_bytes = (
            self.memory_table.weight.numel() * self.memory_table.weight.element_size()
            if self.memory_table is not None
            else 0
        )
        parameter_bytes_by_device: dict[str, int] = {}
        for parameter in unique_parameters.values():
            device_name = str(parameter.device)
            parameter_bytes_by_device[device_name] = (
                parameter_bytes_by_device.get(device_name, 0)
                + parameter.numel() * parameter.element_size()
            )
        embedding_parameters = self.token_embedding.weight.numel()
        position_parameters = self.position_embedding.weight.numel()
        row_width = self.memory_table.width if self.memory_table is not None else 0
        output_parameters = self.output.weight.numel()
        access: dict[str, Any] = {
            "conditional_memory": {
                "declared_placement": self.placement if self.memory_table is not None else None,
                "actual_device": (
                    str(self.memory_table.weight.device)
                    if self.memory_table is not None
                    else None
                ),
                "rows": self.memory_table.rows if self.memory_table is not None else 0,
                "row_width": row_width,
                "storage_dtype": (
                    self.memory_table.storage_dtype_name if self.memory_table is not None else None
                ),
                "runtime_dtype": (
                    self.memory_table.runtime_dtype_name if self.memory_table is not None else None
                ),
                "storage_row_bytes": (
                    self.memory_table.storage_row_bytes if self.memory_table is not None else 0
                ),
                "transfer_row_bytes": (
                    self.memory_table.transfer_row_bytes if self.memory_table is not None else 0
                ),
                "logical_values_per_token": (
                    0 if self.architecture == "ple_no_table" else row_width
                ),
                "gradient_layout": (
                    "sparse"
                    if self.memory_table is not None
                    and self.memory_table.weight.requires_grad
                    else None
                ),
            },
            "token_embedding": {
                "rows": self.vocab_size,
                "row_width": self.width,
                "logical_values_per_token": self.width,
            },
            "position_embedding": {"logical_values_per_token": self.width},
            "output_head": {
                "rows_scanned_per_token": self.vocab_size,
                "row_width": self.width,
                "logical_values_scanned_per_token": output_parameters,
            },
        }
        if example_tokens is not None and self.memory_table is not None:
            keys = (
                self._ngram_keys(example_tokens, self.memory_table.rows)
                if self.architecture == "engram_lite"
                else example_tokens
            )
            access["conditional_memory"].update(
                {
                    "rows_requested_in_example": int(keys.numel()),
                    "unique_rows_in_example": int(torch.unique(keys.detach().cpu()).numel()),
                    "storage_bytes_requested_in_example": int(
                        keys.numel() * self.memory_table.storage_row_bytes
                    ),
                    "transfer_bytes_requested_in_example": int(
                        keys.numel() * self.memory_table.transfer_row_bytes
                    ),
                }
            )
        return {
            "stored_parameters": stored,
            "stored_bytes": stored_bytes,
            "reachable_parameters_upper_bound": stored,
            "reachability_basis": (
                "all rows addressable by token id"
                if self.architecture in {"ple", "fat_embedding"}
                else "configured upper bound; hashed key reachability is workload dependent"
                if self.architecture == "engram_lite"
                else "all dense parameters reachable"
            ),
            "conditional_memory_parameters": memory_parameters,
            "conditional_memory_bytes": memory_bytes,
            "parameter_bytes_by_device": dict(sorted(parameter_bytes_by_device.items())),
            "mapped_parameter_bytes": (
                memory_bytes
                if self.memory_table is not None and self.memory_table.placement == "mmap"
                else 0
            ),
            "active_core_and_decoder_parameters": stored - memory_parameters,
            "embedding_parameters": embedding_parameters,
            "position_parameters": position_parameters,
            "output_head_parameters": output_parameters,
            "access": access,
        }
