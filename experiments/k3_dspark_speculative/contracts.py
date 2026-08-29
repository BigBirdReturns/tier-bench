"""Speculative-execution contracts for the K3 <-> DSpark lane.

Every interface the morning campaign needs, exercised against synthetic
tensors and a small deterministic target adapter. NO K3 integration is
claimed by these tests; K3 remains the sole token adjudicator when the real
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
  - State custody is by content, never by representation: KDA / MLA /
    AttnRes / position / prefix are bound through a recursive, type-tagged
    binary manifest. Dense tensors bind dtype, shape, layout, logical byte
    count, and the SHA-256 of their contiguous raw logical bytes. Unsupported
    types fail closed - nothing ever falls through to repr.
  - Receipt semantics (schema @2) separate what was PROPOSED, what the target
    VERIFIED, and what was actually COMMITTED. A failed commit that rolls the
    state back must report committed_length = 0; the @1 contradiction
    (terminal_status failed:commit with a positive accepted length) is
    structurally impossible. proposed_length is DERIVED from proposal.tokens
    and every decision is bound to its position's exact proposed token, so an
    externally supplied receipt cannot claim a token that was never proposed.
  - Proposal telemetry is validated BEFORE the target is ever driven: score
    count equals token count, every score and the confidence is a real finite
    number, and every token id is an exact integer. Non-finite telemetry used
    to survive verification and target advancement and only surface at receipt
    canonicalisation - after the state had already moved.
  - The custody boundary encloses RECEIPT CONSTRUCTION. If the step's own
    record cannot be built, the snapshot is restored and a bounded failure
    receipt - integers and strings only, so it cannot fail to canonicalise -
    is emitted. A step never ends with advanced target state and no receipt.
  - There is ONE adjudication authority, adjudicate_logit_row: dimension and
    finiteness are gated before any pick is derived, and the production ARM C
    verifier imports it rather than calling argmax on a raw row.
  - An auxiliary tap bundle is admissible only if it BINDS the outcome of the
    target run that produced it (return code 0, terminal status ok). Captures
    from a nonzero target run are preserved under a distinct failure schema
    that validate_aux_bundle refuses.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import operator
import struct
import time
from dataclasses import dataclass
from typing import Any, Protocol

MAX_BLOCK = 7
STATE_KEYS = ("kda", "mla", "attn_res", "position", "prefix")

RECEIPT_SCHEMA_V1 = "octopodes/k3-dspark-speculative-step@1"
RECEIPT_SCHEMA_V2 = "octopodes/k3-dspark-speculative-step@2"


@dataclass
class SpecStepError(Exception):
    stage: str
    detail: str

    def __str__(self) -> str:
        return f"{self.stage}: {self.detail}"


# --------------------------------------------------------------------------
# Canonical receipt-body encoding (JSON values only, strict, no repr rescue)
# --------------------------------------------------------------------------

def _canon(value: Any) -> bytes:
    """Canonical bytes for receipt identity hashing.

    Receipt bodies are JSON-safe by construction. Anything that is not is a
    programming error and fails closed instead of being smuggled through a
    lossy repr."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SpecStepError("canon", f"non-canonical receipt value: {exc}")


# --------------------------------------------------------------------------
# State custody: recursive, type-tagged, content-bound manifest
# --------------------------------------------------------------------------

_TORCH_CACHE: Any = None


def _torch() -> Any:
    """Import torch lazily; synthetic control paths must not require it."""
    global _TORCH_CACHE
    if _TORCH_CACHE is None:
        try:
            import torch  # noqa: PLC0415

            _TORCH_CACHE = torch
        except ImportError:
            _TORCH_CACHE = False
    return _TORCH_CACHE or None


def _u64(n: int) -> bytes:
    return struct.pack(">Q", n)


