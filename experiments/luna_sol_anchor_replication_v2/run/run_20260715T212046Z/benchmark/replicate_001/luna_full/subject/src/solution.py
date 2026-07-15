import json
import sys
from pathlib import Path


def main() -> None:
    normalized_path = Path(sys.argv[1])
    with normalized_path.open(encoding="utf-8") as handle:
        state = json.load(handle)

    accounts = {}
    for record in state["records"]:
        if not record["eligible"]:
            continue

        account = record["account"]
        totals = accounts.setdefault(account, {
            "account": account,
            "invoice_cents": 0,
            "credit_cents": 0,
            "fee_cents": 0,
            "relief_cents": 0,
            "record_count": 0,
        })
        kind = record["kind"]
        amount = record["amount_cents"]
        if kind == "invoice":
            totals["invoice_cents"] += amount
        elif kind == "credit":
            totals["credit_cents"] -= amount
        elif kind == "fee":
            totals["fee_cents"] += amount
        elif kind == "waiver":
            if record["fee_relief_eligible"]:
                totals["relief_cents"] += amount

        if kind != "waiver":
            totals["record_count"] += 1

    result_accounts = []
    for account in sorted(accounts):
        totals = accounts[account]
        adjusted_fee = max(0, totals["fee_cents"] - totals["relief_cents"])
        result_accounts.append({
            "account": account,
            "invoice_cents": totals["invoice_cents"],
            "credit_cents": totals["credit_cents"],
            "fee_cents": totals["fee_cents"],
            "relief_cents": totals["relief_cents"],
            "adjusted_fee_cents": adjusted_fee,
            "due_cents": totals["invoice_cents"] + totals["credit_cents"] + adjusted_fee,
            "record_count": totals["record_count"],
        })

    result = {
        "accounts": result_accounts,
        "grand_total_cents": sum(account["due_cents"] for account in result_accounts),
    }
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
