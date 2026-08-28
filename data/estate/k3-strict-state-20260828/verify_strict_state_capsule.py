"""Deterministic verifier for the strict-state evidence capsule.

Zero-network. Two levels:

  CAPSULE_VERIFIED
      (default) Reconstructs and validates the committed body-safe capsule:
      required fields, per-position state-manifest roots recompute from the
      committed private manifest, the aggregate private-evidence root
      recomputes under the declared rule, the comparison table is internally
      consistent (93/93 layers exact, no divergence, bank and hidden exact at
      every audited position), the verdict criteria all hold, and the
      economics language keeps 2.83x noncanonical.

  PRIVATE_EVIDENCE_VERIFIED
      (--private-root <dir>) Rehashes every authorized private artifact,
      PARSES the run receipt and adjudication, and independently reconstructs
      the strict-state verdict from their contents. Digest-correct private
      evidence whose semantics contradict the capsule is REFUSED.

Exit 0 = verified at the requested level; 1 = any check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CAPSULE = HERE / "STRICT-STATE-CAPSULE.json"

REQUIRED = [
    "schema", "mission", "runner", "model_identity", "baseline", "proposal",
    "per_position_state_roots", "comparison", "verdicts", "economics",
    "private_evidence", "aggregate_private_evidence_root_sha256",
    "aggregate_root_rule", "private_custody_boundary", "claims", "non_claims",
]


class VerificationFailure(Exception):
    pass


def refuse(msg: str) -> None:
    raise VerificationFailure(msg)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_capsule(capsule: dict) -> None:
    for field in REQUIRED:
        if field not in capsule:
            refuse(f"capsule missing required field {field!r}")
    if capsule["schema"] != "estate/k3-strict-state-capsule@1":
        refuse(f"unexpected schema {capsule['schema']!r}")

    manifest = capsule["private_evidence"]["manifest"]
    if len(manifest) != capsule["private_evidence"]["artifact_count"]:
        refuse("private artifact count does not match the manifest length")
    for label, entry in manifest.items():
        if len(entry.get("sha256", "")) != 64:
            refuse(f"private artifact {label!r} lacks a sha256 digest")

    lines = "".join(f"{k} {manifest[k]['sha256']}\n" for k in sorted(manifest))
    root = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    if root != capsule["aggregate_private_evidence_root_sha256"]:
        refuse(f"aggregate private-evidence root does not recompute (got {root})")

    accepted = capsule["proposal"]["accepted_length"]
    if accepted < 1:
        refuse("capsule claims no accepted positions")
    if len(capsule["proposal"]["committed_tokens"]) != accepted + 1:
        refuse("committed tokens must be the accepted prefix plus one correction")

    # per-position state-manifest roots recompute from the committed manifest
    for p in range(1, accepted + 1):
        prefix = f"strict-state/position-{p:02d}/"
        files = {k[len(prefix):]: v["sha256"] for k, v in manifest.items()
                 if k.startswith(prefix)}
        if not files:
            refuse(f"no private artifacts committed for position {p}")
        agg = hashlib.sha256()
        for name in sorted(files):
            agg.update(f"{name} {files[name]}\n".encode())
        declared = capsule["per_position_state_roots"][str(p)]
        if agg.hexdigest() != declared["state_manifest_root_sha256"]:
            refuse(f"position {p}: state-manifest root does not recompute")
        if declared["files"] != len(files):
            refuse(f"position {p}: file count disagrees with the manifest")
        expected_files = {f"layer-{i:03d}.pt" for i in range(93)} | {"attn-res-bank.pt"}
        if set(files) != expected_files:
            refuse(f"position {p}: unbound or missing state files")

    comp = capsule["comparison"]
    if comp["layers_per_position"] != 93:
        refuse("layer denominator is not 93")
    for p in range(1, accepted + 1):
        row = comp["positions_audited"][str(p)]
        if row["layers_exact"] != 93 or row["layers_divergent"]:
            refuse(f"position {p}: layer comparison is not 93/93 exact")
        if not row["attn_res_bank_exact"] or not row["final_hidden_exact"]:
            refuse(f"position {p}: attn_res bank or final hidden not exact")

    verdicts = capsule["verdicts"]
    if verdicts["STRICT_CANONICAL_COMMIT"] == "PASS":
        if not all(verdicts["criteria"].values()):
            refuse("PASS claimed while a gate criterion is false")
        if verdicts["first_divergence"] is not None:
            refuse("PASS claimed with a recorded divergence")
        if verdicts["selected_checkpoint"] != accepted:
            refuse("adopted checkpoint is not the accepted boundary")

    econ = capsule["economics"]
    if econ.get("verification_only_chunk_speedup") == econ.get(
            "canonical_speedup_at_accepted_k"):
        refuse("verification-only and canonical economics must stay distinct")
    if "noncanonical" not in econ.get("note", ""):
        refuse("economics note must keep the verification-only figure noncanonical")
    if not capsule["claims"] or not capsule["non_claims"]:
        refuse("capsule must state both claims and non-claims")


def verify_private_evidence(capsule: dict, root_dir: Path) -> None:
    manifest = capsule["private_evidence"]["manifest"]
    missing, mismatched = [], []
    for label, entry in sorted(manifest.items()):
        p = root_dir / label
        if not p.is_file():
            missing.append(label)
        elif sha256_file(p) != entry["sha256"]:
            mismatched.append(label)
    if missing or mismatched:
        refuse(f"private evidence: missing={missing[:4]} mismatched={mismatched[:4]}")

    # semantic reconstruction: the private artifacts must SAY what the capsule claims
    receipt = json.loads((root_dir / "STRICT-VERIFY-RECEIPT.json").read_text(
        encoding="utf-8"))
    verdicts = json.loads((root_dir / "STRICT-ADJUDICATION.json").read_text(
        encoding="utf-8"))
    accepted = capsule["proposal"]["accepted_length"]

    if receipt.get("mode") != capsule["runner"]["mode"]:
        refuse("semantic: run receipt mode disagrees with the capsule")
    if receipt.get("model_index_sha256") != capsule["model_identity"]["model_index_sha256"]:
        refuse("semantic: run receipt model index disagrees with the capsule")
    if receipt.get("parent_checkpoint_sha256") != capsule["model_identity"][
            "parent_checkpoint_sha256"]:
        refuse("semantic: run receipt parent identity disagrees with the capsule")
    if receipt.get("proposed") != capsule["proposal"]["proposed_tokens"]:
        refuse("semantic: run receipt proposal disagrees with the capsule")
    if receipt.get("accepted_length") != accepted:
        refuse("semantic: run receipt accepted length disagrees with the capsule")
    if receipt.get("committed_tokens") != capsule["proposal"]["committed_tokens"]:
        refuse("semantic: run receipt committed tokens disagree with the capsule")
    if verdicts.get("STRICT_CANONICAL_COMMIT") != capsule["verdicts"][
            "STRICT_CANONICAL_COMMIT"]:
        refuse("semantic: adjudication verdict disagrees with the capsule")
    if verdicts.get("selected_checkpoint") != capsule["verdicts"]["selected_checkpoint"]:
        refuse("semantic: adjudication checkpoint disagrees with the capsule")
    if verdicts.get("baseline_manifest_root") != capsule["baseline"][
            "manifest_aggregate_root_sha256"]:
        refuse("semantic: adjudication baseline root disagrees with the capsule")
    if verdicts.get("failures"):
        refuse(f"semantic: adjudication records failures {verdicts['failures'][:3]}")
    for p in range(1, accepted + 1):
        row = verdicts["positions"].get(str(p)) or verdicts["positions"].get(p)
        if row is None:
            refuse(f"semantic: adjudication has no position {p}")
        claimed = capsule["comparison"]["positions_audited"][str(p)]
        if row["layers_exact"] != claimed["layers_exact"] or \
                row["layers_divergent"] != claimed["layers_divergent"] or \
                row["bank_exact"] != claimed["attn_res_bank_exact"] or \
                row["hidden_exact"] != claimed["final_hidden_exact"]:
            refuse(f"semantic: position {p} comparison disagrees with the capsule")


def run(capsule_path: Path, private_root: Path | None) -> str:
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    verify_capsule(capsule)
    print(f"CAPSULE_VERIFIED: private-evidence root "
          f"{capsule['aggregate_private_evidence_root_sha256']}")
    print(f"  {capsule['verdicts']['STRICT_CANONICAL_COMMIT']} | accepted "
          f"K={capsule['proposal']['accepted_length']} | "
          f"{capsule['private_evidence']['artifact_count']} bound artifacts")
    if private_root is None:
        print("note: repository reproducibility of the physical result requires "
              "PRIVATE_EVIDENCE_VERIFIED (--private-root on the custody host)")
        return "CAPSULE_VERIFIED"
    verify_private_evidence(capsule, private_root)
    print(f"PRIVATE_EVIDENCE_VERIFIED: all artifacts rehash and their contents "
          f"independently reconstruct the verdict under {private_root}")
    return "PRIVATE_EVIDENCE_VERIFIED"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", default=None)
    parser.add_argument("--capsule", default=None)
    args = parser.parse_args()
    try:
        run(Path(args.capsule) if args.capsule else DEFAULT_CAPSULE,
            Path(args.private_root) if args.private_root else None)
    except VerificationFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