def _tensor_binding(value: Any, path: str) -> tuple[bytes, dict[str, Any]]:
    """Bind one dense torch tensor: (binary encoding, manifest record).

    The binding covers semantic field coordinate (via the enclosing container
    keys and the record's ``field``), dtype, shape, layout, logical element
    byte count, and the SHA-256 of the contiguous raw logical bytes. The
    source tensor is never mutated: hashing works on a CPU copy."""
    torch = _torch()
    if getattr(value, "is_quantized", False):
        raise SpecStepError(
            "state_manifest", f"quantized tensor at {path} has no canonical encoding"
        )
    if value.layout != torch.strided:
        raise SpecStepError(
            "state_manifest",
            f"unsupported tensor layout {value.layout} at {path} "
            "(only dense/strided tensors have a specified canonical encoding)",
        )
    if getattr(value, "is_meta", False):
        raise SpecStepError("state_manifest", f"meta/lazy tensor at {path} has no bytes")
    t = value.detach()
    if t.is_conj():
        t = t.resolve_conj()
    if getattr(t, "is_neg", None) and t.is_neg():
        t = t.resolve_neg()
    t = t.to("cpu", copy=True).contiguous().reshape(-1)
    nbytes = t.numel() * t.element_size()
    if t.numel() == 0:
        raw = b""
    else:
        try:
            raw = t.numpy().tobytes()
        except (TypeError, RuntimeError):
            # dtypes without a numpy analogue (e.g. bfloat16): byte view
            raw = t.view(torch.uint8).numpy().tobytes()
    if len(raw) != nbytes:
        raise SpecStepError(
            "state_manifest", f"tensor at {path}: raw byte count {len(raw)} != logical {nbytes}"
        )
    digest = hashlib.sha256(raw).hexdigest()
    record = {
        "type": "tensor",
        "field": path,
        "dtype": str(value.dtype),
        "shape": list(value.shape),
        "layout": str(value.layout),
        "nbytes": nbytes,
        "data_sha256": digest,
    }
    enc = (
        b"X"
        + _encode_scalar_str(str(value.dtype))
        + _u64(len(value.shape))
        + b"".join(_u64(int(d)) for d in value.shape)
        + _encode_scalar_str(str(value.layout))
        + _u64(nbytes)
        + bytes.fromhex(digest)
    )
    return enc, record


def _encode_scalar_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return b"S" + _u64(len(b)) + b


def _encode_state(value: Any, path: str) -> tuple[bytes, Any]:
    """Recursive, type-tagged binary encoding + JSON-able manifest mirror.

    Supported: dense torch tensors, dict (str keys), list, tuple, str, bool,
    int, float, bytes, None. Anything else fails closed."""
    torch = _torch()
    if torch is not None and isinstance(value, torch.Tensor):
        return _tensor_binding(value, path)
    if value is None:
        return b"Z", {"type": "null"}
    if isinstance(value, bool):  # before int: bool is an int subclass
        return b"B" + (b"1" if value else b"0"), {"type": "bool", "value": value}
    if isinstance(value, int):
        digits = str(value).encode("ascii")
        return b"I" + _u64(len(digits)) + digits, {"type": "int", "value": value}
    if isinstance(value, float):
        return b"F" + struct.pack(">d", value), {"type": "float", "value": value}
    if isinstance(value, str):
        return _encode_scalar_str(value), {"type": "str", "value": value}
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return (
            b"Y" + _u64(len(raw)) + raw,
            {"type": "bytes", "nbytes": len(raw), "data_sha256": hashlib.sha256(raw).hexdigest()},
        )
    if isinstance(value, (list, tuple)):
        tag = b"L" if isinstance(value, list) else b"T"
        parts = [tag, _u64(len(value))]
        items = []
        for i, item in enumerate(value):
            enc, rec = _encode_state(item, f"{path}[{i}]")
            parts.append(enc)
            items.append(rec)
        return b"".join(parts), {"type": "list" if tag == b"L" else "tuple", "items": items}
    if isinstance(value, dict):
        keys = list(value.keys())
        if any(not isinstance(k, str) for k in keys):
            raise SpecStepError("state_manifest", f"non-string dict key at {path}")
        parts = [b"D", _u64(len(keys))]
        entries = {}
        for k in sorted(keys):
            enc, rec = _encode_state(value[k], f"{path}.{k}")
            parts.append(_encode_scalar_str(k))
            parts.append(enc)
            entries[k] = rec
        return b"".join(parts), {"type": "dict", "entries": entries}
    raise SpecStepError(
        "state_manifest",
        f"unsupported state type {type(value).__name__} at {path} - no canonical "
        "encoding is specified; refusing to hash by representation",
    )


