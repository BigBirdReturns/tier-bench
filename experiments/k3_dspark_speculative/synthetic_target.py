"""Small deterministic target adapter and drafter for control-path tests.

These stand in for K3 and DSpark ONLY to exercise the speculative-executor
contracts (acceptance 0/1/partial/full, rollback, exceptions, malformed
bundles, hash drift, receipt replay). Nothing here represents K3 numerics and
no result from them may be cited as K3 integration evidence.
"""
from __future__ import annotations

import hashlib
from typing import Any

VOCAB = 16


def _pick(prefix: list[int]) -> int:
    """Deterministic 'target' next token: sha256 of the prefix mod VOCAB."""
    digest = hashlib.sha256(",".join(map(str, prefix)).encode()).digest()
    return digest[0] % VOCAB


class SyntheticTarget:
    """Deterministic target with explicit KDA/MLA/AttnRes-shaped state.

    State objects are small deterministic functions of the prefix so commit
    and rollback have real, checkable consequences on every state component.
    """

    def __init__(self, prefix: list[int]):
        self._state = self._state_for(list(prefix))

    @staticmethod
    def _state_for(prefix: list[int]) -> dict[str, Any]:
        tag = hashlib.sha256(",".join(map(str, prefix)).encode()).hexdigest()
        return {
            "kda": {"recurrent": tag[:16], "conv": tag[16:24]},
            "mla": {"kv_rows": len(prefix), "kv_tag": tag[24:40]},
            "attn_res": tag[40:56],
            "position": len(prefix),
            "prefix": list(prefix),
        }

    def export_state(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in self._state.items()}

    def load_state(self, state: dict[str, Any]) -> None:
        self._state = {k: (list(v) if isinstance(v, list) else v) for k, v in state.items()}

    def block_logits(self, proposed_tokens: list[int]) -> list[list[float]]:
        prefix = list(self._state["prefix"])
        rows = []
        for token in proposed_tokens:
            pick = _pick(prefix)
            rows.append([1.0 if v == pick else 0.0 for v in range(VOCAB)])
            prefix.append(token)  # streamed traversal conditions on the proposal
        return rows

    def advance(self, tokens: list[int]) -> None:
        self._state = self._state_for(list(self._state["prefix"]) + list(tokens))

    def greedy_continuation(self, n: int) -> list[int]:
        """Ground truth: what sequential decoding would produce."""
        prefix = list(self._state["prefix"])
        out = []
        for _ in range(n):
            t = _pick(prefix)
            out.append(t)
            prefix.append(t)
        return out


class ScriptedDrafter:
    """Drafter returning a scripted proposal (for exact acceptance control)."""

    def __init__(self, tokens: list[int], confidence: float = 0.5):
        self.tokens = list(tokens)
        self.confidence = confidence

    def propose(self, aux_bundle: dict[str, Any], prefix: list[int]) -> dict[str, Any]:
        return {
            "tokens": list(self.tokens),
            "scores": [1.0] * len(self.tokens),
            "confidence": self.confidence,
        }


class ExplodingDrafter:
    def propose(self, aux_bundle: dict[str, Any], prefix: list[int]) -> dict[str, Any]:
        raise RuntimeError("drafter exploded")


class ExplodingTarget(SyntheticTarget):
    def block_logits(self, proposed_tokens: list[int]) -> list[list[float]]:
        raise RuntimeError("verifier exploded")


class DriftingTarget(SyntheticTarget):
    """Mutates state during 'pure' verification: must be caught by commit."""

    def block_logits(self, proposed_tokens: list[int]) -> list[list[float]]:
        rows = super().block_logits(proposed_tokens)
        self._state["attn_res"] = "drifted"
        return rows


def make_aux_bundle(layers: list[int]) -> dict[str, Any]:
    return {
        "schema": "octopodes/k3-dspark-tap-capture@1",
        # a synthetic bundle stands in for a SUCCESSFUL target run; admission
        # requires the target-run outcome AND the identity of the run that
        # produced it to be bound
        "target_run_return_code": 0,
        "terminal_status": "ok",
        "run_identity": "synthetic-tap-run-0000",
        "enabled": True,
        "specs": [{"layer": l, "location": "post", "declared_as": f"synthetic tap {l}"} for l in layers],
        "captures": [
            {
                "layer": l,
                "location": "post",
                "declared_as": f"synthetic tap {l}",
                "shape": [1, 4, 8],
                "dtype": "torch.bfloat16",
                "token_axis": 1,
                "batch_axis": 0,
                "token_count": 4,
                "sha256": hashlib.sha256(str(l).encode()).hexdigest(),
            }
            for l in layers
        ],
    }
