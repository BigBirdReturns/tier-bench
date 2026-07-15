import json
import sys
from pathlib import Path


def main() -> None:
    normalized = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    totals = {}

    for record in normalized["records"]:
        if not record["eligible"]:
            continue

        kind = record["kind"]
        # A settled waiver has already been consumed; only open, relief-eligible
        # waivers affect the current rollup.
        if kind == "waiver" and not (
            record["fee_relief_eligible"] and record["status"] == "open"
        ):
            continue

        account = record["account"]
        values = totals.setdefault(
            account,
            {
                "invoice_cents": 0,
                "credit_cents": 0,
                "fee_cents": 0,
                "relief_cents": 0,
                "record_count": 0,
            },
        )
        amount = record["amount_cents"]
        if kind == "invoice":
            values["invoice_cents"] += amount
        elif kind == "credit":
            values["credit_cents"] -= amount
        elif kind == "fee":
            values["fee_cents"] += amount
        elif kind == "waiver":
            values["relief_cents"] += amount
        values["record_count"] += 1

    accounts = []
    grand_total = 0
    for account in sorted(totals):
        values = totals[account]
        adjusted_fee = max(0, values["fee_cents"] - values["relief_cents"])
        due = values["invoice_cents"] + values["credit_cents"] + adjusted_fee
        accounts.append(
            {
                "account": account,
                "invoice_cents": values["invoice_cents"],
                "credit_cents": values["credit_cents"],
                "fee_cents": values["fee_cents"],
                "relief_cents": values["relief_cents"],
                "adjusted_fee_cents": adjusted_fee,
                "due_cents": due,
                "record_count": values["record_count"],
            }
        )
        grand_total += due

    print(
        json.dumps(
            {"accounts": accounts, "grand_total_cents": grand_total},
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
