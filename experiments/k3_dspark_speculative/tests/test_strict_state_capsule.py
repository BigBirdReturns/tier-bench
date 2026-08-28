"""Witnesses for the strict-state capsule verifier.

The committed capsule must authenticate itself, and PRIVATE_EVIDENCE_VERIFIED
must refuse digest-correct private evidence whose CONTENTS contradict the
capsule. Each witness rewrites one private artifact, recomputes the capsule's
manifest digests and aggregate root so the byte level still passes, and
requires refusal at the semantic level. Zero-network, no torch required.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CAPSULE_DIR = REPO / "data" / "estate" / "k3-strict-state-20260828"
VERIFIER = CAPSULE_DIR / "verify_strict_state_capsule.py"
CAPSULE = CAPSULE_DIR / "STRICT-STATE-CAPSULE.json"

spec = importlib.util.spec_from_file_location("verify_strict_state_capsule", VERIFIER)
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class CapsuleLevel(unittest.TestCase):
    def test_committed_capsule_self_verifies(self):
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        V.verify_capsule(capsule)

    def test_pass_with_false_criterion_refused(self):
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        capsule["verdicts"]["criteria"]["4_component_roots_bit_exact"] = False
        with self.assertRaises(V.VerificationFailure):
            V.verify_capsule(capsule)

    def test_pass_with_recorded_divergence_refused(self):
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        capsule["verdicts"]["first_divergence"] = {"position": 1, "layer": 0}
        with self.assertRaises(V.VerificationFailure):
            V.verify_capsule(capsule)

    def test_divergent_layer_row_refused(self):
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        capsule["comparison"]["positions_audited"]["1"]["layers_divergent"] = [7]
        capsule["comparison"]["positions_audited"]["1"]["layers_exact"] = 92
        with self.assertRaises(V.VerificationFailure):
            V.verify_capsule(capsule)

    def test_conflated_economics_refused(self):
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        capsule["economics"]["canonical_speedup_at_accepted_k"] = 2.83
        with self.assertRaises(V.VerificationFailure):
            V.verify_capsule(capsule)

    def test_tampered_private_root_refused(self):
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        capsule["aggregate_private_evidence_root_sha256"] = "0" * 64
        with self.assertRaises(V.VerificationFailure):
            V.verify_capsule(capsule)

    def test_missing_state_file_in_manifest_refused(self):
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        manifest = capsule["private_evidence"]["manifest"]
        victim = next(k for k in manifest if k.endswith("position-01/layer-050.pt"))
        del manifest[victim]
        capsule["private_evidence"]["artifact_count"] = len(manifest)
        lines = "".join(f"{k} {manifest[k]['sha256']}\n" for k in sorted(manifest))
        capsule["aggregate_private_evidence_root_sha256"] = sha256_bytes(
            lines.encode("utf-8"))
        with self.assertRaises(V.VerificationFailure):
            V.verify_capsule(capsule)


class PrivateEvidenceSemantics(unittest.TestCase):
    """Digest-correct private evidence that contradicts the capsule refuses."""

    def build(self, tmp: Path, mutate_receipt=None, mutate_verdicts=None):
        """A minimal private root: only the two parsed JSON artifacts plus
        stub state files, with the capsule's manifest recomputed to match."""
        capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
        accepted = capsule["proposal"]["accepted_length"]
        receipt = {
            "mode": capsule["runner"]["mode"],
            "model_index_sha256": capsule["model_identity"]["model_index_sha256"],
            "parent_checkpoint_sha256": capsule["model_identity"][
                "parent_checkpoint_sha256"],
            "proposed": capsule["proposal"]["proposed_tokens"],
            "accepted_length": accepted,
            "committed_tokens": capsule["proposal"]["committed_tokens"],
        }
        verdicts = {
            "STRICT_CANONICAL_COMMIT": capsule["verdicts"]["STRICT_CANONICAL_COMMIT"],
            "selected_checkpoint": capsule["verdicts"]["selected_checkpoint"],
            "baseline_manifest_root": capsule["baseline"][
                "manifest_aggregate_root_sha256"],
            "failures": [],
            "positions": {
                str(p): {
                    "layers_exact": capsule["comparison"]["positions_audited"][str(p)][
                        "layers_exact"],
                    "layers_divergent": capsule["comparison"]["positions_audited"][
                        str(p)]["layers_divergent"],
                    "bank_exact": capsule["comparison"]["positions_audited"][str(p)][
                        "attn_res_bank_exact"],
                    "hidden_exact": capsule["comparison"]["positions_audited"][str(p)][
                        "final_hidden_exact"],
                }
                for p in range(1, accepted + 1)
            },
        }
        if mutate_receipt:
            mutate_receipt(receipt)
        if mutate_verdicts:
            mutate_verdicts(verdicts)

        manifest = {}

        def write(label: str, data: bytes):
            path = tmp / label
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            manifest[label] = {"sha256": sha256_bytes(data), "bytes": len(data)}

        write("STRICT-VERIFY-RECEIPT.json",
              json.dumps(receipt).encode("utf-8"))
        write("STRICT-ADJUDICATION.json", json.dumps(verdicts).encode("utf-8"))
        write("per-position-logits.pt", b"stub")
        write("../BASELINE-MANIFEST.json", b"stub-manifest")
        for p in range(1, accepted + 1):
            for i in range(93):
                write(f"strict-state/position-{p:02d}/layer-{i:03d}.pt",
                      f"stub {p} {i}".encode())
            write(f"strict-state/position-{p:02d}/attn-res-bank.pt",
                  f"stub bank {p}".encode())

        capsule["private_evidence"]["manifest"] = manifest
        capsule["private_evidence"]["artifact_count"] = len(manifest)
        capsule["private_evidence"]["total_bytes"] = sum(
            v["bytes"] for v in manifest.values())
        lines = "".join(f"{k} {manifest[k]['sha256']}\n" for k in sorted(manifest))
        capsule["aggregate_private_evidence_root_sha256"] = sha256_bytes(
            lines.encode("utf-8"))
        for p in range(1, accepted + 1):
            prefix = f"strict-state/position-{p:02d}/"
            files = {k[len(prefix):]: v["sha256"] for k, v in manifest.items()
                     if k.startswith(prefix)}
            agg = hashlib.sha256()
            for name in sorted(files):
                agg.update(f"{name} {files[name]}\n".encode())
            capsule["per_position_state_roots"][str(p)] = {
                "files": len(files),
                "bytes": 0,
                "state_manifest_root_sha256": agg.hexdigest(),
            }
        return capsule

    def assert_bytes_pass_semantics_refuse(self, capsule, tmp: Path, fragment: str):
        V.verify_capsule(capsule)  # capsule level still valid
        with self.assertRaises(V.VerificationFailure) as ctx:
            V.verify_private_evidence(capsule, tmp)
        self.assertIn(fragment, str(ctx.exception))
        self.assertIn("semantic", str(ctx.exception))

    def test_consistent_private_evidence_verifies(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp)
            V.verify_capsule(capsule)
            V.verify_private_evidence(capsule, tmp)

    def test_verdict_contradiction_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_verdicts=lambda v: v.update(
                STRICT_CANONICAL_COMMIT="FAIL"))
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "verdict")

    def test_recorded_failures_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_verdicts=lambda v: v.update(
                failures=["position 1 layer 3 KDA.recurrent divergent"]))
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "failures")

    def test_substituted_baseline_root_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_verdicts=lambda v: v.update(
                baseline_manifest_root="0" * 64))
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "baseline root")

    def test_substituted_parent_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                parent_checkpoint_sha256="0" * 64))
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "parent identity")

    def test_substituted_model_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                model_index_sha256="0" * 64))
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "model index")

    def test_different_mode_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                mode="FAST_CHUNK_EXPERIMENTAL"))
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "mode")

    def test_different_committed_tokens_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                committed_tokens=[1, 2, 3]))
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "committed tokens")

    def test_component_comparison_contradiction_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)

            def drift(v):
                v["positions"]["1"]["layers_exact"] = 92
                v["positions"]["1"]["layers_divergent"] = [11]
            capsule = self.build(tmp, mutate_verdicts=drift)
            self.assert_bytes_pass_semantics_refuse(capsule, tmp, "comparison")

    def test_missing_private_artifact_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp)
            (tmp / "strict-state" / "position-01" / "layer-042.pt").unlink()
            V.verify_capsule(capsule)
            with self.assertRaises(V.VerificationFailure) as ctx:
                V.verify_private_evidence(capsule, tmp)
            self.assertIn("missing", str(ctx.exception))

    def test_tampered_private_artifact_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp)
            (tmp / "strict-state" / "position-02" / "attn-res-bank.pt").write_bytes(
                b"tampered")
            V.verify_capsule(capsule)
            with self.assertRaises(V.VerificationFailure) as ctx:
                V.verify_private_evidence(capsule, tmp)
            self.assertIn("mismatched", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
