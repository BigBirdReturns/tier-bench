#!/usr/bin/env bash
set -u
cd ~/tbrail
T="python3 bin/tbrail.py"

echo "########## A. DELIBERATE VALIDATION DEFECT MUST RENDER RED ##########"
$T submit envelope-defect.json
$T execute estate-organ-realignment-defect-001 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("terminal=",d["terminal"]); [print("  ",p["name"],p["state"],"exit",p["exit_code"]) for p in d["phases"]]'

echo
echo "########## B. CREDENTIAL ISOLATION IN THE WORKER ##########"
$T submit envelope-isolation.json
$T execute estate-credential-isolation-001 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("terminal=",d["terminal"]); [print("  ",p["name"],p["state"],"exit",p["exit_code"]) for p in d["phases"]]'
echo "--- worker probe output ---"
cat ~/.tbrail/receipts/estate-credential-isolation-001/logs/00-*.log

echo
echo "########## C. RESTART REPLAY MUST NOT DUPLICATE ##########"
echo "re-executing an already-SETTLED transaction in a FRESH process:"
$T execute estate-organ-realignment-canary-001
echo "phase rows for canary (must remain exactly 5, not 10):"
python3 - <<'PY'
import sqlite3, pathlib
db = sqlite3.connect(pathlib.Path.home()/".tbrail"/"rail.db")
n = db.execute("SELECT COUNT(*) FROM phase WHERE txn_id=?",
               ("estate-organ-realignment-canary-001",)).fetchone()[0]
print("phase_rows =", n)
PY

echo
echo "########## D. SAME-RESOURCE COLLISION ##########"
$T submit envelope-collision-holder.json
$T submit envelope-collision-contender.json
echo "starting holder in background (25s phase, same resource_key)..."
nohup $T execute estate-collision-holder-001 > /tmp/holder.json 2>&1 &
HOLDER=$!
sleep 4
echo "lease table while holder runs:"
python3 - <<'PY'
import sqlite3, pathlib
db = sqlite3.connect(pathlib.Path.home()/".tbrail"/"rail.db")
for r in db.execute("SELECT resource_key, txn_id, pid FROM lease"):
    print("  held:", r)
PY
echo "contender attempting the SAME resource_key:"
$T execute estate-collision-contender-001
echo "waiting for holder to finish..."
wait $HOLDER
python3 -c 'import json;d=json.load(open("/tmp/holder.json"));print("holder terminal =",d["terminal"])' 2>/dev/null || tail -3 /tmp/holder.json

echo
echo "########## E. TERMINAL RECEIPT RECONSTRUCTS IN A FRESH PROCESS ##########"
$T verify ~/.tbrail/receipts/estate-organ-realignment-canary-001/RECEIPT.json

echo
echo "########## F. ZERO RESIDENCY ##########"
$T residency
echo "workspace root contents:"
ls -la ~/.tbrail/work/ 2>/dev/null
echo "any tbrail worker processes still alive?"
pgrep -af 'py_compile|unittest|estate_authority_resolver' || echo "  none"
echo "transaction ledger:"
$T list
echo "PROOFS_DONE"
