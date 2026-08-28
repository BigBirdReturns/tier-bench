"""Speculative-execution contracts for the K3 <-> DSpark lane.

Every interface the morning campaign needs, exercised tonight only against
synthetic tensors and a small deterministic target adapter. NO K3 integration
is claimed by these tests; K3 remains the sole token adjudicator when the real
adapter is bound.

Design constraints carried from the estate:
  - verify_proposed_block's final K3 implementation must permit ONE streamed
    layer traversal over the whole proposed block (all proposed positions
    advanced together, one weight sweep per layer) rather than N independent
    full sweeps. The TargetAdapter protocol therefore takes the whole block at
    once and returns per-position logits.
  - A poor proposal must never affect correctness: acceptance is decided only
    by the target's own greedy picks; rollback restores the exact
    pre-verification snapshot.
  - State custody is by hash: KDA / MLA / AttnRes / position / prefix are
    hashed before and after, and commit/rollback are verified against those
    hashes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

MAX_BLOCK = 7
STATE_KEYS = ("kda", "mla", "attn_res", "position", "prefix")


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr).encode("utf-8")


def state_hash(state: dict[str, Any]) -> str:
    missing = [k for k in STATE_KEYS if k not in state]
    if missing:
        raise ValueError(f"target state missing keys: {missing}")
    return hashlib.sha256(_canon({k: state[k] for k in STATE_KEYS})).hexdigest()


class TargetAdapter(Protocol):
    """The target model surface the speculative executor drives.

    The real K3 binding implements this over the cached runner (KDA/MLA/AttnRes
    continuation state); ``SyntheticTarget`` implements it deterministically
    for control-path tests.
    """

    def export_state(self) -> dict[str, Any]: ...
    def load_state(self, state: dict[str, Any]) -> None: ...
    def block_logits(self, proposed_tokens: list[int]) -> list[list[float]]:
        """One streamed traversal over the proposed block: logits for every
        proposed position, conditioned on the accepted prefix plus the
        preceding proposed tokens. PURE: must not mutate exported state."""
        ...
    def advance(self, tokens: list[int]) -> None:
        """Advance every state object (KDA/MLA/AttnRes/position/prefix) through
        exactly these positions."""
        ...


class Drafter(Protocol):
    def propose(self, aux_bundle: dict[str, Any], prefix: list[int]) -> dict[str, Any]: ...


@dataclass
class SpecStepError(Exception):
    stage: str
    detail: str

    def __str__(self) -> str:
        return f"{self.stage}: {self.detail}"


def validate_aux_bundle(bundle: dict[str, Any], expected_layers: list[int]) -> None:
    """Reject malformed hidden-state bundles before they reach a drafter."""
    if bundle.get("schema") != "octopodes/k3-dspark-tap-capture@1":
        raise SpecStepError("aux_bundle", f"unknown schema {bundle.get('schema')!r}")
    captures = bundle.get("captures")
    if not isinstance(captures, list) or not captures:
        raise SpecStepError("aux_bundle", "no captures present")
    got_layers = [c.get("layer") for c in captures]
    if got_layers != expected_layers:
        raise SpecStepError(
            "aux_bundle",
            f"layer identity mismatch: expected {expected_layers}, got {got_layers}",
        )
    for c in captures:
        for key in ("shape", "dtype", "sha256", "location"):
            if key not in c:
                raise SpecStepError("aux_bundle", f"capture missing {key}")


def capture_target_aux_hidden(
    tap_session_receipt: dict[str, Any], expected_layers: list[int]
) -> dict[str, Any]:
    """Adopt a TapSession receipt as the drafter's auxiliary bundle."""
    validate_aux_bundle(tap_session_receipt, expected_layers)
    return tap_session_receipt


def draft_block(
    drafter: Drafter, aux_bundle: dict[str, Any], prefix: list[int], expected_layers: list[int]
) -> dict[str, Any]:
    validate_aux_bundle(aux_bundle, expected_layers)
    proposal = drafter.propose(aux_bundle, list(prefix))
    tokens = proposal.get("tokens", [])
    if not 1 <= len(tokens) <= MAX_BLOCK:
        raise SpecStepError("draft", f"proposal length {len(tokens)} outside 1..{MAX_BLOCK}")
    return {
        "tokens": [int(t) for t in tokens],
        "scores": [float(s) for s in proposal.get("scores", [0.0] * len(tokens))],
        "confidence": float(proposal.get("confidence", 0.0)),
    }


def snapshot_target_state(target: TargetAdapter) -> dict[str, Any]:
    state = copy.deepcopy(target.export_state())
    return {"state": state, "hash": state_hash(state)}


