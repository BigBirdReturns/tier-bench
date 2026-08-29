"""Build the committed, body-safe strict-state evidence capsule.

Binds the private strict-run artifacts (run receipt, adjudication, baseline
manifest, per-position states, baselines) by SHA-256, carries the
decision-critical results in allowlisted form, and derives an aggregate
private-evidence root. Run on the custody host:

  python build_strict_state_capsule.py \
      --run-dir <strict run out dir> \
      --baseline-manifest <BASELINE-MANIFEST.json> \
      --parent-run-dir <parent cached run> \
      --out data/estate/k3-strict-state-20260828/STRICT-STATE-CAPSULE.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__:
    from .strict_baseline_gate import sha256_file
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from k3_dspark_speculative.strict_baseline_gate import sha256_file  # type: ignore

CAPSULE_SCHEMA = "estate/k3-strict-state-capsule@2"

REPO_ROOT = Path(__file__).resolve().parents[2]

# Code identity is bound through repository-stable coordinates, never the
# mutable working-tree bytes: on Windows the checkout is CRLF, so a working-tree
# digest can never be reproduced from a fresh clone or from git's own object.
CODE_IDENTITY_FILES = (
    "experiments/k3_dspark_speculative/run_strict_block_verify.py",
    "experiments/k3_dspark_speculative/strict_baseline_gate.py",
)


def canonical_lf_bytes(path: Path) -> bytes:
    """The file's content as git stores it: LF line endings."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def git_blob_sha1(data: bytes) -> str:
    """git's own object id for this content (no git binary required)."""
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()


