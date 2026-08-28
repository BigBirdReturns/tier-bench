"""Strict-state K3 block verification with per-position full-state checkpoints.

Two explicit verification modes, per council ruling 2026-08-28
(OCTO-L01-PR-STACK-AND-STRICT-STATE-CLOSURE-001, phase 8):

  FAST_CHUNK_EXPERIMENTAL
    The existing ARM C chunk-style traversal (run_block_verify.py): one
    multi-token chunk-KDA sweep per layer. Fast, token-stream-exact, but the
    block-derived state is kernel-drifted vs the sequential chain (phase 7
    re-audit: 93/93 layers divergent, first at layer 000 kda conv_k [0,0,3]).
    Block-derived state remains NONCANONICAL.

  SEQUENTIAL_WITHIN_LAYER_STRICT
    Load each K3 layer's weights once, then advance the proposed positions
    IN THE SEQUENTIAL RECURRENT ORDER through that resident layer using the
    exact single-position kernels the cached sequential runner uses
    (fused_recurrent_kda / incremental MLA with prior state; K=1 per call).
    The layer-outer/position-inner traversal order is numerically exact: layer
    i's output for position p depends only on (layer i-1's position-p output,
    layer i's state after position p-1), both reproduced exactly. Per-position
    state is round-tripped through CPU between positions, mirroring the
    sequential runner's cpu->cuda state loads.

    Full target state is captured after EVERY proposed position:
    kda + mla layer caches, attn_res residual bank, position, prefix.
    KDA-only checkpointing is insufficient for a free committed continuation.

Checkpoint adoption law: after target acceptance of K positions, checkpoint K
may be adopted ONLY when every component root (content-bound hashing from
contracts.py) matches the sequential baseline at that position. Otherwise the
canonical continuation remains the sequential cached chain.

Economics measured (three custody modes):
  VERIFY_ONLY                        target verifies, no state adopted
  EXPERIMENTAL_BLOCK_STATE_ADOPTION  chunk block state adopted for measurement
                                     only (never canonical)
  STRICT_CANONICAL_COMMIT            per-position state matches the sequential
                                     component roots and may be adopted
                                     without sequential replay

The 2.83x verification result may be called canonical only if
STRICT_CANONICAL_COMMIT passes. Uses only the existing campaign fixture; no
CLAUDE-10 registered item is consumed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

SLICE = Path(r"C:\Users\octo-operator\TierFloor-Staging\kimi-runtime-slice")
sys.path.insert(0, str(SLICE))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from transformers import AutoConfig, AutoTokenizer  # noqa: E402

import run_cached_continuation as rcc  # noqa: E402
import run_full_depth_map as full  # noqa: E402
import run_real_k3_slice as core  # noqa: E402

from k3_dspark_speculative import contracts as contracts_mod  # noqa: E402
from k3_dspark_speculative import run_block_verify as chunk_mode  # noqa: E402

MAX_LAYER = 92


def tensor_root(t: torch.Tensor) -> str:
    enc, _ = contracts_mod._encode_state(t, "t")
    return hashlib.sha256(enc).hexdigest()


def cache_roots(cache: dict[str, torch.Tensor]) -> dict[str, str]:
    return {k: tensor_root(v) for k, v in sorted(cache.items())}


def sum_bytes(node) -> int:
    """Recursively sum numeric 'bytes' fields from runtime receipts."""
    total = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "bytes" and isinstance(v, (int, float)):
                total += int(v)
            else:
                total += sum_bytes(v)
    elif isinstance(node, list):
        for v in node:
            total += sum_bytes(v)
    return total


def load_resident_layer(layer: int, config, classes, weight_map):
    """Load one layer's attention module + support tensors ONCE (resident)."""
    prefix = f"language_model.model.layers.{layer}"
    is_linear = True if layer == 0 else bool(config.is_kda_layer(layer))
    if not is_linear and getattr(config, "_attn_implementation", None) is None:
        config._attn_implementation = "eager"
    attention_class = classes["KimiDeltaAttention" if is_linear else "KimiMLAAttention"]
    with torch.device("meta"):
        attention = attention_class(config, layer)
    attention_receipt = core.load_module(
        attention, f"{prefix}.self_attn", weight_map, device=core.DEVICE)
    support, support_receipt = core.load_layer_support(layer, weight_map)
    mlp = None
    mlp_receipt = None
    if layer == 0:
        with torch.device("meta"):
            mlp = classes["KimiMLP"](config)
        mlp_receipt = core.load_module(
            mlp, f"{prefix}.mlp", weight_map, device=core.DEVICE)
    return {
        "layer": layer,
        "is_linear": is_linear,
        "prefix": prefix,
        "attention": attention,
        "support": support,
        "mlp": mlp,
        "load_bytes": sum_bytes(attention_receipt) + sum_bytes(support_receipt)
        + sum_bytes(mlp_receipt),
    }


