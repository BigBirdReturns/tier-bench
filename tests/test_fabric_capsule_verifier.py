"""Hostile witnesses for the CLAUDE-5 fabric capsule verifier.

Each witness builds a synthetic estate root whose raw artifacts are INTERNALLY
VALID and CORRECTLY REHASHED (the capsule manifest and aggregate root are
recomputed so RAW_BYTES_VERIFIED passes), but whose contents contradict the
committed capsule in exactly one decision-critical field. Every witness must
refuse. Zero-model, zero-network.

Witness coverage:
  denominator/statistics  phase denominator, run count, decode median,
                          recomputed-decode-vs-declared, recomputed-prefill-
                          vs-declared, per-card medians, aggregate/retention,
                          VRAM, terminal verdict, date
  workload                per-sample token count, driver generation constant
  identity                GPU UUID (driver source and device attestation),
                          swapped card roles via serve pinning, altered core
                          lock cap, altered core-lock policy rule, retagged
                          ollama model manifest, driver serve dispatch
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

MSI = "GPU-b84a8323-dbd6-e432-074b-3ce8fadd3326"
DELLB = "GPU-493239dc-f76e-bbbb-8e68-ffd34a5e7bbc"

DRIVER_SRC = f'''"""synthetic bench driver (fixture)"""
import json

MSI_UUID = "{MSI}"
DELLB_UUID = "{DELLB}"
PROMPTS = ["a", "b", "c"]
N_PREDICT = 512
ROUNDS = 3


def bench(port, model, tag, concurrent_with=None):
    pass


if __name__ == "__main__":
    bench(11504, "qwen3.5:27b", "single-27b-msi")
    bench(11504, "qwen3.5:27b", "double-27b-both", concurrent_with=11505)
    bench(11506, "qwen3.5:35b-a3b-q8_0", "split-35b-a3b-q8")
    bench(11506, "deepseek-r1:70b", "split-70b-r1")
'''

LAUNCHER_SRC = f"""# synthetic fabric serving layer (fixture)
$serves = @(
    @{{ port = 11504; cuda = '{MSI}' }},
    @{{ port = 11505; cuda = '{DELLB}' }},
    @{{ port = 11506; cuda = $null }}
)
"""

GPU_MODE_SRC = """# synthetic core-lock applier (fixture)
# Effective core lock per card = min(mode's lock, the card's coreLockCapMHz).
    $eff = $m.coreLock
    if ($card2.coreLockCapMHz -lt $eff) {
        $eff = [int]$card2.coreLockCapMHz
    }
