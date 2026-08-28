"""Deterministic verifier for the CLAUDE-8 K3 tensor-census capsule.

Zero-model, zero-network. Two verification levels:

  python verify_census_capsule.py
      Verifies the committed capsule alone: reconstructs the 96-shard
      denominator and the final totals (shards 96/96, tensors 497,220,
      NaN 0, Inf 0, structural anomalies 0) from the per-shard rows, and
      recomputes the aggregate root exactly under the declared root rule.

  python verify_census_capsule.py --ledger-root <dir>
      Additionally rehashes the raw per-shard census ledgers (private
      custody, off-repository) against each row's ledger_row_sha256 and
      re-derives every row's tensor/NaN/Inf counts from the raw per-tensor
      statistics. Absence of the private tree does not invalidate the
      committed capsule; it only limits verification to the committed level.

Exit code 0 = verified at the requested level; 1 = any check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPSULE = HERE / "CENSUS-CAPSULE.json"

EXPECTED_TOTALS = {
    "shards": "96/96",
    "tensors": 497220,
    "nan": 0,
    "inf": 0,
    "structural_anomalies": 0,
}


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
    parser.add_argument("--ledger-root", default=None,
                        help="local raw census-ledger root (private custody level)")
    args = parser.parse_args()

    capsule = json.loads(CAPSULE.read_text(encoding="utf-8"))
    if capsule.get("schema") != "estate/k3-tensor-census-capsule@1":
        fail(f"unexpected schema {capsule.get('schema')!r}")

    rows = capsule["rows"]
    denom = capsule["denominator"]
    if denom["shards_total"] != 96 or denom["shards_scanned"] != 96 or denom["missing_shards"]:
        fail(f"denominator is not a closed 96/96: {denom}")
    if len(rows) != 96:
        fail(f"capsule carries {len(rows)} rows, not 96")
    names = [r["shard"] for r in rows]
    if names != sorted(names) or len(set(names)) != 96:
        fail("shard rows are not 96 unique names in sorted order")

    tensors = nan = inf = struct = 0
    for r in rows:
        for field in ("shard", "shard_sha256", "shard_bytes", "hf_expected_match",
                      "tensors", "elements", "dtype_histogram", "nan", "inf",
                      "structural_anomalies", "ledger_row_sha256"):
            if field not in r:
                fail(f"row {r.get('shard')} missing field {field!r}")
        if r["hf_expected_match"] is not True:
            fail(f"row {r['shard']} does not attest HF byte-identity match")
        if len(r["shard_sha256"]) != 64 or len(r["ledger_row_sha256"]) != 64:
            fail(f"row {r['shard']} carries malformed digests")
        if sum(r["dtype_histogram"].values()) != r["tensors"]:
            fail(f"row {r['shard']}: dtype histogram does not sum to tensor count")
        tensors += r["tensors"]
        nan += r["nan"]
        inf += r["inf"]
        struct += r["structural_anomalies"]

    reconstructed = {
        "shards": f"{len(rows)}/96",
        "tensors": tensors,
        "nan": nan,
        "inf": inf,
        "structural_anomalies": struct,
    }
    if reconstructed != capsule["totals"]:
        fail(f"totals do not reconstruct from rows: {reconstructed} != {capsule['totals']}")
    if reconstructed != EXPECTED_TOTALS:
        fail(f"reconstructed totals differ from the claimed census: {reconstructed}")

    agg = hashlib.sha256()
    for r in rows:
        agg.update(f"{r['shard']} {r['shard_sha256']} {r['ledger_row_sha256']}\n".encode())
    root = agg.hexdigest()
    if root != capsule["aggregate_root_sha256"]:
        fail(f"aggregate root does not recompute (got {root})")

    print(f"COMMITTED CAPSULE VERIFIED: root {root}")
    print(f"  {reconstructed['shards']} shards | {tensors} tensors | "
          f"NaN {nan} | Inf {inf} | structural {struct}")

    if args.ledger_root:
        ledger = Path(args.ledger_root)
        problems = []
        for r in rows:
            p = ledger / f"census-{r['shard']}.json"
            if not p.is_file():
                problems.append(f"missing {p.name}")
                continue
            if sha256_file(p) != r["ledger_row_sha256"]:
                problems.append(f"digest mismatch {p.name}")
                continue
            per_tensor = json.loads(p.read_text(encoding="utf-8"))
            if len(per_tensor) != r["tensors"]:
                problems.append(f"{p.name}: tensor count {len(per_tensor)} != row {r['tensors']}")
            if sum(t["nan"] for t in per_tensor.values()) != r["nan"]:
                problems.append(f"{p.name}: NaN sum mismatch")
            if sum(t["inf"] for t in per_tensor.values()) != r["inf"]:
                problems.append(f"{p.name}: Inf sum mismatch")
        if problems:
            fail("raw custody check: " + "; ".join(problems[:10]))
        print(f"RAW CUSTODY VERIFIED: 96 ledgers rehash and re-derive exactly under {ledger}")


if __name__ == "__main__":
    main()
