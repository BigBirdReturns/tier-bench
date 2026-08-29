"""Baseline-gated adjudication for the strict-state block verifier.

This module - not prose, not a separately performed manual comparison - is
the authority that computes STRICT_CANONICAL_COMMIT. It loads the sealed
sequential baselines named by a baseline manifest, compares every required
state component at every accepted position with the content-bound component
roots from contracts.py, and emits PASS only when:

  1. the target token stream is exact (accepted tokens equal the baseline
     appended tokens; the correction equals the baseline argmax);
  2. the accepted-prefix boundary is exact (equals the expected denominator);
  3. every required state component is present;
  4. every required component root is bit-exact (93 layer caches, every KDA
     and MLA tensor, the complete attn_res bank, position, prefix, final
     hidden);
  5. the baseline manifest and run identities verify (manifest aggregate
     root, model index, parent cached state, parent prefix digest, baseline
     file digests, baseline content roots);
  6. no additional unbound state exists (exact per-kind tensor key sets,
     exact per-position file inventory);
  7. the adopted checkpoint is the checkpoint at the exact accepted boundary.

Logit comparison is reported SEPARATELY (LOGIT_ARGMAX_EQUIVALENCE,
LOGIT_MARGIN_EQUIVALENCE, LOGIT_NUMERICAL_EQUIVALENCE) and never weakens the
bit-exact state-adoption gate.

Two properties the @1 gate did not have:

  - The pinned root covers the WHOLE canonical baseline manifest, excluding
    only its own root field, so identity fields, the token ground truth, the
    accepted denominator and the comparison policy are all bound. Under @1 a
    substituted manifest could rewrite any of them and still satisfy
    --expect-baseline-root.
  - --expected-accepted is REQUIRED. Omitting it used to make the boundary
    criterion unconditionally true, and the emitted verdict did not record
    whether a denominator had been supplied at all. It is now mandatory,
    checked against the manifest's own denominator, and serialised into the
    verdict.

CLI re-adjudication over existing artifacts (no K3 execution):

  python -m k3_dspark_speculative.strict_baseline_gate \
      --run-dir <out dir of a strict run> \
      --parent-run-dir <parent cached run> \
      --baseline-manifest <BASELINE-MANIFEST.json> \
      --expect-baseline-root <sha256> \
      --expected-accepted <K>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import torch

if __package__:
    from . import contracts as C
else:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from k3_dspark_speculative import contracts as C  # type: ignore

MANIFEST_SCHEMA = "octopodes/k3-sequential-baseline-manifest@2"
EXPECTED_TENSOR_KEYS = {"KDA": {"conv_q", "conv_k", "conv_v", "recurrent"},
                        "MLA": {"key", "value"}}
LAYERS = 93
MARGIN_TOLERANCE = 1e-3
TENSOR_ROOT_RULE = "sha256 of contracts._encode_state binary encoding (dtype, shape, layout, logical bytes)"

# the root covers the WHOLE canonical manifest, excluding only its own field
ROOT_EXCLUDED_FIELD = "aggregate_root_sha256"

REQUIRED_MANIFEST_FIELDS = (
    "schema",
    "model_index_sha256",
    "parent_checkpoint_sha256",
    "parent_sequence_length",
    "parent_prefix_sha256",
    "accepted_position_denominator",
    "comparison_policy",
    "positions",
)

REQUIRED_POSITION_FIELDS = (
    "generation",
    "sequence_length",
    "appended_token",
    "layer_cache_dir",
    "layer_files",
    "checkpoint_file",
    "checkpoint_sha256",
    "final_hidden_root",
    "attn_res_bank_root",
    "logits_file",
    "logits_sha256",
)


def comparison_policy() -> dict[str, Any]:
    """The comparison semantics this module implements, in manifest form.

    A manifest that declares a different policy is refused: the pinned root
    must bind HOW the comparison is performed, not only what it compares."""
    return {
        "layers": LAYERS,
        "expected_tensor_keys": {k: sorted(v) for k, v in EXPECTED_TENSOR_KEYS.items()},
        "tensor_root_rule": TENSOR_ROOT_RULE,
        "margin_tolerance": MARGIN_TOLERANCE,
        "state_file_inventory": ["layer-000.pt .. layer-092.pt", "attn-res-bank.pt"],
    }


def tensor_root(t: torch.Tensor) -> str:
    enc, _ = C._encode_state(t, "t")
    return hashlib.sha256(enc).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_manifest_body(manifest: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in manifest.items() if k != ROOT_EXCLUDED_FIELD}


def manifest_aggregate_root(manifest: dict[str, Any]) -> str:
    """Digest of the COMPLETE canonical manifest, excluding only its own root
    field.

    The @1 rule hashed the layer/checkpoint/logit digests alone, so identity
    fields (model index, parent checkpoint, parent sequence length), the token
    ground truth (appended_token), the accepted denominator and the comparison
    policy could all be rewritten while --expect-baseline-root stayed
    satisfied. Nothing outside the root field is unbound now."""
    body = canonical_manifest_body(manifest)
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"),
                   allow_nan=False, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def load_manifest(path: Path, expected_root: str | None) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"baseline manifest schema {manifest.get('schema')!r}")
    missing = [f for f in REQUIRED_MANIFEST_FIELDS if f not in manifest]
    if missing:
        raise ValueError(f"baseline manifest missing required fields {missing}")
    if manifest["comparison_policy"] != comparison_policy():
        raise ValueError(
            "baseline manifest declares a comparison policy this gate does not "
            "implement - refusing a relaxed or substituted policy")
    positions = manifest["positions"]
    if not positions:
        raise ValueError("baseline manifest carries no positions")
    for pos, entry in positions.items():
        gaps = [f for f in REQUIRED_POSITION_FIELDS if f not in entry]
        if gaps:
            raise ValueError(f"baseline position {pos} missing fields {gaps}")
        if len(entry["layer_files"]) != LAYERS:
            raise ValueError(
                f"baseline position {pos} binds {len(entry['layer_files'])} layer "
                f"files, not {LAYERS}")
    denom = manifest["accepted_position_denominator"]
    if not isinstance(denom, int) or denom < 1:
        raise ValueError(
            f"baseline manifest accepted_position_denominator {denom!r} is not a "
            "positive integer")
    if sorted(int(p) for p in positions) != list(range(1, denom + 1)):
        raise ValueError(
            "baseline manifest positions are not exactly 1..accepted_position_denominator")
    root = manifest_aggregate_root(manifest)
    if root != manifest.get(ROOT_EXCLUDED_FIELD):
        raise ValueError("baseline manifest aggregate root does not recompute")
    if expected_root is not None and root != expected_root:
        raise ValueError(
            f"baseline manifest root {root} != expected {expected_root} - "
            "refusing a substituted baseline")
    return manifest


def _fail(verdicts: dict, reason: str, divergence: dict | None = None) -> None:
    verdicts["failures"].append(reason)
    if divergence is not None and verdicts["first_divergence"] is None:
        verdicts["first_divergence"] = divergence


def _first_coordinate(a: torch.Tensor, b: torch.Tensor):
    if a.shape != b.shape or a.dtype != b.dtype:
        return {"kind": "structure", "expected": [list(a.shape), str(a.dtype)],
                "observed": [list(b.shape), str(b.dtype)]}
    neq = torch.nonzero((a.reshape(-1) != b.reshape(-1)), as_tuple=False)
    if neq.numel() == 0:
        return None
    flat = int(neq[0])
    coord, rem = [], flat
    for dim in reversed(a.shape):
        coord.append(rem % dim)
        rem //= dim
    return {"kind": "content", "flat_index": flat,
            "coordinate": [int(x) for x in reversed(coord)]}


def gate(
    *,
    state_dir: Path,
    per_position_logits: Path,
    manifest: dict[str, Any],
    model_index_sha256: str,
    parent_checkpoint_sha256: str,
    parent_sequence_length: int,
    proposed: list[int],
    accepted: int,
    committed: list[int],
    expected_accepted: int | None,
    parent_prefix_sha256: str | None = None,
) -> dict[str, Any]:
    verdicts: dict[str, Any] = {
        "schema": "octopodes/k3-strict-canonical-commit-verdict@2",
        "criteria": {},
        "failures": [],
        "first_divergence": None,
        "positions": {},
        "logit_equivalence": {},
        # the denominator this adjudication was gated on is part of the record:
        # a verdict can no longer be read without knowing whether one was given
        "expected_accepted": expected_accepted,
        "expected_accepted_supplied": expected_accepted is not None,
        "comparison_policy": comparison_policy(),
    }

    # criterion 5: manifest and run identities
    identity_ok = True
    if manifest.get("model_index_sha256") != model_index_sha256:
        identity_ok = False
        _fail(verdicts, "manifest model index != run model index")
    if manifest.get("parent_checkpoint_sha256") != parent_checkpoint_sha256:
        identity_ok = False
        _fail(verdicts, "manifest parent cached-state identity != run parent")
    if manifest.get("parent_sequence_length") != parent_sequence_length:
        identity_ok = False
        _fail(verdicts, "manifest parent sequence length != run parent")
    if parent_prefix_sha256 is not None and \
            manifest.get("parent_prefix_sha256") != parent_prefix_sha256:
        identity_ok = False
        _fail(verdicts, "manifest parent prefix digest != run parent prefix digest")

    # criterion 2: accepted boundary. A PASS-capable adjudication REQUIRES a
    # denominator - without one, boundary_ok was unconditionally true and the
    # committed capsule could not tell a gated invocation from an ungated one.
    if expected_accepted is None:
        boundary_ok = False
        _fail(verdicts, "no accepted-position denominator supplied "
                        "(--expected-accepted): a PASS may not be emitted ungated")
    elif accepted != expected_accepted:
        boundary_ok = False
        _fail(verdicts, f"accepted boundary {accepted} != expected denominator "
                        f"{expected_accepted}")
    elif manifest["accepted_position_denominator"] != expected_accepted:
        boundary_ok = False
        _fail(verdicts, f"baseline manifest covers "
                        f"{manifest['accepted_position_denominator']} accepted "
                        f"positions, not the claimed {expected_accepted}")
    else:
        boundary_ok = True

    # criterion 1: token stream (accepted tokens + correction vs baselines)
    token_ok = True
    for p in range(1, accepted + 1):
        entry = manifest["positions"].get(str(p))
        if entry is None:
            token_ok = False
            _fail(verdicts, f"no baseline for accepted position {p}")
            continue
        if committed[p - 1] != entry["appended_token"]:
            token_ok = False
            _fail(verdicts, f"position {p}: committed token {committed[p - 1]} "
                            f"!= baseline appended {entry['appended_token']}")

    strict_logits = torch.load(per_position_logits, map_location="cpu",
                               weights_only=False)

    # correction token = baseline argmax at the boundary position
    if accepted >= 1 and str(accepted) in manifest["positions"]:
        entry = manifest["positions"][str(accepted)]
        base_logits = torch.load(Path(entry["logits_file"]), map_location="cpu",
                                 weights_only=False)["logits"]
        base_row = torch.as_tensor(base_logits).reshape(-1)
        if len(committed) > accepted and committed[accepted] != int(base_row.argmax()):
            token_ok = False
            _fail(verdicts, f"correction token {committed[accepted]} != baseline "
                            f"argmax {int(base_row.argmax())}")

    # criteria 3, 4, 6, 7: per-position component comparison
    state_ok = True
    for p in range(1, accepted + 1):
        entry = manifest["positions"].get(str(p))
        if entry is None:
            state_ok = False
            continue
        pos_dir = state_dir / f"position-{p:02d}"
        report = {"layers_exact": 0, "layers_divergent": [],
                  "bank_exact": False, "hidden_exact": False,
                  "unbound_state": []}
        expected_files = {f"layer-{i:03d}.pt" for i in range(LAYERS)} | {"attn-res-bank.pt"}
        actual_files = {f.name for f in pos_dir.iterdir()} if pos_dir.is_dir() else set()
        stray = sorted(actual_files - expected_files)
        if stray:
            report["unbound_state"].append(f"unexpected files {stray}")
            state_ok = False
            _fail(verdicts, f"position {p}: unbound state files {stray}")
        if not expected_files <= actual_files:
            missing = sorted(expected_files - actual_files)
            state_ok = False
            _fail(verdicts, f"position {p}: missing state files {missing[:4]}")
            verdicts["positions"][p] = report
            continue
        # baseline custody: rehash every named baseline file
        base_dir = Path(entry["layer_cache_dir"])
        for i in range(LAYERS):
            name = f"layer-{i:03d}.pt"
            expected_sha = entry["layer_files"][name]
            base_path = base_dir / name
            if sha256_file(base_path) != expected_sha:
                state_ok = False
                _fail(verdicts, f"position {p}: baseline {name} fails custody rehash")
                continue
            s = torch.load(pos_dir / name, map_location="cpu", weights_only=False)
            a = torch.load(base_path, map_location="cpu", weights_only=False)
            kind = a["kind"]
            if s.get("kind") != kind:
                state_ok = False
                _fail(verdicts, f"position {p} layer {i}: kind mismatch",
                      {"position": p, "layer": i, "component": "kind",
                       "expected_root": a.get("kind"), "observed_root": s.get("kind")})
                continue
            if a["sequence_length"] != parent_sequence_length + p or \
                    s.get("absolute_position") != parent_sequence_length + p:
                state_ok = False
                _fail(verdicts, f"position {p} layer {i}: position component mismatch")
                continue
            s_keys = set(s["tensors"])
            a_keys = set(a["tensors"])
            expected_keys = EXPECTED_TENSOR_KEYS[kind]
            if s_keys != expected_keys or a_keys != expected_keys:
                state_ok = False
                report["unbound_state"].append(f"layer {i}: keys {sorted(s_keys)}")
                _fail(verdicts, f"position {p} layer {i}: tensor key set "
                                f"{sorted(s_keys)} != required {sorted(expected_keys)}")
                continue
            layer_exact = True
            for key in sorted(expected_keys):
                r_s = tensor_root(s["tensors"][key])
                r_a = tensor_root(a["tensors"][key])
                if r_s != r_a:
                    layer_exact = False
                    state_ok = False
                    div = {"position": p, "layer": i, "component": f"{kind}.{key}",
                           "expected_root": r_a, "observed_root": r_s}
                    coord = _first_coordinate(a["tensors"][key], s["tensors"][key])
                    if coord:
                        div.update(coord)
                    _fail(verdicts, f"position {p} layer {i} {kind}.{key} divergent", div)
            if layer_exact:
                report["layers_exact"] += 1
            else:
                report["layers_divergent"].append(i)
        # attn_res bank + final hidden vs the sealed sequential checkpoint
        ckpt_path = Path(entry["checkpoint_file"])
        if sha256_file(ckpt_path) != entry["checkpoint_sha256"]:
            state_ok = False
            _fail(verdicts, f"position {p}: baseline checkpoint fails custody rehash")
        else:
            bank = torch.load(pos_dir / "attn-res-bank.pt", map_location="cpu",
                              weights_only=False)
            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            base_bank_root = tensor_root(ckpt["block_residual"])
            base_hidden_root = tensor_root(ckpt["hidden_states"])
            # the manifest's declared content roots are part of the pinned root,
            # so the baseline's own tensors must match what was sealed
            if base_bank_root != entry["attn_res_bank_root"]:
                state_ok = False
                _fail(verdicts, f"position {p}: baseline attn_res bank content root "
                                f"!= manifest-declared root")
            if base_hidden_root != entry["final_hidden_root"]:
                state_ok = False
                _fail(verdicts, f"position {p}: baseline final hidden content root "
                                f"!= manifest-declared root")
            report["bank_exact"] = tensor_root(bank["attn_res_bank"]) == base_bank_root
            report["hidden_exact"] = tensor_root(bank["final_hidden"]) == base_hidden_root
            if not report["bank_exact"]:
                state_ok = False
                _fail(verdicts, f"position {p}: attn_res bank divergent",
                      {"position": p, "component": "attn_res",
                       "expected_root": tensor_root(ckpt["block_residual"]),
                       "observed_root": tensor_root(bank["attn_res_bank"])})
            if not report["hidden_exact"]:
                state_ok = False
                _fail(verdicts, f"position {p}: final hidden divergent")
            if bank.get("absolute_position") != parent_sequence_length + p:
                state_ok = False
                _fail(verdicts, f"position {p}: bank position component mismatch")
        verdicts["positions"][p] = report

        # separate logit equivalence lanes (never part of the state gate)
        if sha256_file(Path(entry["logits_file"])) != entry["logits_sha256"]:
            _fail(verdicts, f"position {p}: baseline logits fail custody rehash")
            state_ok = False
        else:
            base_logits = torch.load(Path(entry["logits_file"]), map_location="cpu",
                                     weights_only=False)["logits"]
            s_row = strict_logits[p - 1].reshape(-1)
            a_row = torch.as_tensor(base_logits).reshape(-1).to(s_row.dtype)
            s_top = s_row.topk(2).values
            a_top = a_row.topk(2).values
            verdicts["logit_equivalence"][p] = {
                "LOGIT_ARGMAX_EQUIVALENCE": bool(int(s_row.argmax()) == int(a_row.argmax())),
                "LOGIT_MARGIN_EQUIVALENCE": bool(abs(float(s_top[0] - s_top[1])
                                                     - float(a_top[0] - a_top[1]))
                                                 <= MARGIN_TOLERANCE),
                "LOGIT_NUMERICAL_EQUIVALENCE": bool(torch.equal(s_row, a_row)),
                "max_abs_diff": float((s_row - a_row).abs().max()),
            }

    # criterion 7: adopted checkpoint at exact accepted boundary
    adoption_ok = state_ok and boundary_ok and accepted >= 1
    selected = accepted if adoption_ok else 0

    verdicts["criteria"] = {
        "1_token_stream_exact": token_ok,
        "2_accepted_boundary_exact": boundary_ok,
        "3_all_components_present": state_ok,
        "4_component_roots_bit_exact": state_ok,
        "5_identities_verify": identity_ok,
        "6_no_unbound_state": state_ok,
        "7_checkpoint_at_accepted_boundary": adoption_ok,
    }
    verdicts["selected_checkpoint"] = selected
    verdicts["STRICT_CANONICAL_COMMIT"] = (
        "PASS" if (token_ok and boundary_ok and state_ok and identity_ok
                   and adoption_ok) else "FAIL")
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--parent-run-dir", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--expect-baseline-root", default=None)
    parser.add_argument("--expected-accepted", type=int, required=True,
                        help="accepted-position denominator; REQUIRED - a PASS may "
                             "not be emitted without one")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    manifest = load_manifest(args.baseline_manifest, args.expect_baseline_root)
    receipt = json.loads(
        (args.run_dir / "STRICT-VERIFY-RECEIPT.json").read_text(encoding="utf-8"))
    progress = json.loads(
        (args.parent_run_dir / "progress.json").read_text(encoding="utf-8-sig"))
    verdicts = gate(
        state_dir=args.run_dir / "strict-state",
        per_position_logits=args.run_dir / "per-position-logits.pt",
        manifest=manifest,
        model_index_sha256=progress["source"]["model_index_sha256"],
        parent_checkpoint_sha256=progress["checkpoint_sha256"],
        parent_sequence_length=progress["attention_cache"]["sequence_length"],
        proposed=receipt["proposed"],
        accepted=receipt["accepted_length"],
        committed=receipt["committed_tokens"],
        expected_accepted=args.expected_accepted,
        parent_prefix_sha256=progress["source"].get("sequence_sha256"),
    )
    verdicts["baseline_manifest_root"] = manifest["aggregate_root_sha256"]
    verdicts["source_receipt"] = "STRICT-VERIFY-RECEIPT.json"
    out = args.out or (args.run_dir / "STRICT-ADJUDICATION.json")
    out.write_text(json.dumps(verdicts, indent=1), encoding="utf-8")
    print(json.dumps({"STRICT_CANONICAL_COMMIT": verdicts["STRICT_CANONICAL_COMMIT"],
                      "selected_checkpoint": verdicts["selected_checkpoint"],
                      "failures": verdicts["failures"][:5],
                      "first_divergence": verdicts["first_divergence"]}, indent=1))
    return 0 if verdicts["STRICT_CANONICAL_COMMIT"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