def state_component_manifest(state: dict[str, Any]) -> dict[str, Any]:
    """Type-tagged manifest with an independent root per state component.

    Components are EXACTLY STATE_KEYS (kda, mla, attn_res, position, prefix):
    both missing and additional top-level keys refuse. Silently omitting
    adapter-specific state (extra caches, RNG state, renamed components) would
    let mutations to it evade verification and rollback custody while minting
    a valid-looking receipt. A later extension must introduce a new schema or
    a closed extension registry that independently defines how every
    additional component is encoded and hashed - it may not ride along
    unbound. Each component root is the SHA-256 of that component's recursive
    binary encoding; the manifest mirror records every dense-tensor binding
    (field coordinate, dtype, shape, layout, byte count, content digest)."""
    missing = [k for k in STATE_KEYS if k not in state]
    if missing:
        raise SpecStepError("state_manifest", f"target state missing keys: {missing}")
    extra = sorted(k for k in state if k not in STATE_KEYS)
    if extra:
        raise SpecStepError(
            "state_manifest",
            f"target state carries unbound additional keys {extra}; the "
            f"exported-state denominator is exactly {list(STATE_KEYS)} and "
            "unbound components may not evade custody",
        )
    components = {}
    for key in STATE_KEYS:
        enc, mirror = _encode_state(state[key], key)
        components[key] = {
            "root_sha256": hashlib.sha256(enc).hexdigest(),
            "manifest": mirror,
        }
    return {"schema": "octopodes/k3-state-component-manifest@1", "components": components}


def state_root_sha256(state: dict[str, Any]) -> str:
    """Aggregate custody root, derived from the five component roots."""
    manifest = state_component_manifest(state)
    agg = hashlib.sha256()
    for key in STATE_KEYS:
        agg.update(key.encode("ascii"))
        agg.update(b"\x00")
        agg.update(bytes.fromhex(manifest["components"][key]["root_sha256"]))
    return agg.hexdigest()


def state_hash(state: dict[str, Any]) -> str:
    """Authoritative state hash = the component-derived aggregate root.

    (Schema @1 hashed a JSON projection with ``default=repr``, which silently
    dropped tensor elements outside PyTorch's abbreviated print region. That
    path is removed; unsupported types now fail closed.)"""
    return state_root_sha256(state)


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


TAP_BUNDLE_SCHEMA = "octopodes/k3-dspark-tap-capture@1"
FAILED_TAP_BUNDLE_SCHEMA = "octopodes/k3-dspark-tap-capture-failed@1"


def validate_aux_bundle(bundle: dict[str, Any], expected_layers: list[int]) -> None:
    """Reject malformed hidden-state bundles before they reach a drafter.

    Admission requires the bundle to BIND the outcome of the target run that
    produced it. Captures from a target run that returned nonzero may be
    complete-looking and still come from an aborted traversal; a bundle that
    does not carry a successful target-run outcome is not drafter input."""
    if bundle.get("schema") == FAILED_TAP_BUNDLE_SCHEMA:
        raise SpecStepError(
            "aux_bundle",
            f"bundle is a preserved failure artifact "
            f"({bundle.get('terminal_status')!r}) and may not be adopted")
    if bundle.get("schema") != TAP_BUNDLE_SCHEMA:
        raise SpecStepError("aux_bundle", f"unknown schema {bundle.get('schema')!r}")
    if "target_run_return_code" not in bundle or "terminal_status" not in bundle:
        raise SpecStepError(
            "aux_bundle",
            "bundle binds no target-run outcome (target_run_return_code / "
            "terminal_status): a capture whose generation cannot be shown to have "
            "succeeded is not admissible drafter input")
    rc = bundle["target_run_return_code"]
    status = bundle["terminal_status"]
    if not isinstance(rc, int) or isinstance(rc, bool) or rc != 0:
        raise SpecStepError(
            "aux_bundle", f"target run returned {rc!r}, not 0")
    if status != "ok":
        raise SpecStepError("aux_bundle", f"terminal status {status!r} is not ok")
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


