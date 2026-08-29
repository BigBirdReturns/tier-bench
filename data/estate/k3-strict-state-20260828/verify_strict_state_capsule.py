"""Deterministic verifier for the strict-state evidence capsule.

Zero-network. Three levels, each strictly stronger:

  CAPSULE_VERIFIED
      (default) Reconstructs and validates the committed body-safe capsule:
      required fields, per-position state-manifest roots recompute from the
      committed private manifest, the aggregate private-evidence root
      recomputes under the declared rule, the comparison table is internally
      consistent (93/93 layers exact, no divergence, bank and hidden exact at
      every audited position), the verdict criteria all hold, the PASS is
      recorded as gated on an explicit accepted denominator, the economics
      language keeps 2.83x noncanonical, and the CODE IDENTITY of both
      verifier files matches this checkout under repository-stable
      coordinates (canonical LF sha256 + git blob id, never a working-tree
      byte digest).

  PRIVATE_BYTES_VERIFIED
      (--private-root) Additionally rehashes every authorized private
      artifact against the committed manifest. Proves the named files carry
      the expected bytes - and nothing more. A fixture of correctly-digested
      stub tensors reaches exactly this level and no further.

  PRIVATE_EVIDENCE_VERIFIED
      (--private-root) Additionally loads the authenticated baseline manifest,
      loads every retained per-position state tensor and each candidate
      checkpoint, and INDEPENDENTLY RE-INVOKES the committed strict comparison
      implementation (experiments/k3_dspark_speculative/strict_baseline_gate.py)
      to recompute all seven gate criteria from the physical artifacts. The
      capsule's recorded adjudication is then required to agree with that
      recomputation; the first state, identity, token or denominator mismatch
      refuses. This level does not read the precomputed verdict as evidence -
      it reproduces it.

Exit 0 = verified at the requested level; 1 = any check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CAPSULE = HERE / "STRICT-STATE-CAPSULE.json"
REPO_ROOT = HERE.parents[2]

REQUIRED = [
    "schema", "mission", "runner", "code_identity", "model_identity", "baseline",
    "proposal", "per_position_state_roots", "comparison", "verdicts", "economics",
    "private_evidence", "aggregate_private_evidence_root_sha256",
    "aggregate_root_rule", "private_custody_boundary", "claims", "non_claims",
]

GATE_RELPATH = "experiments/k3_dspark_speculative/strict_baseline_gate.py"


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


def canonical_lf_bytes(path: Path) -> bytes:
    """The file's content as git stores it: LF line endings."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()


def verify_code_identity(capsule: dict, repo_root: Path) -> None:
    """The capsule names the implementation that computes the verdict. Bind it
    by content-addressed, repository-stable coordinates so a fresh checkout on
    any platform reproduces the digest - a Windows working-tree byte digest
    never can."""
    ci = capsule["code_identity"]
    files = ci.get("files")
    if not isinstance(files, dict) or not files:
        refuse("code identity binds no files")
    if GATE_RELPATH not in files:
        refuse(f"code identity does not bind the gate implementation {GATE_RELPATH!r}")
    if capsule["runner"]["path"] not in files:
        refuse("code identity does not bind the runner named by the capsule")
    for rel, claim in sorted(files.items()):
        path = repo_root / rel
        if not path.is_file():
            refuse(f"code identity names {rel!r}, absent from this checkout")
        data = canonical_lf_bytes(path)
        lf = hashlib.sha256(data).hexdigest()
        blob = git_blob_sha1(data)
        if lf != claim.get("canonical_lf_sha256"):
            refuse(f"code identity: {rel} canonical LF sha256 {lf} != capsule "
                   f"{claim.get('canonical_lf_sha256')}")
        if blob != claim.get("git_blob_sha1"):
            refuse(f"code identity: {rel} git blob id {blob} != capsule "
                   f"{claim.get('git_blob_sha1')}")
        if len(data) != claim.get("canonical_lf_bytes"):
            refuse(f"code identity: {rel} canonical byte count disagrees")


