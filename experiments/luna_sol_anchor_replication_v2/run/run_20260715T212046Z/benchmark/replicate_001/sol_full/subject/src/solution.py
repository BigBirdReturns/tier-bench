import json
import sys


def main() -> None:
    (normalized_path,) = sys.argv[1:]
    with open(normalized_path, encoding="utf-8") as normalized_file:
        state = json.load(normalized_file)

    accounts = {}
    for record in state["records"]:
        if not record["eligible"]:
            continue

        account = accounts.setdefault(
            record["account"],
            {
                "account": record["account"],
                "invoice_cents": 0,
                "credit_cents": 0,
                "fee_cents": 0,
                "relief_cents": 0,
                "record_count": 0,
            },
        )
        account["record_count"] += 1
        kind = record["kind"]
        amount = record["amount_cents"]
        if kind == "invoice":
            account["invoice_cents"] += amount
        elif kind == "credit":
            account["credit_cents"] -= amount
        elif kind == "fee":
            account["fee_cents"] += amount
        elif kind == "waiver" and record["fee_relief_eligible"]:
            account["relief_cents"] += amount

    output_accounts = []
    grand_total = 0
    for account_name in sorted(accounts):
        account = accounts[account_name]
        adjusted_fees = max(0, account["fee_cents"] - account["relief_cents"])
        due = account["invoice_cents"] + account["credit_cents"] + adjusted_fees
        output_accounts.append(
            {
                "account": account["account"],
                "invoice_cents": account["invoice_cents"],
                "credit_cents": account["credit_cents"],
                "fee_cents": account["fee_cents"],
                "relief_cents": account["relief_cents"],
                "adjusted_fee_cents": adjusted_fees,
                "due_cents": due,
                "record_count": account["record_count"],
            }
        )
        grand_total += due

    result = {"accounts": output_accounts, "grand_total_cents": grand_total}
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