"""


def gpu_lines(mibs):
    return [f"{i}, {mib} MiB, {50 if mib else 0} %, {200.0 if mib else 15.0} W, 45"
            for i, mib in enumerate(mibs)]


def receipt(phase, model, decode, n=9, secondary=None, prefill=100.0,
            mibs=(17000, 0), ts="2026-08-27T20:00:00+00:00", tokens=512):
    r = {
        "phase": phase,
        "model": model,
        "ts": ts,
        "primary": {"n": n, "decode_median": decode, "decode_min": decode,
                    "decode_max": decode, "prefill_median": prefill},
        "gpu_after_load": gpu_lines(mibs),
        "gpu_during": gpu_lines(mibs),
        "raw": [{"wall_s": 10.0, "decode_tok_s": decode,
                 "prefill_tok_s": prefill, "tokens": tokens} for _ in range(n)],
    }
    if secondary is not None:
        r["secondary"] = {"n": n, "decode_median": secondary,
                          "decode_min": secondary, "decode_max": secondary,
                          "prefill_median": prefill}
        r["raw_secondary"] = [{"wall_s": 10.0, "decode_tok_s": secondary,
                               "prefill_tok_s": prefill, "tokens": tokens}
                              for _ in range(n)]
        r["aggregate_decode"] = round(decode + secondary, 1)
    return r


def build_fixture(base: Path):
    """A fully consistent synthetic estate + capsule (digests recomputed)."""
    est = base / "estate"
    (est / "receipts").mkdir(parents=True)
    ident = est / "identity"
    (ident / "ollama-manifests" / "qwen3.5").mkdir(parents=True)
    (ident / "ollama-manifests" / "deepseek-r1").mkdir(parents=True)

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
    (est / "fabric_qual.py").write_text(DRIVER_SRC, encoding="utf-8")
    for name, r in receipts.items():
        (est / "receipts" / f"{name}.json").write_text(json.dumps(r), encoding="utf-8")

    (ident / "launch-fabric-serves.ps1").write_text(LAUNCHER_SRC, encoding="utf-8")
    (ident / "gpu-mode.ps1").write_text(GPU_MODE_SRC, encoding="utf-8")
    (ident / "gpu-cards.json").write_text(json.dumps({
        "cards": {
            MSI: {"label": "MSI", "coreLockCapMHz": 1200},
            DELLB: {"label": "Dell-B"},
        }
    }), encoding="utf-8")
    (ident / "gpu-host-OCTO-L01.json").write_text(json.dumps({
        "host": "OCTO-L01",
        "validated": True,
        "modes": {
            "decode": {"coreLock": 1410, "note": "DEFAULT. synthetic fixture mode"},
            "eco": {"coreLock": 1110, "note": "lower power"},
        },
        "validatedPairUuids": [MSI, DELLB],
    }), encoding="utf-8")
    (ident / "IDENTITY-ATTESTATION.json").write_text(json.dumps({
        "schema": "estate/fabric-identity-attestation@1",
        "host": "OCTO-L01",
        "observation_class": "POST_RUN_READBACK",
        "nvidia_smi_rows": [
            f"0, {MSI}, NVIDIA GeForce RTX 3090, 00000000:04:00.0, 24576 MiB",
            f"1, {DELLB}, NVIDIA GeForce RTX 3090, 00000000:CA:00.0, 24576 MiB",
        ],
    }), encoding="utf-8")
    for repo, tag in [("qwen3.5", "27b"), ("qwen3.5", "35b-a3b-q8_0"),
                      ("deepseek-r1", "70b")]:
        (ident / "ollama-manifests" / repo / tag).write_text(
            json.dumps({"synthetic-manifest": f"{repo}:{tag}"}), encoding="utf-8")

    capsule = json.loads(COMMITTED_CAPSULE.read_text(encoding="utf-8"))
    capsule["phase_results"]["single-27b-msi"]["prefill_tok_s_median"] = 104.1
    capsule["phase_results"]["split-35b-a3b-q8"]["vram_split_gb"] = [19.7, 17.2]
    capsule["phase_results"]["split-70b-r1"]["vram_split_gb"] = [21.9, 21.8]
    write_capsule(base, capsule, est)
    return est, capsule


def write_capsule(base: Path, capsule: dict, est: Path, sync_model_digests=True):
    """Recompute the manifest + aggregate root so raw BYTES always verify."""
    manifest = {}
    for p in sorted(est.rglob("*")):
        if p.is_file():
            manifest[p.relative_to(est).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    capsule["receipt_manifest_sha256"] = manifest
    capsule["summary_receipt_sha256"] = manifest["QUAL-SUMMARY.json"]
    if sync_model_digests:
        for m in capsule["model_identities"]:
            repo, tag = m["name"].split(":")
            m["ollama_manifest_sha256"] = manifest[
                f"identity/ollama-manifests/{repo}/{tag}"]
    lines = "".join(f"{k} {v}\n" for k, v in sorted(manifest.items()))
    capsule["aggregate_evidence_root_sha256"] = hashlib.sha256(
        lines.encode("utf-8")).hexdigest()
    (base / "CAPSULE.json").write_text(json.dumps(capsule), encoding="utf-8")


class SemanticWitnesses(unittest.TestCase):
    # ---------------- helpers ----------------

    def _capsule(self, base: Path) -> dict:
        return json.loads((base / "CAPSULE.json").read_text(encoding="utf-8"))

    def run_levels(self, base: Path):
        capsule = self._capsule(base)
        V.verify_capsule_only(capsule)
        V.verify_raw_bytes(capsule, base / "estate")
        recon = V.reconstruct_from_estate(
            base / "estate", capsule["qualification_mode_denominator"]["modes"],
            [m["name"] for m in capsule["model_identities"]])
        V.verify_raw_semantics(capsule, recon)

    def rewrite(self, base: Path, est: Path, sync_model_digests=True):
        write_capsule(base, self._capsule(base), est, sync_model_digests)

    def mutate_receipt(self, est: Path, base: Path, name: str, fn):
        p = est / "receipts" / f"{name}.json"
        r = json.loads(p.read_text(encoding="utf-8"))
        fn(r)
        p.write_text(json.dumps(r), encoding="utf-8")
        self.rewrite(base, est)

    def mutate_summary(self, est: Path, base: Path, fn):
        p = est / "QUAL-SUMMARY.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        fn(s)
        p.write_text(json.dumps(s), encoding="utf-8")
        self.rewrite(base, est)

    def mutate_identity_json(self, est: Path, base: Path, rel: str, fn,
                             sync_model_digests=True):
        p = est / "identity" / rel
        d = json.loads(p.read_text(encoding="utf-8"))
        fn(d)
        p.write_text(json.dumps(d), encoding="utf-8")
        self.rewrite(base, est, sync_model_digests)

    def mutate_text(self, est: Path, base: Path, rel: str, fn):
        p = est / rel
        p.write_text(fn(p.read_text(encoding="utf-8")), encoding="utf-8")
        self.rewrite(base, est)

    def mutate_capsule(self, base: Path, est: Path, fn):
        c = self._capsule(base)
        fn(c)
        write_capsule(base, c, est)

    def assert_semantic_refusal(self, base: Path, fragment: str):
        capsule = self._capsule(base)
        V.verify_capsule_only(capsule)
        V.verify_raw_bytes(capsule, base / "estate")  # bytes MUST still pass
        # a refusal anywhere at or after reconstruction is a semantic refusal:
        # unparsable identity evidence is as fatal as contradictory evidence.
        with self.assertRaises(V.VerificationFailure) as ctx:
            recon = V.reconstruct_from_estate(
                base / "estate", capsule["qualification_mode_denominator"]["modes"],
                [m["name"] for m in capsule["model_identities"]])
            V.verify_raw_semantics(capsule, recon)
        self.assertIn(fragment, str(ctx.exception))

    def assert_capsule_refusal(self, base: Path, fragment: str):
        with self.assertRaises(V.VerificationFailure) as ctx:
            V.verify_capsule_only(self._capsule(base))
        self.assertIn(fragment, str(ctx.exception))

    # ---------------- baseline ----------------

    def test_consistent_fixture_reaches_raw_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            build_fixture(base)
            self.run_levels(base)  # no exception = RAW_SEMANTICS_VERIFIED

    def test_committed_capsule_reaches_capsule_only(self):
        capsule = json.loads(COMMITTED_CAPSULE.read_text(encoding="utf-8"))
        V.verify_capsule_only(capsule)  # fresh-checkout level, no estate needed

    # ---------------- denominator / statistics ----------------

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

    def test_altered_decode_samples_with_unchanged_declared_median_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def swap(r):  # samples moved, declared median left at 33.8
                for x in r["raw"]:
                    x["decode_tok_s"] = 40.0
            self.mutate_receipt(est, base, "single-27b-msi", swap)
            self.assert_semantic_refusal(base, "recomputed decode median")

    def test_altered_prefill_samples_with_unchanged_declared_median_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def swap(r):  # every raw prefill -> 1.0, declared median left at 104.1
                for x in r["raw"]:
                    x["prefill_tok_s"] = 1.0
            self.mutate_receipt(est, base, "single-27b-msi", swap)
            self.assert_semantic_refusal(base, "recomputed prefill median")

    def test_altered_secondary_prefill_samples_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def swap(r):
                for x in r["raw_secondary"]:
                    x["prefill_tok_s"] = 1.0
            self.mutate_receipt(est, base, "double-27b-both", swap)
            self.assert_semantic_refusal(base, "recomputed secondary prefill median")

    def test_per_card_median_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            # capsule claims MSI 1.0 / Dell-B 68.4 against raw 33.3 / 36.1
            self.mutate_capsule(base, est, lambda c: c["phase_results"][
                "double-27b-both"]["per_card_medians"].update(msi=1.0, dell_b=68.4))
            self.assert_semantic_refusal(base, "per-card median for 'msi'")

    def test_swapped_card_roles_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            # launcher and capsule agree that the pinning swapped, so the identity
            # binding still reconciles - but MSI is now the 36.1 stream.
            self.mutate_text(est, base, "identity/launch-fabric-serves.ps1",
                             lambda s: s.replace(MSI, "__TMP__")
                                        .replace(DELLB, MSI).replace("__TMP__", DELLB))
            self.mutate_capsule(base, est, lambda c: c.update(
                serve_pinning={"11504": DELLB, "11505": MSI, "11506": None}))
            self.assert_semantic_refusal(base, "per-card median for 'msi'")

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
            self.assert_semantic_refusal(base, "per-card median")

    def test_vram_allocation_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_receipt(est, base, "split-70b-r1",
                                lambda r: r.update(gpu_during=gpu_lines((12000, 11000))))
            self.assert_semantic_refusal(base, "VRAM")

    def test_excluded_device_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def activate_second(r):  # baseline phase secretly used both cards
                r["gpu_during"] = gpu_lines((17262, 5000))
            self.mutate_receipt(est, base, "single-27b-msi", activate_second)
            self.assert_semantic_refusal(base, "devices")

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

    # ---------------- workload ----------------

    def test_one_token_workload_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def shrink(r):  # 512-token runs replaced by 1-token runs
                for x in r["raw"]:
                    x["tokens"] = 1
            self.mutate_receipt(est, base, "single-27b-msi", shrink)
            self.assert_semantic_refusal(base, "primary sample token counts")

    def test_one_token_secondary_workload_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)

            def shrink(r):
                for x in r["raw_secondary"]:
                    x["tokens"] = 1
            self.mutate_receipt(est, base, "double-27b-both", shrink)
            self.assert_semantic_refusal(base, "secondary sample token counts")

    def test_driver_generation_constant_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_text(est, base, "fabric_qual.py",
                             lambda s: s.replace("N_PREDICT = 512", "N_PREDICT = 64"))
            self.assert_semantic_refusal(base, "driver N_PREDICT")

    def test_driver_serve_dispatch_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_text(
                est, base, "fabric_qual.py",
                lambda s: s.replace('"double-27b-both", concurrent_with=11505',
                                    '"double-27b-both", concurrent_with=11506'))
            self.assert_semantic_refusal(base, "driver serve binding")

    # ---------------- identity ----------------

    def test_altered_driver_uuid_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_text(est, base, "fabric_qual.py",
                             lambda s: s.replace(DELLB, "GPU-deadbeef-0000-0000-0000-000000000000"))
            self.assert_semantic_refusal(base, "driver-source UUIDs")

    def test_altered_attested_uuid_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_identity_json(
                est, base, "IDENTITY-ATTESTATION.json",
                lambda d: d.update(nvidia_smi_rows=[
                    f"0, {MSI}, NVIDIA GeForce RTX 3090, 00000000:04:00.0, 24576 MiB",
                    "1, GPU-deadbeef-0000-0000-0000-000000000000, "
                    "NVIDIA GeForce RTX 3090, 00000000:CA:00.0, 24576 MiB"]))
            self.assert_semantic_refusal(base, "attested device UUIDs")

    def test_altered_validated_pair_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_identity_json(
                est, base, "gpu-host-OCTO-L01.json",
                lambda d: d.update(validatedPairUuids=[
                    MSI, "GPU-deadbeef-0000-0000-0000-000000000000"]))
            self.assert_semantic_refusal(base, "validated pair")

    def test_altered_lock_cap_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_identity_json(
                est, base, "gpu-cards.json",
                lambda d: d["cards"][MSI].update(coreLockCapMHz=1000))
            self.assert_semantic_refusal(base, "effective core lock")

    def test_altered_host_mode_lock_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_identity_json(
                est, base, "gpu-host-OCTO-L01.json",
                lambda d: d["modes"]["decode"].update(coreLock=1695))
            self.assert_semantic_refusal(base, "effective core lock")

    def test_lock_rule_removed_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_text(est, base, "identity/gpu-mode.ps1",
                             lambda s: s.replace("$eff = [int]$card2.coreLockCapMHz",
                                                 "# cap application removed"))
            self.assert_semantic_refusal(base, "committed rule anchor")

    def test_ambiguous_default_mode_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_identity_json(
                est, base, "gpu-host-OCTO-L01.json",
                lambda d: d["modes"]["eco"].update(note="DEFAULT. also default"))
            self.assert_semantic_refusal(base, "exactly one DEFAULT mode")

    def test_altered_serve_pinning_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_text(est, base, "identity/launch-fabric-serves.ps1",
                             lambda s: s.replace(DELLB, MSI))
            self.assert_semantic_refusal(base, "raw serve pinning")

    def test_retagged_model_manifest_witness(self):
        """Retagged/repulled model: the manifest bytes move, the capsule digest
        does not. Refused both at the capsule binding and at the semantic level."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            (est / "identity" / "ollama-manifests" / "qwen3.5" / "27b").write_text(
                json.dumps({"synthetic-manifest": "qwen3.5:27b", "retagged": True}),
                encoding="utf-8")
            self.rewrite(base, est, sync_model_digests=False)
            self.assert_capsule_refusal(base, "is not the digest bound for")

            capsule = self._capsule(base)
            recon = V.reconstruct_from_estate(
                base / "estate", capsule["qualification_mode_denominator"]["modes"],
                [m["name"] for m in capsule["model_identities"]])
            with self.assertRaises(V.VerificationFailure) as ctx:
                V.verify_raw_semantics(capsule, recon)
            self.assertIn("ollama manifest digest", str(ctx.exception))

    def test_identity_artifact_dropped_from_denominator_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            (est / "identity" / "gpu-cards.json").unlink()
            self.rewrite(base, est)
            self.assert_capsule_refusal(base, "is not in the evidence denominator")


if __name__ == "__main__":
    unittest.main(verbosity=2)