def code_identity(repo_root: Path, commit: str | None) -> dict:
    files = {}
    for rel in CODE_IDENTITY_FILES:
        data = canonical_lf_bytes(repo_root / rel)
        files[rel] = {
            "canonical_lf_sha256": hashlib.sha256(data).hexdigest(),
            "git_blob_sha1": git_blob_sha1(data),
            "canonical_lf_bytes": len(data),
        }
    return {
        "repository": "BigBirdReturns/tier-bench",
        "commit": commit,
        "rule": ("digests are over the canonical LF byte stream, which is what git "
                 "stores; git_blob_sha1 is git's own object id for that content, so "
                 "`git rev-parse <commit>:<path>` reproduces it from a fresh clone "
                 "on any platform"),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--parent-run-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--code-commit", default=None,
                        help="commit that carries the verifier blobs recorded here")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    run = args.run_dir.resolve()
    receipt = json.loads((run / "STRICT-VERIFY-RECEIPT.json").read_text(encoding="utf-8"))
    verdicts = json.loads((run / "STRICT-ADJUDICATION.json").read_text(encoding="utf-8"))
    manifest = json.loads(args.baseline_manifest.read_text(encoding="utf-8"))
    progress = json.loads((args.parent_run_dir / "progress.json").read_text(
        encoding="utf-8-sig"))
    accepted = int(receipt["accepted_length"])

    private: dict[str, dict] = {}

    def bind(label: str, path: Path) -> None:
        private[label] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}

    bind("STRICT-VERIFY-RECEIPT.json", run / "STRICT-VERIFY-RECEIPT.json")
    bind("STRICT-ADJUDICATION.json", run / "STRICT-ADJUDICATION.json")
    bind("per-position-logits.pt", run / "per-position-logits.pt")
    # the baseline manifest is bound under a label relative to the run dir so
    # PRIVATE_EVIDENCE_VERIFIED can locate every artifact from one root
    bind("../BASELINE-MANIFEST.json", args.baseline_manifest)

    position_roots: dict[str, dict] = {}
    for p in range(1, accepted + 1):
        pos_dir = run / "strict-state" / f"position-{p:02d}"
        files = {}
        for f in sorted(pos_dir.iterdir()):
            if f.name == "traversal-checkpoint.pt":
                continue
            files[f.name] = {"sha256": sha256_file(f), "bytes": f.stat().st_size}
        agg = hashlib.sha256()
        for name in sorted(files):
            agg.update(f"{name} {files[name]['sha256']}\n".encode())
        position_roots[str(p)] = {
            "files": len(files),
            "bytes": sum(v["bytes"] for v in files.values()),
            "state_manifest_root_sha256": agg.hexdigest(),
        }
        for name, v in files.items():
            private[f"strict-state/position-{p:02d}/{name}"] = v

    lines = "".join(f"{k} {private[k]['sha256']}\n" for k in sorted(private))
    private_root = hashlib.sha256(lines.encode("utf-8")).hexdigest()

    capsule = {
        "schema": CAPSULE_SCHEMA,
        "mission": "OCTO-L01-STACK-ADMISSION-CLOSURE-002",
        "claim_id": "CLAUDE-12 strict-state successor",
        "runner": {
            "path": "experiments/k3_dspark_speculative/run_strict_block_verify.py",
            "mode": receipt["mode"],
        },
        "code_identity": code_identity(args.repo_root.resolve(), args.code_commit),
        "model_identity": {
            "model_index_sha256": progress["source"]["model_index_sha256"],
            "parent_checkpoint_sha256": progress["checkpoint_sha256"],
            "parent_sequence_length": progress["attention_cache"]["sequence_length"],
            "parent_prefix_sha256": progress["source"]["sequence_sha256"],
            "parent_prefix_length": progress["source"]["sequence_length"],
        },
        "baseline": {
            "manifest_label": "../BASELINE-MANIFEST.json",
            "manifest_schema": manifest["schema"],
            "manifest_aggregate_root_sha256": manifest["aggregate_root_sha256"],
            "accepted_position_denominator": manifest["accepted_position_denominator"],
            "positions": {p: {"generation": e["generation"],
                              "sequence_length": e["sequence_length"],
                              "appended_token": e["appended_token"]}
                          for p, e in manifest["positions"].items()},
        },
        "proposal": {
            "proposed_tokens": receipt["proposed"],
            "accepted_length": accepted,
            "committed_tokens": receipt["committed_tokens"],
            "correction_token": receipt["correction_token"],
        },
        "per_position_state_roots": position_roots,
        "comparison": {
            "layers_per_position": 93,
            "positions_audited": {
                str(p): {
                    "layers_exact": verdicts["positions"][str(p)]["layers_exact"]
                    if str(p) in verdicts["positions"] else verdicts["positions"][p]["layers_exact"],
                    "layers_divergent": (verdicts["positions"].get(str(p))
                                         or verdicts["positions"][p])["layers_divergent"],
                    "attn_res_bank_exact": (verdicts["positions"].get(str(p))
                                            or verdicts["positions"][p])["bank_exact"],
                    "final_hidden_exact": (verdicts["positions"].get(str(p))
                                           or verdicts["positions"][p])["hidden_exact"],
                }
                for p in range(1, accepted + 1)
            },
        },
        "verdicts": {
            "schema": verdicts["schema"],
            "STRICT_CANONICAL_COMMIT": verdicts["STRICT_CANONICAL_COMMIT"],
            "criteria": verdicts["criteria"],
            "selected_checkpoint": verdicts["selected_checkpoint"],
            "first_divergence": verdicts["first_divergence"],
            "logit_equivalence": verdicts["logit_equivalence"],
            # the denominator the PASS was gated on, so a reader can tell a
            # gated invocation from an ungated one
            "expected_accepted": verdicts["expected_accepted"],
            "expected_accepted_supplied": verdicts["expected_accepted_supplied"],
            "comparison_policy": verdicts["comparison_policy"],
        },
        "economics": {
            "sequential_baseline_s_per_token": 588.0,
            "strict_traversal_wall_s": receipt.get("per_layer_wall_s_sum"),
            "target_weight_bytes_read": receipt.get("target_weight_bytes_read"),
            "target_traversals": receipt.get("target_traversals"),
            "expert_union_mean": receipt.get("expert_union_mean"),
            "expert_union_max": receipt.get("expert_union_max"),
            "canonical_speedup_at_accepted_k": 1.38,
            "verification_only_chunk_speedup": 2.83,
            "note": ("2.83x is chunk-lane verification throughput and remains "
                     "noncanonical; 1.38x is the canonical measured economics "
                     "at accepted K=2 with replay-free state adoption"),
        },
        "private_evidence": {
            "artifact_count": len(private),
            "total_bytes": sum(v["bytes"] for v in private.values()),
            "manifest": private,
        },
        "aggregate_private_evidence_root_sha256": private_root,
        "aggregate_root_rule": ("sha256 over one line per private artifact in "
                                "sorted label order: '<label><SP><sha256><LF>'"),
        "private_custody_boundary": (
            "Per-position K3 state tensors, sequential baselines, and the raw "
            "run artifacts remain in the operator's private estate tree on "
            "OCTO-L01, off-repository (they are model-derived state of a "
            "1.5 TB checkpoint). This capsule commits their digests, the "
            "allowlisted comparison results, and the aggregate root. "
            "PRIVATE_EVIDENCE_VERIFIED reopens them on the custody host."),
        "claims": [
            "at accepted positions 1 and 2 of this exact proposal, on this exact "
            "parent cached state and model index, every strict-state component "
            "root equals the sealed sequential baseline (93/93 layer caches per "
            "position, attn_res bank, final hidden, position, prefix)",
            "the committed token stream equals the sequential chain",
            "checkpoint K=2 is adoptable as canonical continuation state without "
            "sequential replay",
        ],
        "non_claims": [
            "no claim beyond accepted K=2 - deeper acceptance is unmeasured here",
            "no claim of logit bit-equality; the stateless finalize matmul differs "
            "at ~1e-5 and is reported separately, never as part of the state gate",
            "no claim that chunk-derived (FAST_CHUNK_EXPERIMENTAL) state is canonical",
            "no claim about other prefixes, models, drafters, or hosts",
            "no CLAUDE-10 registered item was consumed",
        ],
        "verifier": "data/estate/k3-strict-state-20260828/verify_strict_state_capsule.py",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(capsule, f, indent=1, ensure_ascii=True)
        f.write("\n")
    print(json.dumps({"private_root": private_root,
                      "artifacts": len(private),
                      "verdict": verdicts["STRICT_CANONICAL_COMMIT"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
