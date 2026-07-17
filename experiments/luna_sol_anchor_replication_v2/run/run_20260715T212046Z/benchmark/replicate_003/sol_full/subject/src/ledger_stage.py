import json
import sys


def main() -> None:
    input_path, output_path = sys.argv[1:]
    with open(input_path, encoding="utf-8") as source:
        ledger = json.load(source)

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
                "eligible": record["status"] in {"open", "settled"}
                and record["period"] <= cutoff,
                "fee_relief_eligible": record["kind"] == "waiver"
                and priority >= 2,
                "source_index": source_index,
            }
        )

    with open(output_path, "w", encoding="utf-8") as destination:
        json.dump(
            {"schema": 1, "cutoff_period": cutoff, "records": records},
            destination,
            separators=(",", ":"),
        )


if __name__ == "__main__":
    main()