def verify_capsule(capsule: dict, repo_root: Path | None = None) -> None:
    for field in REQUIRED:
        if field not in capsule:
            refuse(f"capsule missing required field {field!r}")
    if capsule["schema"] != "estate/k3-strict-state-capsule@2":
        refuse(f"unexpected schema {capsule['schema']!r}")

    verify_code_identity(capsule, repo_root or REPO_ROOT)

    manifest = capsule["private_evidence"]["manifest"]
    if len(manifest) != capsule["private_evidence"]["artifact_count"]:
        refuse("private artifact count does not match the manifest length")
    for label, entry in manifest.items():
        if len(entry.get("sha256", "")) != 64:
            refuse(f"private artifact {label!r} lacks a sha256 digest")
    if capsule["baseline"]["manifest_label"] not in manifest:
        refuse("the baseline manifest is not a bound private artifact")

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
        # a PASS may not come from an ungated invocation
        if not verdicts.get("expected_accepted_supplied"):
            refuse("PASS claimed without an accepted-position denominator")
        if verdicts.get("expected_accepted") != accepted:
            refuse(f"PASS gated on denominator {verdicts.get('expected_accepted')!r} "
                   f"but the capsule claims accepted length {accepted}")
        if capsule["baseline"].get("accepted_position_denominator") != accepted:
            refuse("the baseline manifest does not cover the claimed accepted boundary")

    econ = capsule["economics"]
    if econ.get("verification_only_chunk_speedup") == econ.get(
            "canonical_speedup_at_accepted_k"):
        refuse("verification-only and canonical economics must stay distinct")
    if "noncanonical" not in econ.get("note", ""):
        refuse("economics note must keep the verification-only figure noncanonical")
    if not capsule["claims"] or not capsule["non_claims"]:
        refuse("capsule must state both claims and non-claims")


def verify_private_bytes(capsule: dict, root_dir: Path) -> None:
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


