#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

CASES = [{"cutoff_period":202601,"records":[{"account":"alpha","amount_cents":10000,"id":"a1","kind":"invoice","period":202601,"priority":0,"status":"open"},{"account":"alpha","amount_cents":1500,"id":"a2","kind":"fee","period":202601,"priority":0,"status":"settled"},{"account":"alpha","amount_cents":4000,"id":"a3","kind":"waiver","period":202601,"priority":2,"status":"settled"},{"account":"alpha","amount_cents":500,"id":"a4","kind":"credit","period":202602,"priority":0,"status":"open"},{"account":"alpha","amount_cents":999,"id":"a5","kind":"invoice","period":202601,"priority":0,"status":"void"},{"account":"beta","amount_cents":3000,"id":"b1","kind":"invoice","period":202601,"priority":0,"status":"settled"},{"account":"beta","amount_cents":700,"id":"b2","kind":"credit","period":202601,"priority":0,"status":"settled"}]},{"cutoff_period":202602,"records":[{"account":"north","amount_cents":7000,"id":"c1","kind":"invoice","period":202602,"priority":0,"status":"open"},{"account":"north","amount_cents":500,"id":"c2","kind":"fee","period":202601,"priority":0,"status":"open"},{"account":"north","amount_cents":1000,"id":"c3","kind":"waiver","period":202602,"priority":1,"status":"settled"},{"account":"south","amount_cents":8000,"id":"c4","kind":"invoice","period":202603,"priority":0,"status":"open"},{"account":"south","amount_cents":2000,"id":"c5","kind":"fee","period":202602,"priority":0,"status":"settled"},{"account":"south","amount_cents":2500,"id":"c6","kind":"waiver","period":202602,"priority":2,"status":"settled"}]},{"cutoff_period":202603,"records":[{"account":"x","amount_cents":1200,"id":"d1","kind":"invoice","period":202603,"priority":0,"status":"settled"},{"account":"x","amount_cents":2200,"id":"d2","kind":"credit","period":202603,"priority":0,"status":"settled"},{"account":"x","amount_cents":900,"id":"d3","kind":"fee","period":202603,"priority":0,"status":"settled"},{"account":"x","amount_cents":400,"id":"d4","kind":"waiver","period":202603,"priority":2,"status":"settled"},{"account":"y","amount_cents":4500,"id":"d5","kind":"invoice","period":202602,"priority":0,"status":"draft"},{"account":"y","amount_cents":600,"id":"d6","kind":"fee","period":202603,"priority":0,"status":"open"}]},{"cutoff_period":202604,"records":[{"account":"one","amount_cents":100,"id":"e1","kind":"invoice","period":202604,"priority":0,"status":"open"},{"account":"one","amount_cents":1000,"id":"e2","kind":"fee","period":202604,"priority":0,"status":"open"},{"account":"one","amount_cents":400,"id":"e3","kind":"waiver","period":202604,"priority":2,"status":"settled"},{"account":"two","amount_cents":900,"id":"e4","kind":"invoice","period":202604,"priority":0,"status":"open"},{"account":"two","amount_cents":100,"id":"e5","kind":"credit","period":202604,"priority":0,"status":"open"}]},{"cutoff_period":202605,"records":[{"account":"red","amount_cents":10000,"id":"f1","kind":"invoice","period":202605,"priority":0,"status":"settled"},{"account":"red","amount_cents":1000,"id":"f2","kind":"credit","period":202605,"priority":0,"status":"settled"},{"account":"red","amount_cents":100,"id":"f3","kind":"fee","period":202605,"priority":0,"status":"settled"},{"account":"red","amount_cents":50,"id":"f4","kind":"waiver","period":202605,"priority":2,"status":"settled"},{"account":"blue","amount_cents":2500,"id":"f5","kind":"invoice","period":202605,"priority":0,"status":"open"},{"account":"blue","amount_cents":250,"id":"f6","kind":"fee","period":202605,"priority":0,"status":"void"}]},{"cutoff_period":202606,"records":[{"account":"late","amount_cents":6000,"id":"g1","kind":"invoice","period":202606,"priority":0,"status":"open"},{"account":"late","amount_cents":7000,"id":"g2","kind":"invoice","period":202607,"priority":0,"status":"open"},{"account":"late","amount_cents":800,"id":"g3","kind":"fee","period":202606,"priority":0,"status":"settled"},{"account":"late","amount_cents":900,"id":"g4","kind":"waiver","period":202606,"priority":2,"status":"settled"},{"account":"early","amount_cents":3200,"id":"g5","kind":"invoice","period":202605,"priority":0,"status":"settled"},{"account":"early","amount_cents":300,"id":"g6","kind":"credit","period":202605,"priority":0,"status":"settled"}]}]
def expected(raw):
    buckets = {}
    for row in raw["records"]:
        if row["status"] not in {"open", "settled"} or int(row["period"]) > int(raw["cutoff_period"]):
            continue
        b = buckets.setdefault(row["account"], [0, 0, 0, 0, 0])
        b[4] += 1
        if row["kind"] == "invoice": b[0] += int(row["amount_cents"])
        elif row["kind"] == "credit": b[1] -= int(row["amount_cents"])
        elif row["kind"] == "fee": b[2] += int(row["amount_cents"])
        elif row["kind"] == "waiver" and int(row.get("priority", 0)) >= 2: b[3] += int(row["amount_cents"])
    accounts = []
    for name in sorted(buckets):
        inv, cred, fee, relief, count = buckets[name]
        adjusted = max(0, fee - relief)
        accounts.append({"account": name, "invoice_cents": inv, "credit_cents": cred,
            "fee_cents": fee, "relief_cents": relief, "adjusted_fee_cents": adjusted,
            "due_cents": inv + cred + adjusted, "record_count": count})
    return {"accounts": accounts, "grand_total_cents": sum(x["due_cents"] for x in accounts)}

def run(candidate, raw, number):
    work = candidate / ("_grade_case_" + str(number))
    work.mkdir()
    ledger = work / "ledger.json"; normalized = work / "normalized.json"
    ledger.write_text(json.dumps(raw) + "\n")
    stage = subprocess.run([sys.executable, "src/ledger_stage.py", str(ledger), str(normalized)], cwd=candidate, capture_output=True, text=True)
    if stage.returncode != 0 or not normalized.is_file(): return False, "stage:" + stage.stderr[-200:]
    try:
        state = json.loads(normalized.read_text())
        if state.get("cutoff_period") != raw["cutoff_period"] or len(state.get("records", [])) != len(raw["records"]): return False, "state-shape"
    except Exception: return False, "state-json"
    solution = subprocess.run([sys.executable, "src/solution.py", str(normalized)], cwd=candidate, capture_output=True, text=True)
    if solution.returncode != 0: return False, "solution:" + solution.stderr[-200:]
    try: actual = json.loads(solution.stdout)
    except Exception: return False, "output-json"
    return actual == expected(raw), "mismatch" if actual != expected(raw) else "ok"

def main():
    if len(sys.argv) != 2: return 2
    candidate = Path(sys.argv[1]).resolve()
    failures = []
    for i, raw in enumerate(CASES):
        ok, why = run(candidate, raw, i)
        if not ok: failures.append({"case": i, "reason": why})
    print(json.dumps({"cases": len(CASES), "failures": failures, "passed": not failures}, sort_keys=True))
    return 0 if not failures else 1
if __name__ == "__main__": raise SystemExit(main())
