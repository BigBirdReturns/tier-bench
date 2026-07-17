from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

def rollup(normalized: dict) -> dict:
    grouped = defaultdict(lambda: {"invoice": 0, "credit": 0, "fee": 0, "relief": 0, "count": 0})
    for record in normalized["records"]:
        if not record["eligible"]:
            continue
        bucket = grouped[record["account"]]
        bucket["count"] += 1
        if record["kind"] == "invoice":
            bucket["invoice"] += record["amount_cents"]
        elif record["kind"] == "credit":
            bucket["credit"] -= record["amount_cents"]
        elif record["kind"] == "fee":
            bucket["fee"] += record["amount_cents"]
        elif record["fee_relief_eligible"]:
            bucket["relief"] += record["amount_cents"]
    accounts = []
    for account in sorted(grouped):
        bucket = grouped[account]
        adjusted_fee = max(0, bucket["fee"] - bucket["relief"])
        accounts.append({
            "account": account,
            "invoice_cents": bucket["invoice"],
            "credit_cents": bucket["credit"],
            "fee_cents": bucket["fee"],
            "relief_cents": bucket["relief"],
            "adjusted_fee_cents": adjusted_fee,
            "due_cents": bucket["invoice"] + bucket["credit"] + adjusted_fee,
            "record_count": bucket["count"],
        })
    return {"accounts": accounts, "grand_total_cents": sum(a["due_cents"] for a in accounts)}

def main() -> int:
    normalized = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(rollup(normalized), sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
