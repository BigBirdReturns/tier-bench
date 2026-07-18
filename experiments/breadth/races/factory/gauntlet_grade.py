"""Gauntlet grader: every arm x shape through the pre-verified hidden tests."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

G = Path(__file__).resolve().parent
A = G / "_authoring"
ARMS = sys.argv[1:] or ["spark", "luna", "terra", "sol", "haiku", "sonnet", "opus"]
SHAPES = {
    "w1_pipeline": {"visible": "run.py", "copy": ["run.py", "pipeline"]},
    "w2_bughunt": {"visible": "ledger.py", "copy": ["ledger.py"]},
    "w3_amendments": {"visible": "input.py", "copy": ["input.py"]},
}


def grade(arm, shape, cfg):
    src = G / arm / shape
    if not src.exists():
        return "MISSING"
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp)
        for item in cfg["copy"]:
            s = src / item
            if not s.exists():
                return "INCOMPLETE"
            if s.is_dir():
                shutil.copytree(s, tp / item)
            else:
                shutil.copy(s, tp / item)
        shutil.copy(A / shape / "hidden_tests.py", tp / "hidden_tests.py")
        try:
            v = subprocess.run([sys.executable, "-B", cfg["visible"]], cwd=tp, capture_output=True, text=True, timeout=60)
            h = subprocess.run([sys.executable, "-B", "hidden_tests.py"], cwd=tp, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return "TIMEOUT"
        if "OK" not in v.stdout:
            return "VISIBLE-FAIL"
        if h.returncode != 0:
            tail = [l for l in h.stdout.splitlines() if l.startswith(("FAIL", "HIDDEN"))]
            return "HIDDEN-FAIL(" + (tail[-1] if tail else "?") + ")"
        return "PASS"


def main():
    board = {}
    for arm in ARMS:
        row = {}
        for shape, cfg in SHAPES.items():
            row[shape] = grade(arm, shape, cfg)
        board[arm] = row
        marks = " ".join(f"{s.split('_')[0]}={'P' if r == 'PASS' else 'X'}" for s, r in row.items())
        print(f"{arm:8s} {marks}   {json.dumps(row) if any(r != 'PASS' for r in row.values()) else ''}")
    (G / "board.json").write_text(json.dumps(board, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
