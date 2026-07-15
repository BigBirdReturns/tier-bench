import json
import sys


def main():
    with open(sys.argv[1], encoding="utf-8") as source:
        state = json.load(source)

    totals = {}
    for record in state["records"]:
        if not record["eligible"]:
            continue

        account = record["account"]
        if account not in totals:
            totals[account] = {
                "account": account,
                "invoice_cents": 0,
                "credit_cents": 0,
                "fee_cents": 0,
                "relief_cents": 0,
                "record_count": 0,
            }
        result = totals[account]
        result["record_count"] += 1
        if record["kind"] == "invoice":
            result["invoice_cents"] += record["amount_cents"]
        elif record["kind"] == "credit":
            result["credit_cents"] -= record["amount_cents"]
        elif record["kind"] == "fee":
            result["fee_cents"] += record["amount_cents"]
        elif record["kind"] == "waiver" and record["fee_relief_eligible"]:
            result["relief_cents"] += record["amount_cents"]

    accounts = []
    for account in sorted(totals):
        result = totals[account]
        result["adjusted_fee_cents"] = max(0, result["fee_cents"] - result["relief_cents"])
        result["due_cents"] = (
            result["invoice_cents"]
            + result["credit_cents"]
            + result["adjusted_fee_cents"]
        )
        accounts.append({
            "account": result["account"],
            "invoice_cents": result["invoice_cents"],
            "credit_cents": result["credit_cents"],
            "fee_cents": result["fee_cents"],
            "relief_cents": result["relief_cents"],
            "adjusted_fee_cents": result["adjusted_fee_cents"],
            "due_cents": result["due_cents"],
            "record_count": result["record_count"],
        })

    print(json.dumps({
        "accounts": accounts,
        "grand_total_cents": sum(account["due_cents"] for account in accounts),
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
