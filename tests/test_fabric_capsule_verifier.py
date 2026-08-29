"""Hostile witnesses for the CLAUDE-5 fabric capsule verifier.

Each witness builds a synthetic estate root whose raw artifacts are INTERNALLY
VALID and CORRECTLY REHASHED (the capsule manifest and aggregate root are
recomputed so RAW_BYTES_VERIFIED passes), but whose contents contradict the
committed capsule in exactly one decision-critical field. Every witness must
refuse. Zero-model, zero-network.

Witness coverage:
  denominator/statistics  phase denominator, run count, decode median,
                          recomputed-decode-vs-declared, recomputed-prefill-
                          vs-declared, per-card median values, aggregate/
                          retention, VRAM, terminal verdict, date
  per-card role set       omitted, additional, renamed and swapped card roles;
                          per-card medians claimed for a single-stream phase
  workload                per-sample token count, driver generation constant
  identity                GPU UUID (driver source and device attestation),
                          swapped card roles via serve pinning, altered core
                          lock cap, retagged ollama model manifest, driver
                          serve dispatch
  model denominator       a dispatched model with no identity, with no manifest
                          artifact, an identity no phase dispatches, a bound
                          manifest no identity claims, a phase naming a model
                          the driver does not dispatch, a receipt naming a model
                          the capsule has no identity for
  executable lock rule    the committed min-rule present only as a comment,
                          only inside a string, only inside an uncalled
                          function; mode operand alone; cap operand alone; an
                          unconditional cap; an inverted (max) comparison;
                          unrelated operands; the computed lock discarded
                          before application; the lock never applied
  attestation binding     another host, another class, another schema, an
                          unexpected device denominator, another claim id, a
                          missing supplemental statement, a readback timestamp
                          that predates the run it attests
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

def gpu_mode_src(compute: str) -> str:
    """A synthetic core-lock applier whose per-card computation is `compute`.

    The surrounding shape mirrors the real applier: a per-device loop that
    stores its computed lock into $lockByIdx, and a later nvidia-smi -lgc
    application that reads it back. Only the computation varies between
    witnesses, so every refusal is attributable to the executable rule.
    """
    return f"""# synthetic core-lock applier (fixture)
