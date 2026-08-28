"""First K3 tap capture: one cached continuation step with the tap adapter enabled.

Runs run_cached_continuation IN-PROCESS with a TapSession installed, capturing
the declared boundary taps during the single-token target traversal, then
writes the hashed capture bundle next to the run. The target result is
unchanged by construction (adapter inertness: tests, commit 24950cb) and the
run remains a normal custody-chain generation.

Until interface-resolution R1 (K3 stream identity vs vLLM recombined stream)
is closed, every bundle is labeled stream_identity_unconfirmed and MUST NOT be
fed to the drafter for any claim beyond ARM B interface exploration.

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
    parser.add_argument("--location", choices=("pre", "post"), default="pre",
                        help="pre = residual stream entering the layer (vLLM boundary semantics, subject to R1)")
    args = parser.parse_args()

    import run_cached_continuation as rcc

    layers = [int(x) for x in args.layers.split(",")]
    specs = tuple(
        TapSpec(layer=l, location=args.location,
                declared_as=f"dspark target_layer_id {l} (zero-based boundary; stream_identity_unconfirmed)")
        for l in layers
    )
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    active = out_root / "active.json"

    session = TapSession(specs=specs, enabled=True).install(rcc)
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
    bundle["stream_identity"] = "stream_identity_unconfirmed (interface-resolution R1 open)"
    bundle["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    bundle["run_active_path"] = str(active)
    bundle_path = out_root / "tap-bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=1), encoding="utf-8")
    print(json.dumps({"rc": rc, "captures": len(bundle["captures"]), "bundle": str(bundle_path)}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
