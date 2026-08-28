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
import sys
import time
from pathlib import Path

SLICE = Path(r"C:\Users\octo-operator\TierFloor-Staging\kimi-runtime-slice")
sys.path.insert(0, str(SLICE))

import torch
import torch.nn.functional as F
from transformers import AutoConfig, AutoTokenizer

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


def adjudicate(parent_pick: int, proposed: list[int], logits: torch.Tensor):
    """Greedy acceptance. p_1 judged by the parent's own argmax; p_{i+1} by
    block position i. Correction = target argmax at first rejection."""
    picks = [parent_pick] + logits.argmax(-1).tolist()  # picks[i] judges proposed[i]
    accepted = 0
    decisions = []
    for i, p in enumerate(proposed):
        ok = accepted == i and picks[i] == p
        decisions.append({"position": i, "proposed": p, "target_pick": int(picks[i]),
                          "accepted": bool(ok)})
        if ok:
            accepted += 1
    correction = int(picks[accepted])
    committed = proposed[:accepted] + [correction]
    return accepted, correction, committed, decisions


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
            parent_pick, proposal, logits)
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
    next_logits = logits[-1]
    next_pick = int(next_logits.argmax().item())
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
            "logit_margin": float(
                (next_logits.topk(2).values[0] - next_logits.topk(2).values[1]).item()),
        },
    }
    receipt["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (out / "ARM-C-RECEIPT.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(json.dumps({"commit": committed, "next_pick": next_pick,
                      "commit_wall_s": commit_wall}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
