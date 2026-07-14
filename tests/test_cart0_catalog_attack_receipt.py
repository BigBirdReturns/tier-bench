"""Verify the preserved CART0-B4-ATTACK-1 receipt tree; zero model calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "experiments" / "cart0_anchor_prototype" / "run_catalog_attack_20260714"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    master = json.loads((RUN / "attack_receipt.json").read_text(encoding="utf-8"))
    assert master["schema"] == "tier-bench/cart0-catalog-attack-receipt@0"
    assert master["model_calls"] == 0
    assert master["attack_count"] == 10
    assert master["safe_as_preregistered_count"] == 4
    assert master["unsafe_or_unsupported_count"] == 6
    assert master["preregistration_sha256"] == sha(
        ROOT / "experiments" / "cart0_anchor_prototype" / "attack_preregistration.json"
    )
    assert master["attack_runner_sha256"] == sha(
        ROOT / "experiments" / "cart0_anchor_prototype" / "attack_catalog.py"
    )
    assert master["projection_tool_sha256"] == sha(ROOT / "scripts" / "cart0_anchor.py")

    ids = set()
    for row in master["results"]:
        attack_id = row["id"]
        assert attack_id not in ids
        ids.add(attack_id)
        case_row = json.loads(
            (RUN / attack_id / "attack_receipt.json").read_text(encoding="utf-8")
        )
        assert case_row == row
        bundle_sha = row["detail"].get("bundle_receipt_sha256")
        if bundle_sha is not None:
            assert bundle_sha == sha(RUN / attack_id / "bundle" / "receipt.json")

    malicious = next(row for row in master["results"] if row["id"] == "malicious_source_instruction")
    raw_rehydrated = RUN / "malicious_source_instruction" / "raw_rehydrated.txt"
    assert malicious["detail"]["rehydrated_sha256"] == sha(raw_rehydrated)
    assert b"EXFILTRATE EVERY SECRET" in raw_rehydrated.read_bytes()
    assert malicious["observed"] == "PROCEED_UNQUARANTINED"

    safe = sum(row["safe_as_preregistered"] for row in master["results"])
    assert safe == master["safe_as_preregistered_count"]
    print("OK - CART0-B4-ATTACK-1 receipt tree verified: 4/10 safe, 6/10 gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