def strict_position_forward(res, hidden, block, prior_cache, config):
    """Exact mirror of the sequential runner's forward_one for one position.

    hidden: [1, 1, width]; block: [1, L, width] (this position's residual
    bank); prior_cache: this layer's state after the previous position
    (CPU tensors). Returns (router_input, prefix_sum, block, next_cache_cpu).
    """
    prefix = res["prefix"]
    support = res["support"]
    epsilon = float(config.rms_norm_eps)
    tokens = hidden.shape[0] * hidden.shape[1]
    width = hidden.shape[-1]
    prefix_sum = hidden
    if block.shape[1] > 0:
        mixed = core.apply_attn_residual(
            prefix_sum.reshape(tokens, width), block,
            support[f"{prefix}.self_attention_res_proj.weight"],
            support[f"{prefix}.self_attention_res_norm.weight"],
            epsilon,
        ).reshape_as(hidden)
    else:
        mixed = prefix_sum
    if res["layer"] % int(config.attn_res_block_size) == 0:
        block = torch.cat(
            (block, prefix_sum.reshape(tokens, width).unsqueeze(1)), dim=1)
        prefix_sum = None
    normalized = core.rms_norm(
        mixed, support[f"{prefix}.input_layernorm.weight"], epsilon)
    if res["is_linear"]:
        attention_output, next_cache = core.kda_chunk_beta_compat_forward_retained(
            res["attention"], normalized, prior_cache)
    else:
        attention_output, next_cache = core.mla_forward_retained(
            res["attention"], normalized, prior_cache)
    prefix_sum = attention_output if prefix_sum is None else prefix_sum + attention_output
    moe_input = core.apply_attn_residual(
        prefix_sum.reshape(tokens, width), block,
        support[f"{prefix}.mlp_res_proj.weight"],
        support[f"{prefix}.mlp_res_norm.weight"],
        epsilon,
    ).reshape_as(hidden)
    router_input = core.rms_norm(
        moe_input, support[f"{prefix}.post_attention_layernorm.weight"], epsilon)
    next_cache_cpu = {k: v.detach().to("cpu") for k, v in next_cache.items()}
    return router_input, prefix_sum, block, next_cache_cpu


