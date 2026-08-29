"""Witnesses for the strict-state capsule verifier.

Three levels, three obligations:

  CAPSULE_VERIFIED         the committed capsule authenticates itself, binds the
                           code that computes the verdict by repository-stable
                           coordinates, and cannot record an ungated PASS.
  PRIVATE_BYTES_VERIFIED   named private artifacts carry the expected bytes.
  PRIVATE_EVIDENCE_VERIFIED the committed gate, re-invoked over the retained
                           tensors, reproduces the verdict.

The stub-tensor fixture below is deliberately capped: it reaches
PRIVATE_BYTES_VERIFIED and MUST refuse at PRIVATE_EVIDENCE_VERIFIED. Digest-
correct arbitrary bytes are not a physical result. The real recomputation is
exercised against the custody tree when it is present.

Zero-network.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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

# the custody tree this capsule was built from; absent on any other host
CUSTODY_ROOT = Path(os.environ.get(
    "K3_STRICT_PRIVATE_ROOT",
    r"D:\kimilab\estate\pr-stack-strict-state-closure-20260828"
    r"\phase8-strict-successor\strict-d7"))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def committed() -> dict:
    return json.loads(CAPSULE.read_text(encoding="utf-8"))


class CapsuleLevel(unittest.TestCase):
    def refuse(self, mutate, fragment: str):
        capsule = committed()
        mutate(capsule)
        with self.assertRaises(V.VerificationFailure) as ctx:
            V.verify_capsule(capsule, REPO)
        self.assertIn(fragment, str(ctx.exception))

    def test_committed_capsule_self_verifies(self):
        V.verify_capsule(committed(), REPO)

    def test_pass_with_false_criterion_refused(self):
        self.refuse(lambda c: c["verdicts"]["criteria"].update(
            {"4_component_roots_bit_exact": False}), "criterion is false")

    def test_pass_with_recorded_divergence_refused(self):
        self.refuse(lambda c: c["verdicts"].update(
            first_divergence={"position": 1, "layer": 0}), "recorded divergence")

    def test_divergent_layer_row_refused(self):
        def drift(c):
            c["comparison"]["positions_audited"]["1"]["layers_divergent"] = [7]
            c["comparison"]["positions_audited"]["1"]["layers_exact"] = 92
        self.refuse(drift, "93/93 exact")

    def test_conflated_economics_refused(self):
        self.refuse(lambda c: c["economics"].update(
            canonical_speedup_at_accepted_k=2.83), "must stay distinct")

    def test_tampered_private_root_refused(self):
        self.refuse(lambda c: c.update(
            aggregate_private_evidence_root_sha256="0" * 64), "does not recompute")

    def test_missing_state_file_in_manifest_refused(self):
        def drop(c):
            manifest = c["private_evidence"]["manifest"]
            victim = next(k for k in manifest if k.endswith("position-01/layer-050.pt"))
            del manifest[victim]
            c["private_evidence"]["artifact_count"] = len(manifest)
            lines = "".join(f"{k} {manifest[k]['sha256']}\n" for k in sorted(manifest))
            c["aggregate_private_evidence_root_sha256"] = sha256_bytes(
                lines.encode("utf-8"))
        self.refuse(drop, "state-manifest root does not recompute")

    # ---- the accepted denominator must be recorded and consistent ----

    def test_pass_without_a_denominator_refused(self):
        self.refuse(lambda c: c["verdicts"].update(expected_accepted_supplied=False),
                    "without an accepted-position denominator")

    def test_pass_gated_on_a_different_denominator_refused(self):
        self.refuse(lambda c: c["verdicts"].update(expected_accepted=3),
                    "but the capsule claims accepted length")

    def test_baseline_not_covering_the_boundary_refused(self):
        self.refuse(lambda c: c["baseline"].update(accepted_position_denominator=1),
                    "does not cover the claimed accepted boundary")

    def test_unbound_baseline_manifest_refused(self):
        self.refuse(lambda c: c["baseline"].update(manifest_label="nowhere.json"),
                    "not a bound private artifact")

    # ---- code identity ----

    def test_code_identity_must_bind_the_gate(self):
        self.refuse(
            lambda c: c["code_identity"]["files"].pop(V.GATE_RELPATH),
            "does not bind the gate implementation")

    def test_code_identity_must_bind_the_runner(self):
        self.refuse(
            lambda c: c["code_identity"]["files"].pop(c["runner"]["path"]),
            "does not bind the runner")

    def test_altered_gate_source_refused(self):
        """A checkout whose gate implementation differs from the one the
        capsule names must refuse, even by one byte."""
        with tempfile.TemporaryDirectory() as t:
            fake = Path(t)
            for rel in committed()["code_identity"]["files"]:
                dst = fake / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / rel, dst)
            gate = fake / V.GATE_RELPATH
            gate.write_bytes(gate.read_bytes() + b"\n# tampered\n")
            with self.assertRaises(V.VerificationFailure) as ctx:
                V.verify_capsule(committed(), fake)
            self.assertIn("canonical LF sha256", str(ctx.exception))

    def test_missing_commit_refused(self):
        self.refuse(lambda c: c["code_identity"].update(commit=None),
                    "records no commit")

    @unittest.skipUnless((REPO / ".git").exists(), "not a git checkout")
    def test_commit_that_does_not_carry_the_blobs_refused(self):
        self.refuse(lambda c: c["code_identity"].update(commit="0" * 40),
                    "is not present at commit")

    def test_line_ending_conversion_does_not_change_identity(self):
        """CRLF and LF checkouts of the same content must bind identically -
        that is the whole point of using the canonical LF byte stream."""
        with tempfile.TemporaryDirectory() as t:
            fake = Path(t)
            for rel in committed()["code_identity"]["files"]:
                dst = fake / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                lf = (REPO / rel).read_bytes().replace(b"\r\n", b"\n")
                dst.write_bytes(lf.replace(b"\n", b"\r\n"))  # force CRLF
            V.verify_capsule(committed(), fake)


class StubFixtureIsCapped(unittest.TestCase):
    """A private root of correctly-digested stub bytes reaches the BYTES level
    and never the EVIDENCE level."""

    def build(self, tmp: Path, mutate_receipt=None, mutate_verdicts=None):
        capsule = committed()
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

        write("STRICT-VERIFY-RECEIPT.json", json.dumps(receipt).encode("utf-8"))
        write("STRICT-ADJUDICATION.json", json.dumps(verdicts).encode("utf-8"))
        write("per-position-logits.pt", b"stub")
        write(capsule["baseline"]["manifest_label"], b"stub-manifest")
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

    def test_stub_fixture_reaches_bytes_and_is_refused_at_evidence(self):
        """The exact defect the review named: stub tensor bytes plus a positive
        adjudication must NOT reach PRIVATE_EVIDENCE_VERIFIED."""
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp)
            V.verify_capsule(capsule, REPO)
            V.verify_private_bytes(capsule, tmp)      # bytes level: passes
            with self.assertRaises(V.VerificationFailure) as ctx:
                V.verify_private_evidence(capsule, tmp, REPO)
            self.assertIn("baseline manifest", str(ctx.exception))

    def assert_refused_before_recomputation(self, capsule, tmp: Path, fragment: str):
        V.verify_capsule(capsule, REPO)
        V.verify_private_bytes(capsule, tmp)
        with self.assertRaises(V.VerificationFailure) as ctx:
            V.verify_private_evidence(capsule, tmp, REPO)
        self.assertIn(fragment, str(ctx.exception))
        self.assertIn("semantic", str(ctx.exception))

    def test_substituted_parent_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                parent_checkpoint_sha256="0" * 64))
            self.assert_refused_before_recomputation(capsule, tmp, "parent identity")

    def test_substituted_model_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                model_index_sha256="0" * 64))
            self.assert_refused_before_recomputation(capsule, tmp, "model index")

    def test_different_mode_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                mode="FAST_CHUNK_EXPERIMENTAL"))
            self.assert_refused_before_recomputation(capsule, tmp, "mode")

    def test_different_committed_tokens_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp, mutate_receipt=lambda r: r.update(
                committed_tokens=[1, 2, 3]))
            self.assert_refused_before_recomputation(capsule, tmp, "committed tokens")

    def test_missing_private_artifact_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp)
            (tmp / "strict-state" / "position-01" / "layer-042.pt").unlink()
            V.verify_capsule(capsule, REPO)
            with self.assertRaises(V.VerificationFailure) as ctx:
                V.verify_private_bytes(capsule, tmp)
            self.assertIn("missing", str(ctx.exception))

    def test_tampered_private_artifact_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            capsule = self.build(tmp)
            (tmp / "strict-state" / "position-02" / "attn-res-bank.pt").write_bytes(
                b"tampered")
            V.verify_capsule(capsule, REPO)
            with self.assertRaises(V.VerificationFailure) as ctx:
                V.verify_private_bytes(capsule, tmp)
            self.assertIn("mismatched", str(ctx.exception))


@unittest.skipUnless(
    (CUSTODY_ROOT / "STRICT-VERIFY-RECEIPT.json").is_file(),
    "custody tree absent (this level runs only on the evidence host)")
class RealRecomputation(unittest.TestCase):
    """On the custody host, PRIVATE_EVIDENCE_VERIFIED must actually reload the
    retained state tensors and reproduce the verdict."""

    def test_full_recomputation_reproduces_the_verdict(self):
        capsule = committed()
        V.verify_capsule(capsule, REPO)
        V.verify_private_bytes(capsule, CUSTODY_ROOT)
        recomputed = V.verify_private_evidence(capsule, CUSTODY_ROOT, REPO)
        self.assertEqual(recomputed["STRICT_CANONICAL_COMMIT"], "PASS")
        self.assertEqual(recomputed["failures"], [])
        self.assertIsNone(recomputed["first_divergence"])
        self.assertEqual(recomputed["selected_checkpoint"],
                         capsule["proposal"]["accepted_length"])
        self.assertTrue(recomputed["expected_accepted_supplied"])
        for p in range(1, capsule["proposal"]["accepted_length"] + 1):
            row = recomputed["positions"][p]
            self.assertEqual(row["layers_exact"], 93)
            self.assertEqual(row["layers_divergent"], [])
            self.assertTrue(row["bank_exact"])
            self.assertTrue(row["hidden_exact"])

    def test_wrong_denominator_fails_the_recomputation(self):
        capsule = committed()
        capsule["verdicts"]["expected_accepted"] = 1
        with self.assertRaises(V.VerificationFailure) as ctx:
            V.verify_private_evidence(capsule, CUSTODY_ROOT, REPO)
        self.assertIn("failures", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