# Effective core lock per card = min(mode's lock, the card's coreLockCapMHz).
$lockByIdx = @{{}}
foreach ($line in (nvidia-smi --query-gpu=index,uuid --format=csv,noheader)) {{
    $f2 = $line -split ',\\s*'; $i2 = [int]$f2[0]; $u2 = $f2[1].Trim()
    $card2 = $registry.cards.$u2
{compute}
    $lockByIdx[$i2] = $eff
}}
foreach ($i in $idx) {{
    if ($lockByIdx[$i] -gt 0) {{ nvidia-smi -i $i -lgc "210,$($lockByIdx[$i])" | Out-Null }}
}}
"""


# the committed rule, on the executable path
LOCK_MIN_COMPUTE = """    $eff = $m.coreLock
    if ($eff -gt 0 -and $registry) {
        if ($card2 -and [int]$card2.coreLockCapMHz -gt 0 -and [int]$card2.coreLockCapMHz -lt $eff) {
            $eff = [int]$card2.coreLockCapMHz
        }
    }"""

GPU_MODE_SRC = gpu_mode_src(LOCK_MIN_COMPUTE)


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
        "attestation_id": "CLAUDE-5-IDENTITY-001",
        "supplements": {
            "capsule_claim_id": "CLAUDE-5",
            "statement": "Supplements the qualification run; re-measures nothing.",
        },
        "host": "OCTO-L01",
        "observed_utc": "2026-08-29T01:56:08Z",
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

    # ------------- executable core-lock rule (never substring presence) ------

    def _lock_witness(self, source: str, fragment: str = "core-lock rule"):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            (est / "identity" / "gpu-mode.ps1").write_text(source, encoding="utf-8")
            self.rewrite(base, est)
            self.assert_semantic_refusal(base, fragment)

    def test_lock_rule_removed_witness(self):
        self._lock_witness(gpu_mode_src("""    $eff = $m.coreLock
    # cap application removed"""))

    def test_lock_rule_only_in_a_comment_witness(self):
        """The committed line is present verbatim - as a comment. The line the
        applier actually executes sets an unrelated constant."""
        self._lock_witness(gpu_mode_src("""    $eff = $m.coreLock
    if ($card2 -and [int]$card2.coreLockCapMHz -lt $eff) {
        # $eff = [int]$card2.coreLockCapMHz
        $eff = 1695
    }"""))

    def test_lock_rule_only_in_a_string_witness(self):
        self._lock_witness(gpu_mode_src("""    $eff = $m.coreLock
    Write-Output "$eff = [int]$card2.coreLockCapMHz"
"""))

    def test_lock_rule_only_in_an_unused_function_witness(self):
        self._lock_witness("""# the rule exists, in a function nothing ever calls
function Get-EffectiveCoreLock {
    $eff = $m.coreLock
    if ([int]$card2.coreLockCapMHz -gt 0 -and [int]$card2.coreLockCapMHz -lt $eff) {
        $eff = [int]$card2.coreLockCapMHz
    }
    return $eff
}
$lockByIdx = @{}
foreach ($line in (nvidia-smi --query-gpu=index,uuid --format=csv,noheader)) {
    $i2 = [int]($line -split ',\\s*')[0]
    $eff = $m.coreLock
    $lockByIdx[$i2] = $eff
}
foreach ($i in $idx) { nvidia-smi -i $i -lgc "210,$($lockByIdx[$i])" | Out-Null }
""")

    def test_lock_rule_mode_operand_only_witness(self):
        self._lock_witness(gpu_mode_src("    $eff = $m.coreLock"))

    def test_lock_rule_cap_operand_only_witness(self):
        self._lock_witness(gpu_mode_src("    $eff = [int]$card2.coreLockCapMHz"))

    def test_lock_rule_unconditional_cap_witness(self):
        """Both operands present, but the cap is applied unconditionally - that
        is not a minimum."""
        self._lock_witness(gpu_mode_src("""    $eff = $m.coreLock
    $eff = [int]$card2.coreLockCapMHz"""))

    def test_lock_rule_inverted_comparison_witness(self):
        """min() turned into max(): the cap is taken when it EXCEEDS the mode
        lock, so a degraded card could be driven above its ceiling."""
        self._lock_witness(gpu_mode_src("""    $eff = $m.coreLock
    if ([int]$card2.coreLockCapMHz -gt $eff) {
        $eff = [int]$card2.coreLockCapMHz
    }"""))

    def test_lock_rule_unrelated_operands_witness(self):
        self._lock_witness(gpu_mode_src("""    $eff = $m.powerLimit
    if ([int]$card2.memOffsetMHz -lt $eff) {
        $eff = [int]$card2.memOffsetMHz
    }"""))

    def test_lock_rule_bypassed_before_application_witness(self):
        """The minimum is computed correctly and then discarded before the
        value reaches nvidia-smi."""
        self._lock_witness(gpu_mode_src("""    $eff = $m.coreLock
    if ($card2 -and [int]$card2.coreLockCapMHz -lt $eff) {
        $eff = [int]$card2.coreLockCapMHz
    }
    $eff = $m.coreLock"""))

    def test_lock_rule_never_applied_witness(self):
        """The minimum is computed but the applier locks the mode value."""
        self._lock_witness("""$lockByIdx = @{}
foreach ($line in (nvidia-smi --query-gpu=index,uuid --format=csv,noheader)) {
    $i2 = [int]($line -split ',\\s*')[0]
    $card2 = $registry.cards.$u2
    $eff = $m.coreLock
    if ([int]$card2.coreLockCapMHz -lt $eff) {
        $eff = [int]$card2.coreLockCapMHz
    }
    $lockByIdx[$i2] = $m.coreLock
}
foreach ($i in $idx) { nvidia-smi -i $i -lgc "210,$($lockByIdx[$i])" | Out-Null }
""")

    def test_min_rule_applier_parses_to_the_committed_rule(self):
        """The positive control: a well-formed applier resolves to the exact
        min-rule, its two operands, and the map that reaches nvidia-smi."""
        rule = V.parse_lock_rule_ps(GPU_MODE_SRC)
        self.assertEqual(rule["mode_object"], "m")
        self.assertEqual(rule["card_object"], "card2")
        self.assertEqual(rule["lock_map"], "lockByIdx")
        self.assertIn("min(", rule["rule"])

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

    # ---------------- model identity denominator ----------------
    #
    # The model set must be DERIVED from the phases (driver dispatch + receipts)
    # and must equal the capsule's identities and the bound manifests exactly.
    # An omission is as fatal as a contradiction.

    @staticmethod
    def add_manifest(est: Path, name: str):
        repo, tag = name.split(":")
        p = est / "identity" / "ollama-manifests" / repo / tag
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"synthetic-manifest": name}), encoding="utf-8")

    @staticmethod
    def drop_identity(capsule: dict, name: str):
        capsule["model_identities"] = [m for m in capsule["model_identities"]
                                       if m["name"] != name]

    def test_dispatched_model_without_identity_witness(self):
        """The 70B phase still runs in the driver, the receipt and the capsule,
        but its model identity is gone and the root recomputes cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_capsule(base, est,
                                lambda c: self.drop_identity(c, "deepseek-r1:70b"))
            self.assert_semantic_refusal(base, "missing=['deepseek-r1:70b']")

    def test_dispatched_model_manifest_removed_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_capsule(base, est,
                                lambda c: self.drop_identity(c, "deepseek-r1:70b"))
            (est / "identity" / "ollama-manifests" / "deepseek-r1" / "70b").unlink()
            self.rewrite(base, est)
            self.assert_semantic_refusal(base, "absent from the raw estate")

    def test_additional_unused_model_identity_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.add_manifest(est, "qwen3.5:8b")
            self.mutate_capsule(base, est, lambda c: c["model_identities"].append(
                {"name": "qwen3.5:8b", "ollama_manifest_sha256": "0" * 64,
                 "ollama_manifest_path": "identity/ollama-manifests/qwen3.5/8b"}))
            self.assert_semantic_refusal(base, "additional=['qwen3.5:8b']")

    def test_bound_manifest_without_identity_witness(self):
        """An extra manifest artifact in the denominator that no dispatched
        model corresponds to."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.add_manifest(est, "qwen3.5:8b")
            self.rewrite(base, est)
            self.assert_semantic_refusal(base, "bound ollama manifest artifacts")

    def test_phase_names_model_absent_from_driver_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.add_manifest(est, "deepseek-r1:32b")
            self.mutate_text(est, base, "fabric_qual.py",
                             lambda s: s.replace('"deepseek-r1:70b"',
                                                 '"deepseek-r1:32b"'))
            self.assert_semantic_refusal(base, "capsule phase results name models")

    def test_receipt_names_model_without_capsule_identity_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.add_manifest(est, "deepseek-r1:32b")
            self.mutate_text(est, base, "fabric_qual.py",
                             lambda s: s.replace('"deepseek-r1:70b"',
                                                 '"deepseek-r1:32b"'))
            self.mutate_receipt(est, base, "split-70b-r1",
                                lambda r: r.update(model="deepseek-r1:32b"))
            self.mutate_capsule(base, est, lambda c: c["phase_results"][
                "split-70b-r1"].update(model="deepseek-r1:32b"))
            self.assert_semantic_refusal(base, "additional=['deepseek-r1:70b']")

    # ---------------- device attestation binding ----------------

    def _attestation_witness(self, mutate, fragment: str):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_identity_json(est, base, "IDENTITY-ATTESTATION.json", mutate)
            self.assert_semantic_refusal(base, fragment)

    def test_attestation_names_another_host_witness(self):
        """Same UUID rows, rehashed cleanly, but the attestation states it
        belongs to OCTO-W01."""
        self._attestation_witness(lambda d: d.update(host="OCTO-W01"),
                                  "which is not the capsule's host")

    def test_attestation_class_witness(self):
        self._attestation_witness(
            lambda d: d.update(observation_class="PER_RUN_TELEMETRY"),
            "attestation class")

    def test_attestation_schema_witness(self):
        self._attestation_witness(
            lambda d: d.update(schema="estate/fabric-identity-attestation@2"),
            "attestation schema")

    def test_attestation_device_denominator_witness(self):
        self._attestation_witness(
            lambda d: d["nvidia_smi_rows"].append(
                "2, GPU-deadbeef-0000-0000-0000-000000000000, "
                "NVIDIA GeForce RTX 3090, 00000000:E1:00.0, 24576 MiB"),
            "reads back 3 devices")

    def test_attestation_claim_binding_witness(self):
        self._attestation_witness(
            lambda d: d["supplements"].update(capsule_claim_id="CLAUDE-11"),
            "attestation supplements claim")

    def test_attestation_supplemental_statement_witness(self):
        self._attestation_witness(
            lambda d: d["supplements"].pop("statement"),
            "no supplemental statement")

    def test_attestation_timestamp_classification_witness(self):
        """A POST_RUN_READBACK that predates the run it reads back."""
        self._attestation_witness(
            lambda d: d.update(observed_utc="2026-08-26T00:00:00Z"),
            "precedes the qualification date")

    def test_attested_denominator_is_capsule_level_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_capsule(base, est, lambda c: c["identity_evidence"].update(
                attested_device_denominator=3))
            self.assert_capsule_refusal(base, "attested device denominator")

    def test_identity_evidence_key_removed_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_capsule(base, est,
                                lambda c: c["identity_evidence"].pop("attestation_class"))
            self.assert_capsule_refusal(base, "identity evidence missing required key")

    # ---------------- per-card median role denominator ----------------

    def _per_card_witness(self, mutate, fragment: str):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            est, _ = build_fixture(base)
            self.mutate_capsule(base, est, mutate)
            self.assert_semantic_refusal(base, fragment)

    def test_per_card_median_role_omitted_witness(self):
        """The capsule publishes one card's median and claims per-card binding
        for a phase that drove two pinned serves."""
        self._per_card_witness(
            lambda c: c["phase_results"]["double-27b-both"]["per_card_medians"]
            .pop("dell_b"), "per-card median roles")

    def test_per_card_median_role_added_witness(self):
        self._per_card_witness(
            lambda c: c["phase_results"]["double-27b-both"]["per_card_medians"]
            .update(phantom=36.1), "per-card median roles")

    def test_per_card_median_role_renamed_witness(self):
        def rename(c):
            medians = c["phase_results"]["double-27b-both"]["per_card_medians"]
            medians["msi_card"] = medians.pop("msi")
        self._per_card_witness(rename, "per-card median roles")

    def test_per_card_median_roles_swapped_witness(self):
        def swap(c):
            medians = c["phase_results"]["double-27b-both"]["per_card_medians"]
            medians["msi"], medians["dell_b"] = medians["dell_b"], medians["msi"]
        self._per_card_witness(swap, "per-card median for")

    def test_single_stream_phase_claims_per_card_medians_witness(self):
        self._per_card_witness(
            lambda c: c["phase_results"]["single-27b-msi"].update(
                per_card_medians={"msi": 33.8}), "single stream")


if __name__ == "__main__":
    unittest.main(verbosity=2)