def load_gate(repo_root: Path):
    """Import the SAME committed comparison implementation the runner used."""
    gate_path = repo_root / GATE_RELPATH
    if not gate_path.is_file():
        refuse(f"the committed gate implementation {GATE_RELPATH!r} is absent")
    experiments = str(repo_root / "experiments")
    if experiments not in sys.path:
        sys.path.insert(0, experiments)
    spec = importlib.util.spec_from_file_location(
        "k3_dspark_speculative.strict_baseline_gate", gate_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        refuse(f"could not load the committed gate implementation: {exc}")
    return module


def verify_private_evidence(capsule: dict, root_dir: Path,
                            repo_root: Path | None = None) -> dict:
    """Recompute the physical verdict from the retained artifacts.

    This does NOT read STRICT-ADJUDICATION.json as evidence. It loads the
    authenticated baseline manifest, every retained per-position state tensor
    and every candidate checkpoint, re-invokes the committed gate, and then
    requires the capsule (and the stored adjudication) to agree with what the
    physics actually says."""
    repo_root = repo_root or REPO_ROOT
    gate = load_gate(repo_root)
    accepted = capsule["proposal"]["accepted_length"]

    receipt = json.loads((root_dir / "STRICT-VERIFY-RECEIPT.json").read_text(
        encoding="utf-8"))
    stored = json.loads((root_dir / "STRICT-ADJUDICATION.json").read_text(
        encoding="utf-8"))

    # run receipt semantics must match the capsule before anything is recomputed
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

    # the baseline manifest is authenticated against the root the capsule pins
    manifest_path = (root_dir / capsule["baseline"]["manifest_label"]).resolve()
    try:
        manifest = gate.load_manifest(
            manifest_path, capsule["baseline"]["manifest_aggregate_root_sha256"])
    except ValueError as exc:
        refuse(f"baseline manifest: {exc}")
    for pos, entry in manifest["positions"].items():
        claimed = capsule["baseline"]["positions"].get(pos)
        if claimed is None:
            refuse(f"semantic: capsule has no baseline record for position {pos}")
        if claimed["appended_token"] != entry["appended_token"] or \
                claimed["sequence_length"] != entry["sequence_length"] or \
                claimed["generation"] != entry["generation"]:
            refuse(f"semantic: baseline position {pos} disagrees with the capsule")

    # THE recomputation: loads all 93 layer states per position, both
    # checkpoints, the per-position logits, and reruns the strict comparison
    expected_accepted = capsule["verdicts"].get("expected_accepted")
    if expected_accepted is None:
        refuse("the capsule records no accepted denominator to re-gate on")
    recomputed = gate.gate(
        state_dir=root_dir / "strict-state",
        per_position_logits=root_dir / "per-position-logits.pt",
        manifest=manifest,
        model_index_sha256=capsule["model_identity"]["model_index_sha256"],
        parent_checkpoint_sha256=capsule["model_identity"]["parent_checkpoint_sha256"],
        parent_sequence_length=capsule["model_identity"]["parent_sequence_length"],
        proposed=receipt["proposed"],
        accepted=receipt["accepted_length"],
        committed=receipt["committed_tokens"],
        expected_accepted=expected_accepted,
        parent_prefix_sha256=capsule["model_identity"].get("parent_prefix_sha256"),
    )

    if recomputed["failures"]:
        refuse(f"recomputation records failures the capsule does not: "
               f"{recomputed['failures'][:3]}")
    if recomputed["first_divergence"] is not None:
        refuse(f"recomputation found a divergence: {recomputed['first_divergence']}")
    if recomputed["STRICT_CANONICAL_COMMIT"] != capsule["verdicts"][
            "STRICT_CANONICAL_COMMIT"]:
        refuse(f"recomputed verdict {recomputed['STRICT_CANONICAL_COMMIT']} != capsule "
               f"{capsule['verdicts']['STRICT_CANONICAL_COMMIT']}")
    if recomputed["criteria"] != capsule["verdicts"]["criteria"]:
        refuse(f"recomputed gate criteria disagree with the capsule: "
               f"{recomputed['criteria']}")
    if recomputed["selected_checkpoint"] != capsule["verdicts"]["selected_checkpoint"]:
        refuse("recomputed adopted checkpoint disagrees with the capsule")
    if recomputed["expected_accepted"] != expected_accepted or \
            not recomputed["expected_accepted_supplied"]:
        refuse("recomputation was not gated on the capsule's denominator")
    if recomputed["comparison_policy"] != capsule["verdicts"]["comparison_policy"]:
        refuse("the committed gate implements a different comparison policy "
               "than the capsule records")

    for p in range(1, accepted + 1):
        row = recomputed["positions"].get(p) or recomputed["positions"].get(str(p))
        if row is None:
            refuse(f"recomputation produced no position {p}")
        claimed = capsule["comparison"]["positions_audited"][str(p)]
        if row["layers_exact"] != claimed["layers_exact"] or \
                row["layers_divergent"] != claimed["layers_divergent"] or \
                row["bank_exact"] != claimed["attn_res_bank_exact"] or \
                row["hidden_exact"] != claimed["final_hidden_exact"]:
            refuse(f"recomputed position {p} comparison disagrees with the capsule")

    # the stored adjudication must agree with the recomputation too - it is a
    # cross-check, never the evidence
    if stored.get("STRICT_CANONICAL_COMMIT") != recomputed["STRICT_CANONICAL_COMMIT"]:
        refuse("the stored adjudication disagrees with the recomputation")
    if stored.get("selected_checkpoint") != recomputed["selected_checkpoint"]:
        refuse("the stored adjudication checkpoint disagrees with the recomputation")
    if stored.get("baseline_manifest_root") != capsule["baseline"][
            "manifest_aggregate_root_sha256"]:
        refuse("the stored adjudication baseline root disagrees with the capsule")
    return recomputed


def run(capsule_path: Path, private_root: Path | None,
        repo_root: Path | None = None) -> str:
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    verify_capsule(capsule, repo_root)
    print(f"CAPSULE_VERIFIED: private-evidence root "
          f"{capsule['aggregate_private_evidence_root_sha256']}")
    print(f"  {capsule['verdicts']['STRICT_CANONICAL_COMMIT']} | accepted "
          f"K={capsule['proposal']['accepted_length']} (gated on "
          f"{capsule['verdicts']['expected_accepted']}) | "
          f"{capsule['private_evidence']['artifact_count']} bound artifacts")
    if private_root is None:
        print("note: repository reproducibility of the physical result requires "
              "PRIVATE_EVIDENCE_VERIFIED (--private-root on the custody host)")
        return "CAPSULE_VERIFIED"
    verify_private_bytes(capsule, private_root)
    print(f"PRIVATE_BYTES_VERIFIED: "
          f"{capsule['private_evidence']['artifact_count']} artifacts rehash "
          f"exactly under {private_root}")
    verify_private_evidence(capsule, private_root, repo_root)
    print("PRIVATE_EVIDENCE_VERIFIED: the committed gate, re-invoked over the "
          "retained state tensors and checkpoints, independently reproduces all "
          "seven criteria, the adopted checkpoint and every per-position "
          "comparison")
    return "PRIVATE_EVIDENCE_VERIFIED"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", default=None)
    parser.add_argument("--capsule", default=None)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args()
    try:
        run(Path(args.capsule) if args.capsule else DEFAULT_CAPSULE,
            Path(args.private_root) if args.private_root else None,
            Path(args.repo_root) if args.repo_root else None)
    except VerificationFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
