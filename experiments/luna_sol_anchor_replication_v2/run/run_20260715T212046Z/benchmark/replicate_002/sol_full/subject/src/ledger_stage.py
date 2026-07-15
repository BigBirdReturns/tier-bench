import json
import sys
from pathlib import Path


def main() -> None:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    ledger = json.loads(input_path.read_text(encoding="utf-8"))
    cutoff = ledger["cutoff_period"]

    records = []
    for source_index, record in enumerate(ledger["records"]):
        priority = record.get("priority", 0)
        records.append(
            {
                "id": record["id"],
                "account": record["account"],
                "period": record["period"],
                "kind": record["kind"],
                "amount_cents": record["amount_cents"],
                "status": record["status"],
                "priority": priority,
                "eligible": (
                    record["status"] in {"open", "settled"}
                    and record["period"] <= cutoff
                ),
                "fee_relief_eligible": (
                    record["kind"] == "waiver" and priority >= 2
                ),
                "source_index": source_index,
            }
        )

    normalized = {"schema": 1, "cutoff_period": cutoff, "records": records}
    output_path.write_text(
        json.dumps(normalized, separators=(",", ":")), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
