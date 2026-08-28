"""Build a sealed sequential-baseline manifest for the strict-state gate.

Reads the ARM A sequential generations (private estate custody), binds every
per-layer cache file, the traversal checkpoint (attn_res bank + final
hidden), and the sealed logits by SHA-256, and derives the manifest aggregate
root the gate pins with --expect-baseline-root.

  python build_sequential_baseline_manifest.py \
      --arm-a-root <...>/arm-a \
      --positions 1:12,2:13 \
      --parent-run-dir <parent cached run dir> \
      --out BASELINE-MANIFEST.json
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path

if __package__:
    from .strict_baseline_gate import MANIFEST_SCHEMA, manifest_aggregate_root, sha256_file
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from k3_dspark_speculative.strict_baseline_gate import (  # type: ignore
        MANIFEST_SCHEMA, manifest_aggregate_root, sha256_file)

LAYERS = 93


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-a-root", type=Path, required=True)
    parser.add_argument("--positions", required=True,
                        help="comma list position:generation, e.g. 1:12,2:13")
    parser.add_argument("--parent-run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    progress = json.loads(
        (args.parent_run_dir / "progress.json").read_text(encoding="utf-8-sig"))
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "model_index_sha256": progress["source"]["model_index_sha256"],
        "parent_checkpoint_sha256": progress["checkpoint_sha256"],
        "parent_sequence_length": progress["attention_cache"]["sequence_length"],
        "positions": {},
    }
    for pair in args.positions.split(","):
        pos_s, gen_s = pair.split(":")
        pos, gen = int(pos_s), int(gen_s)
        cache_dirs = glob.glob(str(
            args.arm_a_root / f"generation-{gen:03d}" / "*" / "attention-cache"
            / f"generation-{gen:03d}"))
        if len(cache_dirs) != 1:
            raise SystemExit(f"generation {gen}: expected one cache dir, "
                             f"found {cache_dirs}")
        cache_dir = Path(cache_dirs[0])
        run_dir = cache_dir.parents[1]
        layer_files = {}
        for i in range(LAYERS):
            name = f"layer-{i:03d}.pt"
            layer_files[name] = sha256_file(cache_dir / name)
        ckpt = run_dir / "checkpoint-latest.pt"
        logits = run_dir / "sequence-logits.pt"
        # bind the position semantics from the sealed layer-0 cache record
        import torch  # noqa: PLC0415
        rec = torch.load(cache_dir / "layer-000.pt", map_location="cpu",
                         weights_only=False)
        manifest["positions"][str(pos)] = {
            "generation": gen,
            "sequence_length": rec["sequence_length"],
            "appended_token": rec["appended_token_id"],
            "layer_cache_dir": str(cache_dir),
            "layer_files": layer_files,
            "checkpoint_file": str(ckpt),
            "checkpoint_sha256": sha256_file(ckpt),
            "logits_file": str(logits),
            "logits_sha256": sha256_file(logits),
        }
        expected_len = manifest["parent_sequence_length"] + pos
        if rec["sequence_length"] != expected_len:
            raise SystemExit(
                f"position {pos}: baseline sequence length {rec['sequence_length']} "
                f"!= parent + position = {expected_len}")
    manifest["aggregate_root_sha256"] = manifest_aggregate_root(manifest)
    args.out.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({"aggregate_root_sha256": manifest["aggregate_root_sha256"],
                      "positions": sorted(manifest["positions"])}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
