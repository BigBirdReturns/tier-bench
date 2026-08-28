"""Deterministic verifier for the CLAUDE-5 fabric qualification capsule.

Zero-model, zero-network. Two verification levels:

  python verify_capsule.py
      Verifies the committed capsule alone: schema fields present, the
      aggregate evidence root recomputes exactly from the embedded receipt
      manifest under the declared root rule, the summary digest is a member
      of the manifest, and the phase result table covers the exact declared
      mode denominator.

  python verify_capsule.py --estate-root <dir>
      Additionally rehashes the raw local evidence files (private custody,
      off-repository) against the embedded manifest. This level can only run
      on a host that holds the raw estate tree; absence of that tree does not
      invalidate the committed capsule, it only limits verification to the
      committed level.

Exit code 0 = verified at the requested level; 1 = any check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPSULE = HERE / "CAPSULE.json"

REQUIRED_FIELDS = [
    "schema",
    "claim_id",
    "claim",
    "host",
    "date",
    "qualification_mode_denominator",
    "phase_results",
    "gpu_identities",
    "model_identities",
    "summary_receipt_sha256",
    "receipt_manifest_sha256",
    "aggregate_evidence_root_sha256",
    "aggregate_root_rule",
    "claim_boundary",
    "raw_evidence_custody",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estate-root", default=None,
                        help="local raw-evidence root (private custody level)")
    args = parser.parse_args()

    capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))

    for field in REQUIRED_FIELDS:
        if field not in capsule:
            fail(f"capsule missing required field {field!r}")

    if capsule["schema"] != "estate/fabric-qual-capsule@1":
        fail(f"unexpected schema {capsule['schema']!r}")

    manifest = capsule["receipt_manifest_sha256"]
    if not manifest or not isinstance(manifest, dict):
        fail("receipt manifest empty or malformed")
    for name, digest in manifest.items():
        if not isinstance(digest, str) or len(digest) != 64:
            fail(f"manifest entry {name!r} is not a sha256 hex digest")

    lines = "".join(f"{k} {v}\n" for k, v in sorted(manifest.items()))
    root = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    if root != capsule["aggregate_evidence_root_sha256"]:
        fail("aggregate evidence root does not recompute from the manifest "
             f"(recomputed {root})")

    if capsule["summary_receipt_sha256"] != manifest.get("QUAL-SUMMARY.json"):
        fail("summary receipt digest is not the manifest's QUAL-SUMMARY.json entry")

    denom = capsule["qualification_mode_denominator"]
    modes = denom["modes"]
    if denom["modes_total"] != len(modes):
        fail("mode denominator count does not match the mode list")
    declared = set(capsule["phase_results"])
    if declared != set(modes):
        fail(f"phase results {sorted(declared)} do not cover exactly the "
             f"declared modes {sorted(modes)}")
    receipt_names = {n for n in manifest if n.startswith("receipts/")}
    if len(receipt_names) != len(modes):
        fail("per-receipt manifest does not carry one receipt per declared mode")

    print(f"COMMITTED CAPSULE VERIFIED: root {root}")
    print(f"  claim {capsule['claim_id']} | {denom['modes_total']} modes | "
          f"{len(manifest)} bound evidence files")

    if args.estate_root:
        est = Path(args.estate_root)
        missing, mismatched = [], []
        for name, expected in sorted(manifest.items()):
            p = est / name
            if not p.is_file():
                missing.append(name)
            elif sha256_file(p) != expected:
                mismatched.append(name)
        if missing or mismatched:
            fail(f"raw custody check: missing={missing} mismatched={mismatched}")
        print(f"RAW CUSTODY VERIFIED: {len(manifest)} files rehash exactly under {est}")


if __name__ == "__main__":
    main()
