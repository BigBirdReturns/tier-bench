import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> None:
    normalized = json.loads(Path(sys.argv[1]).read_text())
    accounts = defaultdict(lambda: {
        "invoice_cents": 0,
        "credit_cents": 0,
        "fee_cents": 0,
        "relief_cents": 0,
        "record_count": 0,
    })

    for record in normalized["records"]:
        if not record["eligible"]:
            continue
        account = accounts[record["account"]]
        amount = record["amount_cents"]
        if record["kind"] != "waiver":
            account["record_count"] += 1
        if record["kind"] == "invoice":
            account["invoice_cents"] += amount
        elif record["kind"] == "credit":
            account["credit_cents"] -= amount
        elif record["kind"] == "fee":
            account["fee_cents"] += amount

    result_accounts = []
    for account_name in sorted(accounts):
        values = accounts[account_name]
        adjusted_fee = max(0, values["fee_cents"] - values["relief_cents"])
        result_accounts.append({
            "account": account_name,
            "invoice_cents": values["invoice_cents"],
            "credit_cents": values["credit_cents"],
            "fee_cents": values["fee_cents"],
            "relief_cents": values["relief_cents"],
            "adjusted_fee_cents": adjusted_fee,
            "due_cents": values["invoice_cents"] + values["credit_cents"] + adjusted_fee,
            "record_count": values["record_count"],
        })

    print(json.dumps({
        "accounts": result_accounts,
        "grand_total_cents": sum(account["due_cents"] for account in result_accounts),
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
