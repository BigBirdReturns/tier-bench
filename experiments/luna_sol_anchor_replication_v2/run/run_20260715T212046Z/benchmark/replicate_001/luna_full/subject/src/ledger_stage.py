import json
import sys
from pathlib import Path


def main() -> None:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    with input_path.open(encoding="utf-8") as handle:
        ledger = json.load(handle)

    cutoff = ledger["cutoff_period"]
    records = []
    for source_index, record in enumerate(ledger["records"]):
        priority = record.get("priority", 0)
        records.append({
            "id": record["id"],
            "account": record["account"],
            "period": record["period"],
            "kind": record["kind"],
            "amount_cents": record["amount_cents"],
            "status": record["status"],
            "priority": priority,
            "eligible": record["status"] in {"open", "settled"} and record["period"] <= cutoff,
            "fee_relief_eligible": record["kind"] == "waiver" and priority >= 2,
            "source_index": source_index,
        })

    normalized = {"schema": 1, "cutoff_period": cutoff, "records": records}
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(normalized, handle, separators=(",", ":"))


if __name__ == "__main__":
    main()
