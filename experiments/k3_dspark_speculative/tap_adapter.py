"""Bounded instrumentation adapter for the cached K3 runner.

Captures declared residual-stream taps during a target traversal WITHOUT changing
the target result. DISABLED BY DEFAULT: importing this module changes nothing.
Only an explicit ``TapSession.install()`` wraps the runner module's
``run_dense_layer`` / ``run_moe_layer`` function objects, and ``uninstall()``
restores the exact original function objects.

The tap CONTRACT (zero/one-based layer numbering, pre- vs post-layer, pre- vs
post-normalization, dtype, packing) is NOT hard-coded here. It is bound at call
time by ``TapSpec`` values; resolving what Kimi-K3-DSpark actually expects for
its declared taps (2, 23, 47, 71, 89) is the job of the interface-resolution
step against the checkpoint's own configuration and implementation. Do not
guess it from the layer numbers alone.

Capture semantics against the cached runner's loop
(``run_cached_continuation.run_continuation``):
  - location "pre"  = the ``hidden_states`` argument entering the layer
                      function = residual stream INPUT to that layer, before any
                      of the layer's normalization (the runner normalizes inside
                      the layer implementation).
  - location "post" = the layer function's ``output`` = residual stream after
                      the layer block.
Every captured tensor is hashed (sha256 of its raw bytes after `.detach().cpu()
.contiguous()`, reinterpreted to a same-width integer dtype) together with its
shape, dtype, layer coordinate, token coordinate, and capture location. Capture
clones nothing into the compute path and mutates nothing: tensors are read-only
observed after the layer function returns.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


_INT_VIEW = {
    "torch.bfloat16": "int16",
    "torch.float16": "int16",
    "torch.float32": "int32",
    "torch.float64": "int64",
}


def tensor_bytes(tensor: Any) -> bytes:
    """Raw little-endian bytes of a torch tensor, dtype-faithful (bf16 safe)."""
    import torch

    t = tensor.detach().to("cpu").contiguous()
    view_name = _INT_VIEW.get(str(t.dtype))
    if view_name is not None:
        t = t.view(getattr(torch, view_name))
    return t.numpy().tobytes()


def tensor_sha256(tensor: Any) -> str:
    return hashlib.sha256(tensor_bytes(tensor)).hexdigest()


@dataclass(frozen=True)
class TapSpec:
    """One declared tap. ``layer`` uses the RUNNER's coordinate system
    (run_cached_continuation layer index: 0 = dense layer, 1..92 = MoE
    decoder layers). Mapping from the drafter's declared tap numbers to this
    coordinate system is external and must be recorded in the capture receipt
    via ``declared_as``.

    Locations:
      "pre"     - residual-stream wire entering the layer (the AttnRes running
                  prefix; vLLM's default prefix_only aux convention).
      "post"    - wire leaving the layer.
      "mixture" - the pre-norm AttnRes mixture over bank + prefix computed with
                  the consumer layer's res weights (vLLM's
                  VLLM_KIMI_K3_AUX_ATTN_RES_STREAM=1 convention, which the K3
                  capture docstring names as the DFlash training target).
                  Requires a ``mixture_fn`` on the session; the adapter never
                  computes it itself.
    """

    layer: int
    location: str  # "pre" | "post" | "mixture"
    declared_as: str = ""  # e.g. "dspark tap 23 (interpretation: ...)"

    def __post_init__(self) -> None:
        if self.location not in ("pre", "post", "mixture"):
            raise ValueError(f"unknown tap location {self.location!r}")
        if not 0 <= self.layer <= 92:
            raise ValueError(f"tap layer {self.layer} outside runner range 0..92")


@dataclass
class TapSession:
    """Wraps a runner module's layer functions to observe declared taps.

    Disabled by default in two independent senses: a session that is never
    ``install()``-ed touches nothing, and a session installed with
    ``enabled=False`` observes nothing while still proving the wrap/unwrap
    path is inert.
    """

    specs: tuple[TapSpec, ...]
    enabled: bool = True
    mixture_fn: Any = None  # (layer:int, prefix:Tensor, call_kwargs:dict) -> Tensor
    captures: list[dict[str, Any]] = field(default_factory=list)
    _module: Any = None
    _originals: dict[str, Any] = field(default_factory=dict)

    def _record(self, layer: int, location: str, spec: TapSpec, tensor: Any) -> None:
        self.captures.append(
            {
                "layer": layer,
                "location": location,
                "declared_as": spec.declared_as,
                "shape": list(tensor.shape),
                "dtype": str(tensor.dtype),
                "token_axis": 1,
                "batch_axis": 0,
                "token_count": int(tensor.shape[1]) if tensor.dim() >= 2 else None,
                "sha256": tensor_sha256(tensor),
            }
        )

    def _observe(self, layer: int, location: str, tensor: Any) -> None:
        if not self.enabled:
            return
        for spec in self.specs:
            if spec.layer == layer and spec.location == location:
                self._record(layer, location, spec, tensor)

    def _observe_mixture(self, layer: int, prefix: Any, call_kwargs: dict) -> None:
        if not self.enabled:
            return
        for spec in self.specs:
            if spec.layer == layer and spec.location == "mixture":
                # computed on detached clones; the live tensors are never touched
                value = self.mixture_fn(layer, prefix, call_kwargs)
                self._record(layer, "mixture", spec, value)

    def install(self, module: Any) -> "TapSession":
        """Wrap ``run_dense_layer`` and ``run_moe_layer`` on ``module``.

        The wrappers pass every argument through unchanged and return the
        wrapped function's result object identity-unchanged; they only observe.
        """
        if self._module is not None:
            raise RuntimeError("tap session already installed")
        if any(s.location == "mixture" for s in self.specs) and self.mixture_fn is None:
            raise RuntimeError("mixture taps declared but no mixture_fn provided")
        self._module = module
        session = self

        original_dense = module.run_dense_layer
        original_moe = module.run_moe_layer
        self._originals = {"run_dense_layer": original_dense, "run_moe_layer": original_moe}

        def wrapped_dense(*args: Any, **kwargs: Any) -> Any:
            hidden = kwargs.get("hidden_states", args[0] if args else None)
            session._observe(0, "pre", hidden)
            result = original_dense(*args, **kwargs)
            session._observe(0, "post", result[0])
            return result

        def wrapped_moe(*args: Any, **kwargs: Any) -> Any:
            layer = kwargs.get("layer")
            hidden = kwargs.get("hidden_states")
            if layer is not None and hidden is not None:
                session._observe(int(layer), "pre", hidden)
                session._observe_mixture(int(layer), hidden, kwargs)
            result = original_moe(*args, **kwargs)
            if layer is not None:
                session._observe(int(layer), "post", result[0])
            return result

        module.run_dense_layer = wrapped_dense
        module.run_moe_layer = wrapped_moe
        return self

    def uninstall(self) -> None:
        if self._module is None:
            return
        for name, fn in self._originals.items():
            setattr(self._module, name, fn)
        self._module = None
        self._originals = {}

    def __enter__(self) -> "TapSession":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.uninstall()

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "octopodes/k3-dspark-tap-capture@1",
            "enabled": self.enabled,
            "specs": [
                {"layer": s.layer, "location": s.location, "declared_as": s.declared_as}
                for s in self.specs
            ],
            "captures": list(self.captures),
        }
