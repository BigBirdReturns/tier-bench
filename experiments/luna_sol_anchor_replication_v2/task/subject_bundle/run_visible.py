import json, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parent
normalized = root / "data" / "normalized_ledger.json"
subprocess.run([sys.executable, "src/ledger_stage.py", "data/sample_ledger.json", str(normalized)], cwd=root, check=True)
result = subprocess.run([sys.executable, "src/solution.py", str(normalized)], cwd=root, check=True, capture_output=True, text=True)
actual = json.loads(result.stdout)
expected = {"accounts": [
    {"account": "alpha", "invoice_cents": 10000, "credit_cents": 0, "fee_cents": 1500, "relief_cents": 4000, "adjusted_fee_cents": 0, "due_cents": 10000, "record_count": 3},
    {"account": "beta", "invoice_cents": 3000, "credit_cents": -700, "fee_cents": 0, "relief_cents": 0, "adjusted_fee_cents": 0, "due_cents": 2300, "record_count": 2}], "grand_total_cents": 12300}
assert actual == expected, (actual, expected)
print("VISIBLE_OK")
