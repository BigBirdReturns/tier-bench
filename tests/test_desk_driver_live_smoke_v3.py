from pathlib import Path

proof = Path("experiments/desk_driver_live_smoke/proof-v3.txt")
actual = proof.read_text(encoding="utf-8").splitlines() if proof.exists() else []
raise SystemExit(actual != ["DESK_DRIVER_LOOP_POST_APPLY_VERIFIED"])