def _proposal_token(value: Any, index: int) -> int:
    """A proposal token id must be an exact integer. Bools are rejected even
    though they index; floats are rejected even when integral."""
    if isinstance(value, bool):
        raise SpecStepError("draft", f"proposal token {index} is a bool, not a token id")
    try:
        return operator.index(value)
    except TypeError:
        raise SpecStepError(
            "draft",
            f"proposal token {index} is {type(value).__name__}, not an integer token id",
        ) from None


def _finite_scalar(value: Any, what: str) -> float:
    """Proposal telemetry must be a real, finite number BEFORE the target is
    ever driven. NaN/Inf here used to survive draft, verification and target
    advancement, and only surfaced when the receipt was canonicalised - after
    the state had already moved."""
    if isinstance(value, bool) or isinstance(value, (str, bytes)):
        raise SpecStepError("draft", f"{what} is {type(value).__name__}, not a real number")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SpecStepError(
            "draft", f"{what} is {type(value).__name__}, not a real number") from None
    if not math.isfinite(v):
        raise SpecStepError("draft", f"{what} is non-finite ({value!r})")
    return v


def draft_block(
    drafter: Drafter, aux_bundle: dict[str, Any], prefix: list[int], expected_layers: list[int]
) -> dict[str, Any]:
    """Draft one block and FULLY validate its telemetry.

    Every field returned here is already proven canonical-safe, so no later
    stage of the step can discover a non-serialisable proposal after the
    target has been advanced."""
    validate_aux_bundle(aux_bundle, expected_layers)
    proposal = drafter.propose(aux_bundle, list(prefix))
    if not isinstance(proposal, dict):
        raise SpecStepError("draft", f"drafter returned {type(proposal).__name__}, not a mapping")
    tokens = proposal.get("tokens", [])
    if not isinstance(tokens, (list, tuple)):
        raise SpecStepError(
            "draft", f"proposal tokens is {type(tokens).__name__}, not a sequence")
    if not 1 <= len(tokens) <= MAX_BLOCK:
        raise SpecStepError("draft", f"proposal length {len(tokens)} outside 1..{MAX_BLOCK}")
    ids = [_proposal_token(t, i) for i, t in enumerate(tokens)]

    raw_scores = proposal.get("scores")
    if raw_scores is None:
        scores = [0.0] * len(ids)
    else:
        if not isinstance(raw_scores, (list, tuple)):
            raise SpecStepError(
                "draft", f"proposal scores is {type(raw_scores).__name__}, not a sequence")
        if len(raw_scores) != len(ids):
            raise SpecStepError(
                "draft",
                f"proposal carries {len(raw_scores)} scores for {len(ids)} tokens - "
                "score length must equal proposal-token length")
        scores = [_finite_scalar(s, f"proposal score {i}") for i, s in enumerate(raw_scores)]

    confidence = _finite_scalar(proposal.get("confidence", 0.0), "proposal confidence")
    return {"tokens": ids, "scores": scores, "confidence": confidence}


def snapshot_target_state(target: TargetAdapter) -> dict[str, Any]:
    state = copy.deepcopy(target.export_state())
    return {"state": state, "hash": state_hash(state)}


def validate_logit_row(row: Any, position: int, vocab_size: int | None) -> list[float]:
    """A target logit row must be nonempty, numeric, finite everywhere, and of
    the declared vocabulary dimension when one is available. NaN/Inf must fail
    verification, never silently pick a different finite token."""
    if not isinstance(row, (list, tuple)) or len(row) == 0:
        raise SpecStepError(
            "verify", f"position {position}: empty or non-sequence logit row")
    if vocab_size is not None and len(row) != vocab_size:
        raise SpecStepError(
            "verify",
            f"position {position}: logit row length {len(row)} != declared "
            f"vocabulary dimension {vocab_size}")
    values = []
    for i, v in enumerate(row):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SpecStepError(
                "verify",
                f"position {position}: nonnumeric logit at index {i} "
                f"({type(v).__name__})")
        v = float(v)
        if not math.isfinite(v):
            raise SpecStepError(
                "verify",
                f"position {position}: non-finite logit {v!r} at index {i}")
        values.append(v)
    return values


# backwards-compatible private alias (the gate is now public: production
# adjudication paths must import it rather than re-implement it)
_validate_logit_row = validate_logit_row


def greedy_pick(values: list[float]) -> int:
    """The single greedy rule: highest logit, lowest index on a tie."""
    return max(range(len(values)), key=lambda i: (values[i], -i))


