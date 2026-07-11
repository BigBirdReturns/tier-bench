#!/usr/bin/env python3
"""Deterministic hidden grader for the A/B/C causal test (count_matches).
Vectors derive from the settled task02 reference oracle. Run: python grade.py <solution_dir>"""
import importlib.util, json, sys
from pathlib import Path
vec = json.loads((Path(__file__).parent / "hidden_vectors.json").read_text())
sol_dir = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("solution", sol_dir / "solution.py")
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except Exception as e:
    print(f"LOAD_ERROR {type(e).__name__}: {e}"); sys.exit(2)
passed = 0
fails = []
for i, v in enumerate(vec):
    want = v.get("result", v.get("error"))
    try:
        got = m.count_matches(v["pattern"], v["words"])
        ok = (got == want)
    except ValueError:
        got = "ValueError"; ok = (want == "ValueError")
    except Exception as e:
        got = f"{type(e).__name__}"; ok = False
    if ok: passed += 1
    else: fails.append(f"v{i} pattern={v['pattern']!r} want={want!r} got={got!r}")
print(f"SCORE {passed}/{len(vec)}")
for f in fails: print("FAIL", f)
sys.exit(0 if passed == len(vec) else 1)
