"""Hostile witnesses for the CLAUDE-5 fabric capsule verifier.

Each witness builds a synthetic estate root whose raw receipts are INTERNALLY
VALID and CORRECTLY REHASHED (the capsule manifest and aggregate root are
recomputed so RAW_BYTES_VERIFIED passes), but whose contents contradict the
committed capsule in exactly one decision-critical field. Every witness must
refuse at the RAW_SEMANTICS_VERIFIED level. Zero-model, zero-network.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFIER = REPO / "data" / "estate" / "fabric-qual-20260827" / "verify_capsule.py"
COMMITTED_CAPSULE = REPO / "data" / "estate" / "fabric-qual-20260827" / "CAPSULE.json"

spec = importlib.util.spec_from_file_location("fabric_verify_capsule", VERIFIER)
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def gpu_lines(mibs):
    return [f"{i}, {mib} MiB, {50 if mib else 0} %, {200.0 if mib else 15.0} W, 45"
            for i, mib in enumerate(mibs)]


def receipt(phase, model, decode, n=9, secondary=None, prefill=100.0,
            mibs=(17000, 0), ts="2026-08-27T20:00:00+00:00"):
    r = {
        "phase": phase,
        "model": model,
        "ts": ts,
        "primary": {"n": n, "decode_median": decode, "decode_min": decode,
                    "decode_max": decode, "prefill_median": prefill},
        "gpu_after_load": gpu_lines(mibs),
        "gpu_during": gpu_lines(mibs),
        "raw": [{"wall_s": 10.0, "decode_tok_s": decode,
                 "prefill_tok_s": prefill, "tokens": 512} for _ in range(n)],
    }
    if secondary is not None:
        r["secondary"] = {"n": n, "decode_median": secondary,
                          "decode_min": secondary, "decode_max": secondary,
                          "prefill_median": prefill}
        r["raw_secondary"] = [{"wall_s": 10.0, "decode_tok_s": secondary,
                               "prefill_tok_s": prefill, "tokens": 512}
                              for _ in range(n)]
        r["aggregate_decode"] = round(decode + secondary, 1)
    return r


def build_fixture(base: Path):
    """A fully consistent synthetic estate + capsule (digests recomputed)."""
    est = base / "estate"
    (est / "receipts").mkdir(parents=True)
    receipts = {
        "single-27b-msi": receipt("single-27b-msi", "qwen3.5:27b", 33.8,
                                  prefill=104.1, mibs=(17262, 0)),
        "double-27b-both": receipt("double-27b-both", "qwen3.5:27b", 33.3,
                                   secondary=36.1, prefill=86.9,
                                   mibs=(17268, 17268)),
        "split-35b-a3b-q8": receipt("split-35b-a3b-q8", "qwen3.5:35b-a3b-q8_0",
                                    51.6, prefill=102.5, mibs=(19700, 17200)),
        "split-70b-r1": receipt("split-70b-r1", "deepseek-r1:70b", 18.1,
                                prefill=156.9, mibs=(21900, 21800)),
    }
    summary = {
        "schema": "estate/fabric-qual@1",
        "host": "OCTO-L01",
        "date": "2026-08-27",
        "verdict": "PASS - synthetic fixture",
        "phases": {k: {} for k in receipts},
    }
    (est / "QUAL-SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    (est / "fabric_qual.py").write_text("# synthetic driver stub\n", encoding="utf-8")
    for name, r in receipts.items():
        (est / "receipts" / f"{name}.json").write_text(json.dumps(r), encoding="utf-8")

    capsule = json.loads(COMMITTED_CAPSULE.read_text(encoding="utf-8"))
    capsule["phase_results"]["single-27b-msi"]["prefill_tok_s_median"] = 104.1
    capsule["phase_results"]["split-35b-a3b-q8"]["vram_split_gb"] = [19.7, 17.2]
    capsule["phase_results"]["split-70b-r1"]["vram_split_gb"] = [21.9, 21.8]
    write_capsule(base, capsule, est)
    return est, capsule


def write_capsule(base: Path, capsule: dict, est: Path):
    """Recompute the manifest + aggregate root so raw BYTES always verify."""
    manifest = {}
    for rel in ["QUAL-SUMMARY.json", "fabric_qual.py"] + [
            f"receipts/{p.name}" for p in sorted((est / "receipts").iterdir())]:
        manifest[rel] = hashlib.sha256((est / rel).read_bytes()).hexdigest()
    capsule["receipt_manifest_sha256"] = manifest
    capsule["summary_receipt_sha256"] = manifest["QUAL-SUMMARY.json"]
    lines = "".join(f"{k} {v}\n" for k, v in sorted(manifest.items()))
    capsule["aggregate_evidence_root_sha256"] = hashlib.sha256(
        lines.encode("utf-8")).hexdigest()
    (base / "CAPSULE.json").write_text(json.dumps(capsule), encoding="utf-8")


class SemanticWitnesses(unittest.TestCase):
    def run_levels(self, base: Path):
        capsule = json.loads((base / "CAPSULE.json").read_text(encoding="utf-8"))
        V.verify_capsule_only(capsule)
        V.verify_raw_bytes(capsule, base / "estate")
        recon = V.reconstruct_from_estate(
            base / "estate", capsule["qualification_mode_denominator"]["modes"])
        V.verify_raw_semantics(capsule, recon)

    def mutate_receipt(self, est: Path, base: Path, name: str, fn):
        p = est / "receipts" / f"{name}.json"
        r = json.loads(p.read_text(encoding="utf-8"))
        fn(r)
        p.write_text(json.dumps(r), encoding="utf-8")
        capsule = json.loads((base / "CAPSULE.json").read_text(encoding="utf-8"))
        write_capsule(base, capsule, est)  # bytes stay verifiable

    def mutate_summary(self, est: Path, base: Path, fn):
        p = est / "QUAL-SUMMARY.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        fn(s)
        p.write_text(json.dumps(s), encoding="utf-8")
        capsule = json.loads((base / "CAPSULE.json").read_text(encoding="utf-8"))
        write_capsule(base, capsule, est)

    def assert_semantic_refusal(self, base: Path, fragment: str):
        capsule = json.loads((base / "CAPSULE.json").read_text(encoding="utf-8"))
        V.verify_capsule_only(capsule)
        V.verify_raw_bytes(capsule, base / "estate")  # bytes MUST still pass
        recon = V.reconstruct_from_estate(
            base / "estate", capsule["qualification_mode_denominator"]["modes"])
        with self.assertRaises(V.VerificationFailure) as ctx:
            V.verify_raw_semantics(capsule, recon)
        self.assertIn(fragment, str(ctx.exception))

    def test_consistent_fixture_reaches_raw_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            build_fixture(base)
            self.run_levels(base)  # no exception = RAW_SEMANTICS_VERIFIED

    def test_phase_denominator_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_summary(est, base, lambda s: s["phases"].pop("split-70b-r1"))
            self.assert_semantic_refusal(base, "phase denominator")

    def test_run_count_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def drop_run(r):
                r["raw"] = r["raw"][:8]
                r["primary"]["n"] = 8
            self.mutate_receipt(est, base, "single-27b-msi", drop_run)
            self.assert_semantic_refusal(base, "run count")

    def test_throughput_median_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def shift(r):  # internally valid: raw and declared agree at 35.0
                for x in r["raw"]:
                    x["decode_tok_s"] = 35.0
                r["primary"]["decode_median"] = 35.0
            self.mutate_receipt(est, base, "single-27b-msi", shift)
            self.assert_semantic_refusal(base, "decode median")

    def test_model_identity_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_receipt(est, base, "split-70b-r1",
                                lambda r: r.update(model="qwen3.5:14b"))
            self.assert_semantic_refusal(base, "model")

    def test_excluded_device_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def activate_second(r):  # baseline phase secretly used both cards
                r["gpu_during"] = gpu_lines((17262, 5000))
            self.mutate_receipt(est, base, "single-27b-msi", activate_second)
            self.assert_semantic_refusal(base, "devices")

    def test_concurrency_retention_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def degrade(r):  # internally valid but retention no longer 98.5
                for x in r["raw"]:
                    x["decode_tok_s"] = 30.0
                r["primary"]["decode_median"] = 30.0
                r["aggregate_decode"] = round(30.0 + 36.1, 1)
            self.mutate_receipt(est, base, "double-27b-both", degrade)
            self.assert_semantic_refusal(base, "aggregate")

    def test_vram_allocation_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_receipt(est, base, "split-70b-r1",
                                lambda r: r.update(gpu_during=gpu_lines((12000, 11000))))
            self.assert_semantic_refusal(base, "VRAM")

    def test_terminal_verdict_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_summary(est, base,
                                lambda s: s.update(verdict="FAIL - thermal abort"))
            self.assert_semantic_refusal(base, "PASS verdict")

    def test_date_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_summary(est, base, lambda s: s.update(date="2026-08-26"))
            self.assert_semantic_refusal(base, "date")

    def test_committed_capsule_reaches_capsule_only(self):
        capsule = json.loads(COMMITTED_CAPSULE.read_text(encoding="utf-8"))
        V.verify_capsule_only(capsule)  # fresh-checkout level, no estate needed


if __name__ == "__main__":
    unittest.main(verbosity=2)