def strict_traversal(
    *,
    token_ids: list[int],
    prefill_progress: dict,
    config,
    classes,
    weight_map,
    state_dir: Path,
    parent_prefix_length: int,
    max_layer: int = MAX_LAYER,
):
    """SEQUENTIAL_WITHIN_LAYER_STRICT: one weight residency per layer, exact
    single-position recurrent order inside it, full per-position state capture.
    """
    k = len(token_ids)
    width = None
    embeddings, embed_receipt = core.load_embeddings(token_ids, weight_map)
    width = embeddings.shape[-1]
    hidden = [embeddings[:, p:p + 1, :].contiguous() for p in range(k)]
    bank = [embeddings.new_zeros((1, 0, width)) for _ in range(k)]
    # per-position layer-cache store (CPU), evolving as layers complete
    for p in range(k):
        (state_dir / f"position-{p + 1:02d}").mkdir(parents=True, exist_ok=True)
    telemetry = {
        "per_layer_wall_s": [],
        "per_layer_load_bytes": [],
        "expert_union_by_layer": {},
        "experts_per_position": {},
        "embed": embed_receipt,
    }
    # crash/kill resume: the inter-layer hidden/bank tensors are tiny, so the
    # traversal checkpoints them after every layer and restarts continue from
    # the first incomplete layer (per-position layer states are already on
    # disk for completed layers).
    ckpt_path = state_dir / "traversal-checkpoint.pt"
    start_layer = 0
    if ckpt_path.is_file():
        ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        if ck.get("token_ids") == list(token_ids) and ck["layer_done"] <= max_layer:
            start_layer = int(ck["layer_done"]) + 1
            hidden = [t.to(embeddings.device) for t in ck["hidden"]]
            bank = [t.to(embeddings.device) for t in ck["bank"]]
            telemetry.update(ck["telemetry"])
            print(json.dumps({"resumed_from_layer": start_layer}), flush=True)
    for layer in range(start_layer, max_layer + 1):
        started = time.perf_counter()
        parent_cache = rcc.load_prefill_layer_cache(prefill_progress, layer)
        res = load_resident_layer(layer, config, classes, weight_map)
        router_inputs = []
        prefix_sums = []
        cache = parent_cache  # state after position p-1 (CPU tensors)
        for p in range(k):
            router_input, prefix_sum, bank[p], cache = strict_position_forward(
                res, hidden[p], bank[p], cache, config)
            router_inputs.append(router_input)
            prefix_sums.append(prefix_sum)
            torch.save(
                {
                    "schema": "octopodes/k3-strict-position-layer-state@1",
                    "layer": layer,
                    "kind": "KDA" if res["is_linear"] else "MLA",
                    "position": p + 1,
                    "absolute_position": parent_prefix_length + p + 1,
                    "tensors": cache,
                },
                state_dir / f"position-{p + 1:02d}" / f"layer-{layer:03d}.pt",
            )
        # MLP / MoE per position with resident support
        if layer == 0:
            for p in range(k):
                dense_out = res["mlp"](router_inputs[p])
                hidden[p] = prefix_sums[p] + dense_out
        else:
            gate_prefix = f"{res['prefix']}.block_sparse_moe.gate"
            union: set[int] = set()
            for p in range(k):
                indices, weights, _ = core.route(
                    router_inputs[p],
                    res["support"][f"{gate_prefix}.weight"],
                    res["support"][f"{gate_prefix}.e_score_correction_bias"],
                )
                moe_out, moe_receipt = core.execute_streamed_moe_dual(
                    layer=layer,
                    router_input=router_inputs[p],
                    topk_indices=indices,
                    topk_weights=weights,
                    support=res["support"],
                    weight_map=weight_map,
                    config=config,
                    missing_policy="exact",
                    execution_mode="sync",
                )
                hidden[p] = prefix_sums[p] + moe_out
                union.update(int(x) for x in indices.reshape(-1).tolist())
                telemetry["per_layer_load_bytes"].append(sum_bytes(moe_receipt))
            telemetry["expert_union_by_layer"][layer] = len(union)
        telemetry["per_layer_load_bytes"].append(res["load_bytes"])
        telemetry["per_layer_wall_s"].append(round(time.perf_counter() - started, 2))
        del res
        torch.cuda.empty_cache()
        torch.save(
            {
                "token_ids": list(token_ids),
                "layer_done": layer,
                "hidden": [t.detach().to("cpu") for t in hidden],
                "bank": [t.detach().to("cpu") for t in bank],
                "telemetry": {k2: v for k2, v in telemetry.items()},
            },
            ckpt_path,
        )
        print(json.dumps({"layer_done": layer,
                          "wall_s": telemetry["per_layer_wall_s"][-1]}), flush=True)
    # per-position residual banks + final hiddens
    for p in range(k):
        torch.save(
            {
                "schema": "octopodes/k3-strict-position-bank@1",
                "position": p + 1,
                "absolute_position": parent_prefix_length + p + 1,
                "attn_res_bank": bank[p].detach().to("cpu"),
                "final_hidden": hidden[p].detach().to("cpu"),
            },
            state_dir / f"position-{p + 1:02d}" / "attn-res-bank.pt",
        )
    hidden_all = torch.cat(hidden, dim=1)
    bank_all = torch.cat(bank, dim=0)
    return hidden_all, bank_all, telemetry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-run-dir", type=Path, required=True)
    parser.add_argument("--proposed", required=True)
    parser.add_argument("--mode", choices=["SEQUENTIAL_WITHIN_LAYER_STRICT",
                                           "FAST_CHUNK_EXPERIMENTAL"],
                        default="SEQUENTIAL_WITHIN_LAYER_STRICT")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-layer", type=int, default=MAX_LAYER,
                        help="bounded smoke: stop after this layer (skips finalize/adjudication unless 92)")
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proposed = [int(x) for x in args.proposed.split(",")]

    weight_map, model_index_sha, prefill_progress, config, classes = (
        chunk_mode.load_environment(args.parent_run_dir.resolve()))
    parent_final = json.loads(
        (args.parent_run_dir / "sequence-final-state.json").read_text(encoding="utf-8-sig"))
    parent_pick = int(parent_final["top_candidates"][0]["token_id"])
    parent_progress = json.loads(
        (args.parent_run_dir / "progress.json").read_text(encoding="utf-8-sig"))
    parent_len = int(parent_progress["source"]["sequence_length"])

    receipt = {
        "schema": "octopodes/k3-dspark-strict-block-verify@1",
        "mode": args.mode,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parent_run_dir": str(args.parent_run_dir),
        "parent_sequence_length": parent_len,
        "parent_checkpoint_sha256": parent_progress.get("checkpoint_sha256"),
        "parent_pick": parent_pick,
        "model_index_sha256": model_index_sha,
        "proposed": proposed,
        "kernel_note": (
            "SEQUENTIAL_WITHIN_LAYER_STRICT advances positions one at a time "
            "inside each resident layer with the exact cached-sequential "
            "kernels (fused_recurrent_kda / incremental MLA, K=1 per call, "
            "CPU state round-trip between positions); layer-outer order is "
            "numerically exact vs position-outer."),
    }
    t0 = time.perf_counter()
    if args.mode == "SEQUENTIAL_WITHIN_LAYER_STRICT":
        state_dir = out / "strict-state"
        hidden, bank, telemetry = strict_traversal(
            token_ids=proposed, prefill_progress=prefill_progress,
            config=config, classes=classes, weight_map=weight_map,
            state_dir=state_dir, parent_prefix_length=parent_len,
            max_layer=args.max_layer)
        receipt["state_dir"] = str(state_dir)
        if args.max_layer != MAX_LAYER:
            receipt["bounded_smoke_max_layer"] = args.max_layer
            receipt["verify_wall_s"] = round(time.perf_counter() - t0, 1)
            receipt["per_layer_wall_s_sum"] = round(sum(telemetry["per_layer_wall_s"]), 1)
            receipt["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            (out / "STRICT-VERIFY-RECEIPT.json").write_text(
                json.dumps(receipt, indent=1), encoding="utf-8")
            print(json.dumps({"mode": args.mode, "bounded_smoke": True,
                              "max_layer": args.max_layer,
                              "wall_s": receipt["verify_wall_s"]}))
            return 0
    else:
        hidden, bank, retained, telemetry = chunk_mode.block_traversal(
            token_ids=proposed, prefill_progress=prefill_progress,
            config=config, classes=classes, weight_map=weight_map, retain=True)
        state_dir = out / "chunk-state"
        state_dir.mkdir(exist_ok=True)
        for layer, cache in enumerate(retained):
            torch.save(cache, state_dir / f"layer-{layer:03d}.pt")
        receipt["state_dir"] = str(state_dir)
    logits = chunk_mode.per_position_logits(hidden, bank, weight_map, config)
    verify_wall = round(time.perf_counter() - t0, 1)

    accepted, correction, committed, decisions = chunk_mode.adjudicate(
        parent_pick, proposed, logits)
    tokenizer = AutoTokenizer.from_pretrained(
        str(core.MODEL_ROOT), trust_remote_code=True, local_files_only=True)
    torch.save(logits.detach().to("cpu"),
               out / "per-position-logits.pt")
    unions = telemetry["expert_union_by_layer"]
    receipt.update({
        "accepted_length": accepted,
        "correction_token": correction,
        "correction_text": tokenizer.decode([correction], skip_special_tokens=False),
        "committed_tokens": committed,
        "per_position": decisions,
        "verify_wall_s": verify_wall,
        "per_layer_wall_s_sum": round(sum(telemetry["per_layer_wall_s"]), 1),
        "target_weight_bytes_read": sum(telemetry.get("per_layer_load_bytes", [])),
        "target_traversals": 1,
        "expert_union_mean": round(sum(unions.values()) / max(len(unions), 1), 2),
        "expert_union_max": max(unions.values()) if unions else None,
        "parent_state_mutated": False,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    (out / "STRICT-VERIFY-RECEIPT.json").write_text(
        json.dumps(receipt, indent=1), encoding="utf-8")
    print(json.dumps({"mode": args.mode, "accepted": accepted,
                      "committed": committed, "wall_s": verify_wall}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
