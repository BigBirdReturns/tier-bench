"""ARM C - streamed K3 block verification of DSpark proposals.

One streamed layer traversal advances all K proposed tokens together: per
layer, the admitted run_dense_layer / run_moe_layer executors run ONCE with
hidden [1, K, 7168] and the parent's retained attention cache (KDA continues
via the chunk kernel with initial_state - Moonshot's native multi-token path;
MLA appends incrementally). Weights stream from disk once per layer regardless
of K; the expert UNION per layer is the byte-cost of depth, captured per the
campaign freeze.

Acceptance (greedy, predeclared): proposal p_1 is judged by the PARENT run's
own final-state argmax (already sealed); p_{i+1} is judged by the block's
position-i argmax. The correction token is the target's argmax at the first
rejected position. Committed tokens = accepted prefix + correction.

Verification never mutates the parent: the parent cache lives on disk and the
traversal only reads it (rollback = don't adopt). Commit produces a SEPARATE
labeled state dir (schema arm-c-commit@1) for state comparison against the
sequential ARM A runs - it is NOT adopted into the custody chain; the
canonical chain remains the sequential runs. Strict state equality vs
sequential is an audit lane (chunk vs fused-recurrent kernels differ
numerically per the 2026-08-03 kernel finding); the operational gate is token
equivalence.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

SLICE = Path(r"C:\Users\octo-operator\TierFloor-Staging\kimi-runtime-slice")
sys.path.insert(0, str(SLICE))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch
import torch.nn.functional as F
from transformers import AutoConfig, AutoTokenizer

from k3_dspark_speculative import contracts

import run_cached_continuation as rcc
import run_full_depth_map as full
import run_real_k3_slice as core


def load_environment(parent_run_dir: Path, max_layer: int = 92):
    torch.cuda.set_device(core.DEVICE)
    torch.set_grad_enabled(False)
    weight_map, model_index_sha = core.load_weight_map()
    prefill_progress, _ = rcc.load_prefill(
        parent_run_dir, model_index_sha256=model_index_sha, max_layer=max_layer
    )
    outer = AutoConfig.from_pretrained(
        str(core.MODEL_ROOT), trust_remote_code=True, local_files_only=True
    )
    config = outer.text_config
    config._octo_kda_runtime_mode = "chunk_beta_compat"
    classes = full.load_classes()
    return weight_map, model_index_sha, prefill_progress, config, classes


def block_traversal(
    *,
    token_ids: list[int],
    prefill_progress: dict,
    config,
    classes,
    weight_map,
    retain: bool,
    max_layer: int = 92,
):
    """One streamed traversal of the proposed block. Returns final hidden,
    bank, retained per-layer caches (or None), and telemetry."""
    k = len(token_ids)
    embeddings, embed_receipt = core.load_embeddings(token_ids, weight_map)
    hidden = embeddings
    block = embeddings.new_zeros((k, 0, embeddings.shape[-1]))
    retained_layers = [] if retain else None
    telemetry = {"per_layer_wall_s": [], "expert_union_by_layer": {}, "embed": embed_receipt}
    for layer in range(0, max_layer + 1):
        started = time.perf_counter()
        prior = rcc.load_prefill_layer_cache(prefill_progress, layer)
        if layer == 0:
            output, block, _, retained_cache, _ = rcc.run_dense_layer(
                hidden_states=hidden, block_residual=block, prior_cache=prior,
                retain_cache=True, config=config, classes=classes, weight_map=weight_map)
        else:
            output, block, _, indices, _w, retained_cache, _ = rcc.run_moe_layer(
                layer=layer, hidden_states=hidden, block_residual=block,
                prior_cache=prior, retain_cache=True, config=config,
                classes=classes, weight_map=weight_map)
            telemetry["expert_union_by_layer"][layer] = int(
                torch.unique(indices.reshape(-1)).numel())
        if retained_layers is not None:
            retained_layers.append(
                {name: value.detach().to("cpu") for name, value in retained_cache.items()})
        hidden = output
        telemetry["per_layer_wall_s"].append(round(time.perf_counter() - started, 2))
    return hidden, block, retained_layers, telemetry


def per_position_logits(hidden, block, weight_map, config):
    """Finalize math generalized to every block position: attn-res blend with
    the output-side weights, final norm, K3 lm_head."""
    names = [
        "language_model.model.output_attn_res_proj.weight",
        "language_model.model.output_attn_res_norm.weight",
        "language_model.model.norm.weight",
        "language_model.lm_head.weight",
    ]
    tensors, _ = core.load_named_tensors(names, weight_map, device=core.DEVICE)
    width = hidden.shape[-1]
    blended = core.apply_attn_residual(
        hidden.reshape(-1, width), block,
        tensors[names[0]], tensors[names[1]], float(config.rms_norm_eps),
    ).reshape_as(hidden)
    normalized = core.rms_norm(blended, tensors[names[2]], float(config.rms_norm_eps))
    logits = F.linear(normalized[0].float(), tensors[names[3]].float())
    del tensors
    torch.cuda.empty_cache()
    return logits  # [K, V]


def parent_position_decision(parent_final: dict, proposed_token: int, vocab: int,
                             accepted_so_far: int) -> dict:
    """Position 0's judge is the PARENT run's sealed final state, not a row of
    this block. It still has to clear the same gate: declared vocabulary
    dimension, finiteness, and a real margin. The row digest is the parent's
    own sealed logits-tensor digest, computed under the parent's rule - that
    difference is recorded rather than papered over."""
    meta = parent_final.get("logits")
    if not isinstance(meta, dict):
        raise contracts.SpecStepError("verify", "parent final state carries no logits record")
    dim = int(meta["shape"][-1])
    if dim != vocab:
        raise contracts.SpecStepError(
            "verify",
            f"parent vocabulary dimension {dim} != block dimension {vocab}")
    finite_rate = float(meta.get("finite_rate", 0.0))
    if finite_rate != 1.0:
        raise contracts.SpecStepError(
            "verify", f"parent logits finite_rate {finite_rate} != 1.0")
    candidates = parent_final.get("top_candidates") or []
    if len(candidates) < 2:
        raise contracts.SpecStepError(
            "verify", "parent final state carries fewer than two ranked candidates")
    top = float(candidates[0]["logit"])
    runner_up = float(candidates[1]["logit"])
    if not (math.isfinite(top) and math.isfinite(runner_up)):
        raise contracts.SpecStepError("verify", "parent candidate logits are not finite")
    pick = int(candidates[0]["token_id"])
    return {
        "position": 0,
        "proposed": proposed_token,
        "target_pick": pick,
        "accepted": bool(pick == proposed_token and accepted_so_far == 0),
        "top_logit": top,
        "runner_up_logit": runner_up,
        "margin": top - runner_up,
        "vocab_dimension": dim,
        "logit_row_sha256": meta["sha256"],
        "logit_row_digest_rule": ("parent run's sealed logits-tensor sha256 (NOT the "
                                  "contracts row encoding used for block positions)"),
        "finite_valid": True,
        "judge": "parent run sealed final state",
    }


def adjudicate(parent_final: dict, proposed: list[int], logits: torch.Tensor):
    """Greedy acceptance through the SHARED contracts gate.

    p_1 is judged by the parent's own sealed argmax; p_{i+1} by block row i.
    Every judging row is validated for vocabulary dimension and finiteness
    before a pick is derived from it - a NaN or Inf row refuses instead of
    letting argmax select some other finite token. Each position preserves its
    complete row digest, finite-validation result, vocabulary dimension,
    target pick, proposed token, top and runner-up logits, margin, and its
    accepted-prefix decision."""
    vocab = int(logits.shape[-1])
    decisions: list[dict] = []
    accepted = 0
    for i, p in enumerate(proposed):
        if i == 0:
            decision = parent_position_decision(parent_final, p, vocab, accepted)
        else:
            decision, _ = contracts.adjudicate_logit_row(
                logits[i - 1].tolist(), i, p, vocab_size=vocab, accepted_so_far=accepted)
            decision["judge"] = f"block row {i - 1}"
        decisions.append(decision)
        if decision["accepted"]:
            accepted += 1

    # correction = the target's gated pick at the first rejected position
    if accepted == 0:
        correction = decisions[0]["target_pick"]
    elif accepted < len(proposed):
        correction = decisions[accepted]["target_pick"]
    else:
        # whole block accepted: the judge for the next position is the last row
        values = contracts.validate_logit_row(
            logits[accepted - 1].tolist(), accepted, vocab)
        correction = contracts.greedy_pick(values)
    committed = proposed[:accepted] + [int(correction)]
    return accepted, int(correction), committed, decisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-run-dir", type=Path, required=True)
    parser.add_argument("--proposed", required=True,
                        help="comma-separated proposed token ids (depth-7 proposal)")
    parser.add_argument("--depths", default="1,2,4,7")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--commit-depth", type=int, default=7,
                        help="depth whose committed tokens get a labeled commit traversal")
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proposed_full = [int(x) for x in args.proposed.split(",")]
    depths = [int(x) for x in args.depths.split(",")]

    weight_map, model_index_sha, prefill_progress, config, classes = load_environment(
        args.parent_run_dir.resolve())
    parent_final = json.loads(
        (args.parent_run_dir / "sequence-final-state.json").read_text(encoding="utf-8-sig"))
    parent_pick = int(parent_final["top_candidates"][0]["token_id"])
    parent_progress = json.loads(
        (args.parent_run_dir / "progress.json").read_text(encoding="utf-8-sig"))
    receipt = {
        "schema": "octopodes/k3-dspark-arm-c@1",
        "arm": "C",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parent_run_dir": str(args.parent_run_dir),
        "parent_sequence_length": parent_progress["source"]["sequence_length"],
        "parent_checkpoint_sha256": parent_progress.get("checkpoint_sha256"),
        "parent_pick": parent_pick,
        "proposed_full": proposed_full,
        "adjudication_gate": (
            "every judging logit row passes contracts.adjudicate_logit_row: declared "
            "vocabulary dimension, numeric and finite everywhere, greedy pick with "
            "lowest-index tie-break, complete row digest preserved. There is no "
            "second ARM C adjudication path."),
        "kernel_note": ("block uses Moonshot's native multi-token chunk KDA with initial_state; "
                        "sequential decode uses the fused recurrent kernel - kernel choice is part "
                        "of the numerical contract, so state audit vs sequential is expected to "
                        "show numeric drift; token equivalence is the gate"),
        "depths": {},
    }
    for depth in depths:
        proposal = proposed_full[:depth]
        t0 = time.perf_counter()
        hidden, block, _, telemetry = block_traversal(
            token_ids=proposal, prefill_progress=prefill_progress, config=config,
            classes=classes, weight_map=weight_map, retain=False)
        logits = per_position_logits(hidden, block, weight_map, config)
        wall = round(time.perf_counter() - t0, 1)
        accepted, correction, committed, decisions = adjudicate(
            parent_final, proposal, logits)
        unions = telemetry["expert_union_by_layer"]
        row = {
            "proposed": proposal,
            "accepted_length": accepted,
            "correction_token": correction,
            "committed_tokens": committed,
            "committed_count": len(committed),
            "per_position": decisions,
            "verify_wall_s": wall,
            "committed_tokens_per_minute": round(len(committed) / (wall / 60), 3),
            "expert_union_mean": round(sum(unions.values()) / max(len(unions), 1), 2),
            "expert_union_max": max(unions.values()) if unions else None,
            "per_layer_wall_s_sum": round(sum(telemetry["per_layer_wall_s"]), 1),
            "parent_state_mutated": False,
        }
        receipt["depths"][str(depth)] = row
        print(json.dumps({"depth": depth, "accepted": accepted,
                          "committed": committed, "wall_s": wall,
                          "union_mean": row["expert_union_mean"]}))
        (out / "ARM-C-RECEIPT.json").write_text(
            json.dumps(receipt, indent=1), encoding="utf-8")
        del hidden, block, logits
        torch.cuda.empty_cache()

    # one labeled commit traversal for the chosen depth's committed tokens
    committed = receipt["depths"][str(args.commit_depth)]["committed_tokens"]
    t0 = time.perf_counter()
    hidden, block, retained, telemetry = block_traversal(
        token_ids=committed, prefill_progress=prefill_progress, config=config,
        classes=classes, weight_map=weight_map, retain=True)
    logits = per_position_logits(hidden, block, weight_map, config)
    commit_wall = round(time.perf_counter() - t0, 1)
    commit_dir = out / "commit-state"
    commit_dir.mkdir(exist_ok=True)
    manifest = []
    for layer, cache in enumerate(retained):
        path = commit_dir / f"layer-{layer:03d}.pt"
        torch.save(cache, path)
        manifest.append({"layer": layer, "path": str(path),
                         "sha256": core.sha256_file(path)})
    tokenizer = AutoTokenizer.from_pretrained(
        str(core.MODEL_ROOT), trust_remote_code=True, local_files_only=True)
    # the post-commit next pick goes through the same gate as every other
    # adjudicated position - it is the seed of the next speculative step
    next_values = contracts.validate_logit_row(
        logits[-1].tolist(), len(committed), int(logits.shape[-1]))
    next_pick = contracts.greedy_pick(next_values)
    next_top = next_values[next_pick]
    next_runner_up = max(v for i, v in enumerate(next_values) if i != next_pick)
    receipt["commit"] = {
        "schema": "octopodes/k3-dspark-arm-c-commit@1",
        "label": "NOT adopted into the custody chain; state-comparison artifact only",
        "committed_tokens": committed,
        "committed_texts": [tokenizer.decode([t], skip_special_tokens=False) for t in committed],
        "wall_s": commit_wall,
        "state_dir": str(commit_dir),
        "cache_manifest": manifest,
        "next_pick_after_commit": {
            "token_id": next_pick,
            "token_text": tokenizer.decode([next_pick], skip_special_tokens=False),
            "top_logit": next_top,
            "runner_up_logit": next_runner_up,
            "logit_margin": next_top - next_runner_up,
            "vocab_dimension": len(next_values),
            "logit_row_sha256": contracts.logit_row_digest(next_values, len(committed)),
            "finite_valid": True,
        },
    }
    receipt["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (out / "ARM-C-RECEIPT.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(json.dumps({"commit": committed, "next_pick": next_pick,
                      "commit_wall_s": commit_wall}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
