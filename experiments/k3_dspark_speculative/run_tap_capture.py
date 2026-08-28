"""First K3 tap capture: one cached continuation step with the tap adapter enabled.

Runs run_cached_continuation IN-PROCESS with a TapSession installed, capturing
the declared boundary taps during the single-token target traversal, then
writes the hashed capture bundle next to the run. The target result is
unchanged by construction (adapter inertness: tests, commit 24950cb) and the
run remains a normal custody-chain generation.

Two K3 tap conventions exist (interface-resolution.md R1): "pre" captures the
AttnRes running-prefix wire (vLLM's prefix_only serving default), "mixture"
computes the pre-norm AttnRes mixture over bank+prefix with the consumer
layer's res weights (VLLM_KIMI_K3_AUX_ATTN_RES_STREAM=1; the K3 capture
docstring names this the DFlash training target). Which one THIS drafter
checkpoint was trained on is the remaining binary - ARM B compares both.
Every bundle records its convention.

Example (generation 11, from the gen-10 run):
  python run_tap_capture.py \
    --prefill-run-dir D:\\kimilab\\estate\\k3-cached-chain-extension-20260827\\generation-010\\20260828T033907Z \
    --token-id 10853 \
    --out-root D:\\kimilab\\estate\\k3-dspark-morning-launch-20260828\\tap-capture-gen-011 \
    --layers 2,23,47,71,89 --location pre
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SLICE = Path(r"C:\Users\octo-operator\TierFloor-Staging\kimi-runtime-slice")
sys.path.insert(0, str(SLICE))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from k3_dspark_speculative.tap_adapter import TapSession, TapSpec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefill-run-dir", required=True)
    parser.add_argument("--token-id", type=int, required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--layers", default="2,23,47,71,89")
    parser.add_argument("--location", choices=("pre", "post", "mixture"), default="pre",
                        help="pre = AttnRes running prefix entering the layer (vLLM prefix_only default); "
                             "mixture = pre-norm AttnRes mixture over bank+prefix with the consumer "
                             "layer's res weights (VLLM_KIMI_K3_AUX_ATTN_RES_STREAM=1 convention)")
    args = parser.parse_args()

    import run_cached_continuation as rcc
    import run_real_k3_slice as core

    def k3_mixture_fn(layer: int, prefix, call_kwargs: dict):
        """The attn_res_stream tap: apply_attn_residual with the CONSUMER
        layer's res weights over (bank ++ prefix), pre-norm, no output norm -
        the same math the runner itself applies at each layer entry."""
        bank = call_kwargs["block_residual"]
        if bank is None or bank.shape[1] == 0:
            return prefix.detach()
        names = [
            f"language_model.model.layers.{layer}.self_attention_res_proj.weight",
            f"language_model.model.layers.{layer}.self_attention_res_norm.weight",
        ]
        tensors, _ = core.load_named_tensors(
            names, call_kwargs["weight_map"], device=prefix.device
        )
        tokens = prefix.shape[0] * prefix.shape[1]
        width = prefix.shape[-1]
        mixed = core.apply_attn_residual(
            prefix.detach().reshape(tokens, width),
            bank.detach(),
            tensors[names[0]],
            tensors[names[1]],
            float(call_kwargs["config"].rms_norm_eps),
        )
        return mixed.reshape_as(prefix)

    layers = [int(x) for x in args.layers.split(",")]
    convention = {"pre": "prefix_only (vLLM serving default)",
                  "post": "post-layer wire",
                  "mixture": "attn_res_stream (documented DFlash training target)"}[args.location]
    specs = tuple(
        TapSpec(layer=l, location=args.location,
                declared_as=f"dspark target_layer_id {l} (zero-based boundary; convention: {convention})")
        for l in layers
    )
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    active = out_root / "active.json"

    session = TapSession(specs=specs, enabled=True,
                         mixture_fn=k3_mixture_fn if args.location == "mixture" else None).install(rcc)
    try:
        sys.argv = [
            "run_cached_continuation.py",
            "--prefill-run-dir", args.prefill_run_dir,
            "--token-id", str(args.token_id),
            "--out-root", str(out_root),
            "--active-path", str(active),
        ]
        rc = rcc.main() if hasattr(rcc, "main") else 1
    finally:
        session.uninstall()

    bundle = session.receipt()
    bundle["stream_identity"] = convention
    bundle["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    bundle["run_active_path"] = str(active)
    bundle_path = out_root / "tap-bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=1), encoding="utf-8")
    print(json.dumps({"rc": rc, "captures": len(bundle["captures"]), "bundle": str(bundle_path)}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