def logit_row_digest(values: list[float], position: int) -> str:
    """Content digest of a validated logit row under the state encoding."""
    return hashlib.sha256(_encode_state(values, f"logits[{position}]")[0]).hexdigest()


def adjudicate_logit_row(
    row: Any,
    position: int,
    proposed_token: int,
    *,
    vocab_size: int | None = None,
    accepted_so_far: int = 0,
) -> tuple[dict[str, Any], list[float]]:
    """THE adjudication authority for one proposed position.

    Every production path that turns a target logit row into an acceptance
    decision must come through here: the row is gated for dimension and
    finiteness FIRST, and the pick, margins and row digest are then derived
    from the validated values. There is deliberately no second, weaker path -
    a NaN row must fail verification rather than silently select some other
    finite token."""
    values = validate_logit_row(row, position, vocab_size)
    target_pick = greedy_pick(values)
    top = values[target_pick]
    runner_up = max((v for i, v in enumerate(values) if i != target_pick), default=None)
    match = target_pick == proposed_token
    decision = {
        "position": position,
        "proposed": proposed_token,
        "target_pick": target_pick,
        "accepted": bool(match and accepted_so_far == position),
        "top_logit": top,
        "runner_up_logit": runner_up,
        "margin": None if runner_up is None else top - runner_up,
        "vocab_dimension": len(values),
        "logit_row_sha256": logit_row_digest(values, position),
        "finite_valid": True,
    }
    return decision, values


def verify_proposed_block(
    target: TargetAdapter,
    proposed_tokens: list[int],
    *,
    vocab_size: int | None = None,
) -> dict[str, Any]:
    if not 1 <= len(proposed_tokens) <= MAX_BLOCK:
        raise SpecStepError("verify", f"block length {len(proposed_tokens)} outside 1..{MAX_BLOCK}")
    logits = target.block_logits(list(proposed_tokens))
    if len(logits) != len(proposed_tokens):
        raise SpecStepError("verify", "target returned wrong number of positions")
    row_width: int | None = vocab_size
    accepted = 0
    decisions = []
    for position, (token, raw_row) in enumerate(zip(proposed_tokens, logits)):
        decision, row = adjudicate_logit_row(
            raw_row, position, token, vocab_size=row_width, accepted_so_far=accepted)
        if row_width is None:
            row_width = len(row)  # every row must share one dimension
        decisions.append(decision)
        if decision["accepted"]:
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


# --------------------------------------------------------------------------
# Speculative-step receipts, schema @2
# --------------------------------------------------------------------------
#
# @1 receipts (a single ambiguous ``accepted_length``) remain valid historical
# artifacts under RECEIPT_SCHEMA_V1 and are NOT reinterpreted: a reader must
# dispatch on the receipt's ``schema`` field. @2 separates:
#
#   proposed_length                what the drafter proposed
#   target_verified_prefix_length  what target verification agreed with
#   committed_length               what actually entered target state
#   rollback_performed             whether the snapshot was restored
#   state_transition               committed | rolled_back | rollback_failed | none
#
# Invariants (fail-closed at construction):
#   - committed_length > 0 requires terminal_status == "ok"
#   - committed_length <= target_verified_prefix_length <= proposed_length
#   - a rolled_back transition requires state_hash_after == state_hash_before
#   - a failed commit may PRESERVE target_verified_prefix_length for diagnosis
#     while committed_length reports 0

TERMINAL_TRANSITIONS = ("committed", "rolled_back", "rollback_failed", "none")