def verify_proposed_block(
    target: TargetAdapter, proposed_tokens: list[int]
) -> dict[str, Any]:
    if not 1 <= len(proposed_tokens) <= MAX_BLOCK:
        raise SpecStepError("verify", f"block length {len(proposed_tokens)} outside 1..{MAX_BLOCK}")
    logits = target.block_logits(list(proposed_tokens))
    if len(logits) != len(proposed_tokens):
        raise SpecStepError("verify", "target returned wrong number of positions")
    accepted = 0
    decisions = []
    for position, (token, row) in enumerate(zip(proposed_tokens, logits)):
        target_pick = max(range(len(row)), key=lambda i: (row[i], -i))
        match = target_pick == token
        decisions.append(
            {"position": position, "proposed": token, "target_pick": target_pick, "accepted": match and accepted == position}
        )
        if match and accepted == position:
            accepted += 1
    return {"logits": logits, "accepted_length": accepted, "decisions": decisions}


def commit_verified_prefix(
    target: TargetAdapter, snapshot: dict[str, Any], accepted_tokens: list[int]
) -> dict[str, Any]:
    """Advance every target state object through exactly the accepted positions.

    Verification is pure, so the target must still be at the snapshot when
    commit begins; any drift there is a custody failure, not a commit."""
    pre = state_hash(target.export_state())
    if pre != snapshot["hash"]:
        raise SpecStepError("commit", f"state drifted during verification: {pre} != {snapshot['hash']}")
    before_prefix = list(target.export_state()["prefix"])
    target.advance(list(accepted_tokens))
    state = target.export_state()
    if list(state["prefix"]) != before_prefix + list(accepted_tokens):
        raise SpecStepError("commit", "target prefix does not equal old prefix plus accepted tokens")
    return {"state_hash": state_hash(state), "prefix_length": len(state["prefix"])}


def restore_target_state(target: TargetAdapter, snapshot: dict[str, Any]) -> str:
    target.load_state(copy.deepcopy(snapshot["state"]))
    restored = state_hash(target.export_state())
    if restored != snapshot["hash"]:
        raise SpecStepError("rollback", f"state hash drift after restore: {restored} != {snapshot['hash']}")
    return restored


def receipt_speculative_step(
    *,
    target_identity: dict[str, Any],
    drafter_identity: dict[str, Any],
    proposal: dict[str, Any],
    verification: dict[str, Any] | None,
    snapshot_hash: str,
    final_state_hash: str,
    accepted_length: int,
    bytes_read: int | None,
    wall_seconds: float,
    thermal: dict[str, Any] | None,
    terminal_status: str,
    existing_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    receipt = {
        "schema": "octopodes/k3-dspark-speculative-step@1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_identity": target_identity,
        "drafter_identity": drafter_identity,
        "proposal": proposal,
        "per_position_decisions": (verification or {}).get("decisions"),
        "accepted_length": accepted_length,
        "state_hash_before": snapshot_hash,
        "state_hash_after": final_state_hash,
        "bytes_read": bytes_read,
        "wall_seconds": wall_seconds,
        "thermal": thermal,
        "terminal_status": terminal_status,
    }
    # identity hash covers the semantic step only, never timing/telemetry -
    # replaying the same step must produce the same receipt_sha256
    body = {k: v for k, v in receipt.items()
            if k not in ("created_at", "wall_seconds", "thermal", "bytes_read")}
    receipt["receipt_sha256"] = hashlib.sha256(_canon(body)).hexdigest()
    if existing_receipts is not None:
        for prior in existing_receipts:
            if prior.get("receipt_sha256") == receipt["receipt_sha256"]:
                receipt["replay_of_existing_receipt"] = True
                break
    return receipt


def speculative_step(
    *,
    target: TargetAdapter,
    drafter: Drafter,
    aux_bundle: dict[str, Any],
    expected_layers: list[int],
    target_identity: dict[str, Any],
    drafter_identity: dict[str, Any],
    existing_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One full speculative step across every contract, fail-closed."""
    started = time.perf_counter()
    snapshot = snapshot_target_state(target)
    prefix = list(target.export_state()["prefix"])
    proposal: dict[str, Any] = {}
    verification: dict[str, Any] | None = None
    accepted: list[int] = []
    status = "ok"
    try:
        proposal = draft_block(drafter, aux_bundle, prefix, expected_layers)
        verification = verify_proposed_block(target, proposal["tokens"])
        accepted = proposal["tokens"][: verification["accepted_length"]]
        if accepted:
            commit_verified_prefix(target, snapshot, accepted)
        else:
            restore_target_state(target, snapshot)
    except SpecStepError as exc:
        status = f"failed:{exc.stage}"
        restore_target_state(target, snapshot)
    except Exception as exc:  # verifier or drafter exception: rollback, preserve
        status = f"exception:{type(exc).__name__}"
        restore_target_state(target, snapshot)
    final_hash = state_hash(target.export_state())
    return receipt_speculative_step(
        target_identity=target_identity,
        drafter_identity=drafter_identity,
        proposal=proposal,
        verification=verification,
        snapshot_hash=snapshot["hash"],
        final_state_hash=final_hash,
        accepted_length=len(accepted),
        bytes_read=None,
        wall_seconds=time.perf_counter() - started,
        thermal=None,
        terminal_status=status,
        existing_receipts=existing_receipts,
    )
