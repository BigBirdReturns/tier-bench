from __future__ import annotations
import json
import sys
from pathlib import Path

ALLOWED_STATUS = {"open", "settled"}
KINDS = {"invoice", "credit", "fee", "waiver"}

def normalize(raw: dict) -> dict:
    records = []
    for index, item in enumerate(raw["records"]):
        amount = int(item["amount_cents"])
        kind = item["kind"]
        status = item["status"]
        period = int(item["period"])
        priority = int(item.get("priority", 0))
        if amount < 0 or kind not in KINDS:
            raise ValueError("invalid ledger record")
        records.append({
            "id": str(item["id"]), "account": str(item["account"]),
            "period": period, "kind": kind, "amount_cents": amount,
            "status": status, "priority": priority,
            "eligible": status in ALLOWED_STATUS and period <= int(raw["cutoff_period"]),
            "fee_relief_eligible": kind == "waiver" and priority >= 2,
            "source_index": index,
        })
    return {"schema": 1, "cutoff_period": int(raw["cutoff_period"]), "records": records}

def main() -> int:
    source, destination = map(Path, sys.argv[1:3])
    destination.write_text(json.dumps(normalize(json.loads(source.read_text())), sort_keys=True) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