def validate_speculative_receipt(receipt: dict[str, Any]) -> None:
    """Fail-closed semantic validation for @2 receipts."""
    if receipt.get("schema") != RECEIPT_SCHEMA_V2:
        raise SpecStepError("receipt", f"not a @2 receipt: {receipt.get('schema')!r}")
    proposed = receipt["proposed_length"]
    verified = receipt["target_verified_prefix_length"]
    committed = receipt["committed_length"]
    status = receipt["terminal_status"]
    transition = receipt["state_transition"]
    if transition not in TERMINAL_TRANSITIONS:
        raise SpecStepError("receipt", f"unknown state_transition {transition!r}")
    if not isinstance(proposed, int) or proposed < 0:
        raise SpecStepError("receipt", f"proposed_length {proposed!r} is not a non-negative int")

    # proposed_length is DERIVED, not trusted: it must be the length of the
    # proposal the receipt actually carries. Otherwise a receipt can claim the
    # commitment of a token that was never proposed.
    proposal = receipt.get("proposal")
    if not isinstance(proposal, dict):
        raise SpecStepError(
            "receipt", f"proposal is {type(proposal).__name__}, not a mapping")
    tokens = proposal.get("tokens")
    if tokens is None:
        tokens = []
    if not isinstance(tokens, (list, tuple)):
        raise SpecStepError(
            "receipt", f"proposal tokens is {type(tokens).__name__}, not a sequence")
    if len(tokens) != proposed:
        raise SpecStepError(
            "receipt",
            f"proposed_length {proposed} != len(proposal.tokens) {len(tokens)} - "
            "the declared length must be derived from the proposal itself")
    for i, t in enumerate(tokens):
        if isinstance(t, bool) or not isinstance(t, int):
            raise SpecStepError(
                "receipt", f"proposal token {i} is {type(t).__name__}, not an int")

    if not isinstance(verified, int) or not 0 <= verified <= proposed:
        raise SpecStepError(
            "receipt",
            f"target_verified_prefix_length {verified!r} outside 0..proposed {proposed} - "
            "externally supplied receipts must satisfy the documented bound")
    if not isinstance(committed, int) or not 0 <= committed <= proposed:
        raise SpecStepError("receipt", f"committed_length {committed!r} outside 0..proposed {proposed}")
    if committed > verified:
        raise SpecStepError("receipt", f"committed_length {committed} exceeds verified prefix {verified}")
    decisions = receipt.get("per_position_decisions")
    if decisions is None:
        if verified != 0:
            raise SpecStepError(
                "receipt",
                f"verified prefix {verified} claimed without per-position decisions")
    else:
        if not isinstance(decisions, (list, tuple)):
            raise SpecStepError(
                "receipt",
                f"per_position_decisions is {type(decisions).__name__}, not a sequence")
        if len(decisions) != len(tokens):
            raise SpecStepError(
                "receipt",
                f"decision count {len(decisions)} != proposal-token count {len(tokens)}")
        # every decision must name its own position AND the exact token proposed
        # there: missing, duplicated, reordered or invented decisions all refuse.
        for i, (decision, token) in enumerate(zip(decisions, tokens)):
            if not isinstance(decision, dict):
                raise SpecStepError(
                    "receipt", f"decision {i} is {type(decision).__name__}, not a mapping")
            if decision.get("position") != i:
                raise SpecStepError(
                    "receipt",
                    f"decision {i} declares position {decision.get('position')!r} - "
                    "decisions must be in proposal order, one per position")
            if decision.get("proposed") != token:
                raise SpecStepError(
                    "receipt",
                    f"decision at position {i} names proposed token "
                    f"{decision.get('proposed')!r} but the proposal carries {token!r}")
        flags = [bool(d.get("accepted")) for d in decisions]
        prefix_len = 0
        for flag in flags:
            if flag:
                prefix_len += 1
            else:
                break
        if any(flags[prefix_len:]):
            raise SpecStepError(
                "receipt",
                "accepted decisions do not form one contiguous prefix")
        if prefix_len != verified:
            raise SpecStepError(
                "receipt",
                f"contiguous accepted prefix {prefix_len} != "
                f"target_verified_prefix_length {verified}")
    if committed > 0 and status != "ok":
        raise SpecStepError(
            "receipt",
            f"terminal_status {status!r} with committed_length {committed} > 0 - "
            "a failed or rolled-back step cannot report committed tokens",
        )
    if committed > 0 and transition != "committed":
        raise SpecStepError("receipt", f"committed_length {committed} with transition {transition!r}")
    if transition == "rolled_back":
        if not receipt["rollback_performed"]:
            raise SpecStepError("receipt", "rolled_back transition without rollback_performed")
        if receipt["state_hash_after"] != receipt["state_hash_before"]:
            raise SpecStepError(
                "receipt", "rolled_back transition but state_hash_after != state_hash_before"
            )
    if transition == "rollback_failed" and status == "ok":
        raise SpecStepError("receipt", "rollback_failed transition cannot be terminal ok")
    if receipt["rollback_performed"] and transition == "committed":
        raise SpecStepError(
            "receipt", "rollback_performed cannot coexist with a committed transition")
    if transition == "committed" and receipt["state_hash_after"] == receipt["state_hash_before"] and committed > 0:
        raise SpecStepError(
            "receipt",
            "committed transition with positive committed_length cannot leave "
            "the state root unchanged")


