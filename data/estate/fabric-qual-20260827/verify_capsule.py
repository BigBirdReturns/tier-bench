"""Deterministic verifier for the CLAUDE-5 fabric qualification capsule.

Zero-model, zero-network. Three verification levels, each strictly stronger:

  CAPSULE_ONLY_VERIFIED
      (default) The committed capsule alone: required fields present, the
      aggregate evidence root recomputes exactly from the embedded receipt
      manifest under the declared root rule, the summary digest is a member
      of the manifest, and the phase-result table covers the exact declared
      mode denominator.

  RAW_BYTES_VERIFIED
      (--estate-root) Additionally rehashes every raw private evidence file
      against the embedded manifest. Proves the named private files carry the
      expected bytes - and nothing more.

  RAW_SEMANTICS_VERIFIED
      (--estate-root, reached only after RAW_BYTES_VERIFIED) Parses
      QUAL-SUMMARY.json and every decision-bearing phase receipt, RECONSTRUCTS
      the decision-critical claims from raw receipt content alone (phase
      denominator and modes, run counts, active/excluded device identities,
      model identities, throughput/timing statistics, concurrency retention,
      VRAM allocation, terminal verdict, claim-boundary structure), and
      refuses on ANY semantic disagreement with the committed capsule even
      when every raw file digest matches.

CLAUDE-5 repository closure is supported only at RAW_SEMANTICS_VERIFIED on a
host holding the raw estate tree; a fresh checkout reaches
CAPSULE_ONLY_VERIFIED, which authenticates the committed claims and their
binding but cannot re-derive them.

Exit code 0 = verified at the requested level; 1 = any check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CAPSULE = HERE / "CAPSULE.json"

REQUIRED_FIELDS = [
    "schema",
    "claim_id",
    "claim",
    "host",
    "date",
    "qualification_mode_denominator",
    "phase_results",
    "phase_execution",
    "gpu_identities",
    "model_identities",
    "summary_receipt_sha256",
    "receipt_manifest_sha256",
    "aggregate_evidence_root_sha256",
    "aggregate_root_rule",
    "claim_boundary",
    "raw_evidence_custody",
]


class VerificationFailure(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def refuse(msg: str) -> None:
    raise VerificationFailure(msg)


def parse_gpu_lines(lines: list[str]) -> dict[int, dict]:
    """Parse 'index, NNN MiB, U %, P W, T' nvidia-smi rows."""
    out = {}
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        idx = int(parts[0])
        out[idx] = {
            "mib": int(parts[1].split()[0]),
            "util_pct": int(parts[2].split()[0]),
            "power_w": float(parts[3].split()[0]),
            "temp_c": int(parts[4]),
        }
    return out


def median_1dp(values: list[float]) -> float:
    return round(statistics.median(values), 1)


def verify_capsule_only(capsule: dict) -> None:
    for field in REQUIRED_FIELDS:
        if field not in capsule:
            refuse(f"capsule missing required field {field!r}")
    if capsule["schema"] != "estate/fabric-qual-capsule@2":
        refuse(f"unexpected schema {capsule['schema']!r}")

    manifest = capsule["receipt_manifest_sha256"]
    if not manifest or not isinstance(manifest, dict):
        refuse("receipt manifest empty or malformed")
    for name, digest in manifest.items():
        if not isinstance(digest, str) or len(digest) != 64:
            refuse(f"manifest entry {name!r} is not a sha256 hex digest")

    lines = "".join(f"{k} {v}\n" for k, v in sorted(manifest.items()))
    root = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    if root != capsule["aggregate_evidence_root_sha256"]:
        refuse("aggregate evidence root does not recompute from the manifest "
               f"(recomputed {root})")

    if capsule["summary_receipt_sha256"] != manifest.get("QUAL-SUMMARY.json"):
        refuse("summary receipt digest is not the manifest's QUAL-SUMMARY.json entry")

    denom = capsule["qualification_mode_denominator"]
    modes = denom["modes"]
    if denom["modes_total"] != len(modes):
        refuse("mode denominator count does not match the mode list")
    if set(capsule["phase_results"]) != set(modes):
        refuse("phase results do not cover exactly the declared modes")
    if set(capsule["phase_execution"]) != set(modes):
        refuse("phase execution records do not cover exactly the declared modes")
    receipt_names = {n for n in manifest if n.startswith("receipts/")}
    if len(receipt_names) != len(modes):
        refuse("per-receipt manifest does not carry one receipt per declared mode")
    boundary = capsule["claim_boundary"]
    if not boundary.get("claims") or not boundary.get("non_claims"):
        refuse("claim boundary must state both claims and non-claims")


def verify_raw_bytes(capsule: dict, estate_root: Path) -> None:
    manifest = capsule["receipt_manifest_sha256"]
    missing, mismatched = [], []
    for name, expected in sorted(manifest.items()):
        p = estate_root / name
        if not p.is_file():
            missing.append(name)
        elif sha256_file(p) != expected:
            mismatched.append(name)
    if missing or mismatched:
        refuse(f"raw custody bytes: missing={missing} mismatched={mismatched}")


def reconstruct_from_estate(estate_root: Path, modes: list[str]) -> dict:
    """Rebuild the decision-critical claims from raw receipt content ONLY."""
    summary = json.loads((estate_root / "QUAL-SUMMARY.json").read_text(encoding="utf-8"))
    recon: dict = {
        "summary_phase_denominator": sorted(summary.get("phases", {})),
        "terminal_verdict_pass": str(summary.get("verdict", "")).startswith("PASS"),
        "host": summary.get("host"),
        "date": summary.get("date"),
        "phases": {},
    }
    for mode in modes:
        rp = estate_root / "receipts" / f"{mode}.json"
        r = json.loads(rp.read_text(encoding="utf-8"))
        during = parse_gpu_lines(r["gpu_during"])
        active = sorted(i for i, g in during.items() if g["mib"] > 0)
        excluded = sorted(i for i, g in during.items() if g["mib"] == 0)
        phase: dict = {
            "phase_name": r["phase"],
            "model": r["model"],
            "date": str(r["ts"])[:10],
            "runs": len(r["raw"]),
            "declared_n": r["primary"]["n"],
            "decode_median": median_1dp([x["decode_tok_s"] for x in r["raw"]]),
            "declared_decode_median": r["primary"]["decode_median"],
            "prefill_median": r["primary"]["prefill_median"],
            "active_devices": active,
            "excluded_devices": excluded,
            "vram_gb_during": {i: round(g["mib"] / 1000, 1) for i, g in during.items()
                               if g["mib"] > 0},
        }
        if "secondary" in r:
            phase["secondary_runs"] = len(r.get("raw_secondary", []))
            phase["secondary_decode_median"] = median_1dp(
                [x["decode_tok_s"] for x in r["raw_secondary"]])
            phase["declared_secondary_decode_median"] = r["secondary"]["decode_median"]
            phase["aggregate_decode"] = r["aggregate_decode"]
        recon["phases"][mode] = phase
    return recon


def verify_raw_semantics(capsule: dict, recon: dict) -> None:
    """Refuse on ANY disagreement between capsule claims and raw semantics."""
    denom = capsule["qualification_mode_denominator"]
    modes = denom["modes"]

    if sorted(recon["summary_phase_denominator"]) != sorted(modes):
        refuse("semantic: summary phase denominator "
               f"{recon['summary_phase_denominator']} != capsule modes {sorted(modes)}")
    if not recon["terminal_verdict_pass"]:
        refuse("semantic: raw summary verdict is not a PASS verdict")
    if recon["host"] != capsule["host"]:
        refuse(f"semantic: host {recon['host']!r} != capsule {capsule['host']!r}")
    if recon["date"] != capsule["date"]:
        refuse(f"semantic: date {recon['date']!r} != capsule {capsule['date']!r}")

    for mode in modes:
        p = recon["phases"][mode]
        claim = capsule["phase_results"][mode]
        execution = capsule["phase_execution"][mode]

        if p["phase_name"] != mode:
            refuse(f"semantic[{mode}]: receipt phase field is {p['phase_name']!r}")
        if p["model"] != claim["model"]:
            refuse(f"semantic[{mode}]: model {p['model']!r} != capsule {claim['model']!r}")
        if p["date"] != capsule["date"]:
            refuse(f"semantic[{mode}]: receipt date {p['date']} != capsule date")
        if p["runs"] != denom["runs_per_mode"] or p["declared_n"] != denom["runs_per_mode"]:
            refuse(f"semantic[{mode}]: run count raw={p['runs']} declared={p['declared_n']} "
                   f"!= capsule runs_per_mode {denom['runs_per_mode']}")
        if p["decode_median"] != p["declared_decode_median"]:
            refuse(f"semantic[{mode}]: recomputed decode median {p['decode_median']} "
                   f"!= receipt-declared {p['declared_decode_median']}")

        if p["active_devices"] != execution["active_devices"]:
            refuse(f"semantic[{mode}]: active devices {p['active_devices']} "
                   f"!= capsule {execution['active_devices']}")
        if p["excluded_devices"] != execution["excluded_devices"]:
            refuse(f"semantic[{mode}]: excluded devices {p['excluded_devices']} "
                   f"!= capsule {execution['excluded_devices']}")

        if "aggregate_decode_tok_s" in claim:
            if p["secondary_runs"] != denom["runs_per_mode"]:
                refuse(f"semantic[{mode}]: secondary run count {p['secondary_runs']}")
            if p["secondary_decode_median"] != p["declared_secondary_decode_median"]:
                refuse(f"semantic[{mode}]: recomputed secondary median disagrees")
            aggregate = round(p["decode_median"] + p["secondary_decode_median"], 1)
            if aggregate != claim["aggregate_decode_tok_s"] or aggregate != p["aggregate_decode"]:
                refuse(f"semantic[{mode}]: aggregate {aggregate} != capsule "
                       f"{claim['aggregate_decode_tok_s']} / receipt {p['aggregate_decode']}")
            single = capsule["phase_results"]["single-27b-msi"]["decode_tok_s_median"]
            scaling = round(aggregate / single, 2)
            if scaling != claim["scaling_x"]:
                refuse(f"semantic[{mode}]: scaling {scaling} != capsule {claim['scaling_x']}")
            retention = round(min(p["decode_median"], p["secondary_decode_median"])
                              / single * 100, 1)
            if retention != claim["retention_pct"]:
                refuse(f"semantic[{mode}]: concurrency retention {retention} "
                       f"!= capsule {claim['retention_pct']}")
        else:
            if p["decode_median"] != claim["decode_tok_s_median"]:
                refuse(f"semantic[{mode}]: decode median {p['decode_median']} "
                       f"!= capsule {claim['decode_tok_s_median']}")

        if "prefill_tok_s_median" in claim and p["prefill_median"] != claim["prefill_tok_s_median"]:
            refuse(f"semantic[{mode}]: prefill median {p['prefill_median']} "
                   f"!= capsule {claim['prefill_tok_s_median']}")

        if "vram_split_gb" in claim:
            got = [p["vram_gb_during"][i] for i in sorted(p["vram_gb_during"])]
            want = sorted(claim["vram_split_gb"], reverse=True)
            if sorted(got, reverse=True) != want:
                refuse(f"semantic[{mode}]: VRAM allocation {got} != capsule "
                       f"{claim['vram_split_gb']}")


def run(capsule_path: Path, estate_root: Path | None) -> str:
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    verify_capsule_only(capsule)
    level = "CAPSULE_ONLY_VERIFIED"
    print(f"CAPSULE_ONLY_VERIFIED: root {capsule['aggregate_evidence_root_sha256']}")
    if estate_root is not None:
        verify_raw_bytes(capsule, estate_root)
        level = "RAW_BYTES_VERIFIED"
        print(f"RAW_BYTES_VERIFIED: {len(capsule['receipt_manifest_sha256'])} files "
              f"rehash exactly under {estate_root}")
        recon = reconstruct_from_estate(
            estate_root, capsule["qualification_mode_denominator"]["modes"])
        verify_raw_semantics(capsule, recon)
        level = "RAW_SEMANTICS_VERIFIED"
        print("RAW_SEMANTICS_VERIFIED: raw receipt contents support every "
              "decision-critical capsule claim (denominator, modes, run counts, "
              "device identities, models, medians, aggregate/scaling/retention, "
              "VRAM, terminal verdict)")
        print("CLAUDE-5 repository closure: SUPPORTED at this level")
    else:
        print("note: CLAUDE-5 closure support requires RAW_SEMANTICS_VERIFIED "
              "(--estate-root on the custody host)")
    return level


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estate-root", default=None,
                        help="local raw-evidence root (raw bytes + semantics levels)")
    parser.add_argument("--capsule", default=None,
                        help="capsule path override (verification testing)")
    args = parser.parse_args()
    capsule_path = Path(args.capsule) if args.capsule else DEFAULT_CAPSULE
    estate = Path(args.estate_root) if args.estate_root else None
    try:
        run(capsule_path, estate)
    except VerificationFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
