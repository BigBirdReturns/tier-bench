import json
import sys


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as source:
        state = json.load(source)

    totals = {}
    for record in state["records"]:
        if not record["eligible"] or record["kind"] == "waiver":
            continue

        account = totals.setdefault(
            record["account"],
            {
                "invoice_cents": 0,
                "credit_cents": 0,
                "fee_cents": 0,
                "relief_cents": 0,
                "record_count": 0,
            },
        )
        amount = record["amount_cents"]
        if record["kind"] == "invoice":
            account["invoice_cents"] += amount
        elif record["kind"] == "credit":
            account["credit_cents"] -= amount
        elif record["kind"] == "fee":
            account["fee_cents"] += amount
        account["record_count"] += 1

    accounts = []
    for account_name in sorted(totals):
        total = totals[account_name]
        adjusted_fee = max(0, total["fee_cents"] - total["relief_cents"])
        due = total["invoice_cents"] + total["credit_cents"] + adjusted_fee
        accounts.append(
            {
                "account": account_name,
                "invoice_cents": total["invoice_cents"],
                "credit_cents": total["credit_cents"],
                "fee_cents": total["fee_cents"],
                "relief_cents": total["relief_cents"],
                "adjusted_fee_cents": adjusted_fee,
                "due_cents": due,
                "record_count": total["record_count"],
            }
        )

    print(
        json.dumps(
            {
                "accounts": accounts,
                "grand_total_cents": sum(account["due_cents"] for account in accounts),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
