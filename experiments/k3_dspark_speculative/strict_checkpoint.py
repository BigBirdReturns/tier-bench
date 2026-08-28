"""Execution-bound resumable checkpoints for the strict block verifier.

A kill-resumable traversal checkpoint is only valid inside the exact
execution that created it. Every checkpoint carries and verifies: schema,
runner source digest, verification mode, model identity, parent cached-state
identity, sequential-baseline root, prefix identity, proposal identity,
completed-layer index, inter-layer carrier tensor roots, saved per-position
state roots, output-root identity, creation timestamp, and an aggregate root
over the bindings. Resume requires exact equality for every binding; on any
mismatch the checkpoint is quarantined (never deleted, never resumed) and the
run must start from a fresh output root.

Torch-only module (no transformers / runtime-slice imports) so the hostile
binding witnesses run anywhere the contracts run.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from . import contracts as C

CHECKPOINT_SCHEMA = "octopodes/k3-strict-traversal-checkpoint@2"


def tensor_root(t: Any) -> str:
    enc, _ = C._encode_state(t, "t")
    return hashlib.sha256(enc).hexdigest()


def tokens_sha256(tokens: list[int]) -> str:
    return hashlib.sha256(
        ",".join(str(int(t)) for t in tokens).encode("ascii")).hexdigest()


def make_bindings(
    *,
    runner_sha256: str,
    mode: str,
    model_index_sha256: str,
    parent_checkpoint_sha256: str,
    baseline_root_sha256: str | None,
    prefix_length: int,
    prefix_sha256: str,
    proposal_tokens: list[int],
    output_root_id: str,
) -> dict[str, Any]:
    return {
        "schema": CHECKPOINT_SCHEMA,
        "runner_sha256": runner_sha256,
        "mode": mode,
        "model_index_sha256": model_index_sha256,
        "parent_checkpoint_sha256": parent_checkpoint_sha256,
        "baseline_root_sha256": baseline_root_sha256,
        "prefix_length": int(prefix_length),
        "prefix_sha256": prefix_sha256,
        "proposal_length": len(proposal_tokens),
        "proposal_sha256": tokens_sha256(proposal_tokens),
        "output_root_id": output_root_id,
    }


BINDING_FIELDS = [
    "schema", "runner_sha256", "mode", "model_index_sha256",
    "parent_checkpoint_sha256", "baseline_root_sha256", "prefix_length",
    "prefix_sha256", "proposal_length", "proposal_sha256", "output_root_id",
]


def _aggregate_root(payload: dict[str, Any]) -> str:
    body = {
        "bindings": {k: payload["bindings"][k] for k in BINDING_FIELDS},
        "layer_done": payload["layer_done"],
        "carrier_roots": payload["carrier_roots"],
        "position_state_roots": payload["position_state_roots"],
        "created_at": payload["created_at"],
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def make_checkpoint_payload(
    *,
    bindings: dict[str, Any],
    layer_done: int,
    hidden: list[Any],
    bank: list[Any],
    telemetry: dict[str, Any],
    position_state_roots: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "bindings": dict(bindings),
        "layer_done": int(layer_done),
        "carrier_roots": {
            "hidden": [tensor_root(t) for t in hidden],
            "bank": [tensor_root(t) for t in bank],
        },
        "position_state_roots": dict(sorted(position_state_roots.items())),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hidden": hidden,
        "bank": bank,
        "telemetry": telemetry,
    }
    payload["aggregate_root_sha256"] = _aggregate_root(payload)
    return payload


class IncompatibleCheckpoint(Exception):
    """First mismatched binding; the checkpoint must be quarantined."""

    def __init__(self, binding: str, expected: Any, found: Any):
        self.binding = binding
        self.expected = expected
        self.found = found
        super().__init__(
            f"INCOMPATIBLE_CHECKPOINT: first mismatched binding {binding!r}: "
            f"checkpoint has {found!r}, this execution requires {expected!r}")


def validate_resume(payload: dict[str, Any], expected_bindings: dict[str, Any]) -> None:
    """Exact equality for every binding, carrier integrity, and the aggregate
    root. Raises IncompatibleCheckpoint naming the FIRST mismatch."""
    saved = payload.get("bindings")
    if not isinstance(saved, dict):
        raise IncompatibleCheckpoint("bindings", "binding object", type(saved).__name__)
    for field in BINDING_FIELDS:
        if saved.get(field) != expected_bindings.get(field):
            raise IncompatibleCheckpoint(field, expected_bindings.get(field),
                                         saved.get(field))
    layer_done = payload.get("layer_done")
    if not isinstance(layer_done, int) or layer_done < 0:
        raise IncompatibleCheckpoint("layer_done", "non-negative int", layer_done)
    recomputed_hidden = [tensor_root(t) for t in payload["hidden"]]
    if recomputed_hidden != payload["carrier_roots"]["hidden"]:
        raise IncompatibleCheckpoint(
            "carrier_roots.hidden", payload["carrier_roots"]["hidden"],
            recomputed_hidden)
    recomputed_bank = [tensor_root(t) for t in payload["bank"]]
    if recomputed_bank != payload["carrier_roots"]["bank"]:
        raise IncompatibleCheckpoint(
            "carrier_roots.bank", payload["carrier_roots"]["bank"], recomputed_bank)
    root = _aggregate_root(payload)
    if root != payload.get("aggregate_root_sha256"):
        raise IncompatibleCheckpoint(
            "aggregate_root_sha256", payload.get("aggregate_root_sha256"), root)