def receipt_speculative_step(
    *,
    target_identity: dict[str, Any],
    drafter_identity: dict[str, Any],
    proposal: dict[str, Any],
    verification: dict[str, Any] | None,
    snapshot_hash: str,
    final_state_hash: str,
    proposed_length: int,
    target_verified_prefix_length: int,
    committed_length: int,
    rollback_performed: bool,
    state_transition: str,
    bytes_read: int | None,
    wall_seconds: float,
    thermal: dict[str, Any] | None,
    terminal_status: str,
    existing_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    receipt = {
        "schema": RECEIPT_SCHEMA_V2,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_identity": target_identity,
        "drafter_identity": drafter_identity,
        "proposal": proposal,
        "per_position_decisions": (verification or {}).get("decisions"),
        "proposed_length": proposed_length,
        "target_verified_prefix_length": target_verified_prefix_length,
        "committed_length": committed_length,
        "rollback_performed": rollback_performed,
        "state_transition": state_transition,
        "state_hash_before": snapshot_hash,
        "state_hash_after": final_state_hash,
        "bytes_read": bytes_read,
        "wall_seconds": wall_seconds,
        "thermal": thermal,
        "terminal_status": terminal_status,
    }
    validate_speculative_receipt(receipt)
    # identity hash covers the semantic step only, never timing/telemetry -
    # replaying the same step must produce the same receipt_sha256. The
    # verified and committed lengths are separate members of the hashed body.
    body = {k: v for k, v in receipt.items()
            if k not in ("created_at", "wall_seconds", "thermal", "bytes_read")}
    receipt["receipt_sha256"] = hashlib.sha256(_canon(body)).hexdigest()
    if existing_receipts is not None:
        for prior in existing_receipts:
            if prior.get("receipt_sha256") == receipt["receipt_sha256"]:
                receipt["replay_of_existing_receipt"] = True
                break
    return receipt


UNAVAILABLE_STATE_HASH = "unavailable"


def _safe_identity(value: Any, label: str) -> dict[str, Any]:
    """Identity blocks are caller-supplied and may themselves be the reason a
    receipt could not be built. Keep them only if they canonicalise."""
    try:
        _canon(value)
    except SpecStepError:
        return {"bounded": True, "omitted": f"{label} is not canonical"}
    return value if isinstance(value, dict) else {"bounded": True, "value_type": type(value).__name__}


def _bounded_failure_receipt(
    *,
    target_identity: dict[str, Any],
    drafter_identity: dict[str, Any],
    proposal: dict[str, Any],
    snapshot_hash: str,
    final_state_hash: str,
    rollback_performed: bool,
    state_transition: str,
    wall_seconds: float,
    terminal_status: str,
    cause: str,
) -> dict[str, Any]:
    """The last-resort receipt for a step whose own record could not be built.

    Its body is integers and strings only, so canonicalisation cannot fail a
    second time. Proposal telemetry is dropped rather than repaired: if the
    step could not record itself, none of that telemetry is trustworthy. The
    receipt always reports committed_length 0 - the caller has already restored
    the snapshot before this is reached."""
    tokens = proposal.get("tokens") if isinstance(proposal, dict) else None
    safe_tokens: list[int] = []
    if isinstance(tokens, (list, tuple)):
        for t in tokens:
            if isinstance(t, bool):
                safe_tokens = []
                break
            try:
                safe_tokens.append(operator.index(t))
            except TypeError:
                safe_tokens = []
                break
    bounded_proposal = {
        "bounded_failure_receipt": True,
        "tokens": safe_tokens,
        "telemetry_omitted": (
            "scores and confidence dropped: the step's own receipt could not be "
            "constructed, so no proposal telemetry from it is trustworthy"),
        "receipt_failure_cause": str(cause)[:512],
    }
    return receipt_speculative_step(
        target_identity=_safe_identity(target_identity, "target_identity"),
        drafter_identity=_safe_identity(drafter_identity, "drafter_identity"),
        proposal=bounded_proposal,
        verification=None,
        snapshot_hash=snapshot_hash,
        final_state_hash=final_state_hash,
        proposed_length=len(safe_tokens),
        target_verified_prefix_length=0,
        committed_length=0,
        rollback_performed=rollback_performed,
        state_transition=state_transition,
        bytes_read=None,
        wall_seconds=wall_seconds,
        thermal=None,
        terminal_status=terminal_status,
        existing_receipts=None,
    )


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
    """One full speculative step across every contract, fail-closed.

    committed_length becomes positive only after the state transition
    succeeds; every failure path rolls back and reports committed_length 0
    (preserving target_verified_prefix_length for diagnosis)."""
    started = time.perf_counter()
    snapshot = snapshot_target_state(target)
    prefix = list(target.export_state()["prefix"])
    proposal: dict[str, Any] = {}
    verification: dict[str, Any] | None = None
    committed_length = 0
    rollback_performed = False
    state_transition = "none"
    status = "ok"

    def _roll_back() -> None:
        nonlocal rollback_performed, state_transition, status
        try:
            restore_target_state(target, snapshot)
            rollback_performed = True
            state_transition = "rolled_back"
        except Exception as exc:  # noqa: BLE001 - custody must record this
            state_transition = "rollback_failed"
            cause = f"rollback_failed:{type(exc).__name__}"
            status = cause if status == "ok" else f"{status}+{cause}"

    try:
        proposal = draft_block(drafter, aux_bundle, prefix, expected_layers)
        verification = verify_proposed_block(target, proposal["tokens"])
        accepted = proposal["tokens"][: verification["accepted_length"]]
        if accepted:
            commit_verified_prefix(target, snapshot, accepted)
            committed_length = len(accepted)
            state_transition = "committed"
        else:
            _roll_back()
    except SpecStepError as exc:
        status = f"failed:{exc.stage}"
        _roll_back()
    except Exception as exc:  # verifier or drafter exception: rollback, preserve
        status = f"exception:{type(exc).__name__}"
        _roll_back()

    # ---- receipt construction is INSIDE the custody boundary -------------
    # Everything above may have moved target state. If recording that outcome
    # fails for any reason, the step must still not end with advanced state and
    # no receipt: restore the exact snapshot, then emit a bounded receipt whose
    # body is scalars only and therefore cannot itself fail to canonicalise.
    try:
        final_hash = state_hash(target.export_state())
        return receipt_speculative_step(
            target_identity=target_identity,
            drafter_identity=drafter_identity,
            proposal=proposal,
            verification=verification,
            snapshot_hash=snapshot["hash"],
            final_state_hash=final_hash,
            proposed_length=len(proposal.get("tokens", [])),
            target_verified_prefix_length=(verification or {}).get("accepted_length", 0),
            committed_length=committed_length,
            rollback_performed=rollback_performed,
            state_transition=state_transition,
            bytes_read=None,
            wall_seconds=time.perf_counter() - started,
            thermal=None,
            terminal_status=status,
            existing_receipts=existing_receipts,
        )
    except Exception as exc:  # noqa: BLE001 - custody outranks the record
        cause = f"failed:receipt:{type(exc).__name__}"
        status = cause if status == "ok" else f"{status}+{cause}"
        if not rollback_performed:
            _roll_back()
        committed_length = 0
        if rollback_performed:
            final_hash = snapshot["hash"]  # restore_target_state proved this
        else:
            try:
                final_hash = state_hash(target.export_state())
            except Exception:  # noqa: BLE001
                final_hash = UNAVAILABLE_STATE_HASH
        return _bounded_failure_receipt(
            target_identity=target_identity,
            drafter_identity=drafter_identity,
            proposal=proposal,
            snapshot_hash=snapshot["hash"],
            final_state_hash=final_hash,
            rollback_performed=rollback_performed,
            state_transition=state_transition,
            wall_seconds=time.perf_counter() - started,
            terminal_status=status,
            cause=f"{type(exc).__name__}: {exc}",
        )
