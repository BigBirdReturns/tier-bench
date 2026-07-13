#!/usr/bin/env python3
"""Hidden grader for t3_accrual_crossover_001. Frozen vectors derived mechanically from
experiments/breadth/authoring3/build_vectors.py (--check in CI guards drift).
The deciding vectors sit on the exact integer floor-compounding (stall, ==-boundary, float drift) the visible checks never touch."""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[1000, 1, 10, 2000, 30], 8],
[[5000, 1, 4, 20000, 30], 7],
[[100, 1, 2, 1000, 30], 6],
[[100, 1, 1000, 5000, 100000], None],
[[1000, 1, 10, 1210, 30], 3],
[[5000, 1, 10, 4999, 10], 0],
[[1000000, 1, 997, 3000000, 20000], 1097],
[[10000000000000, 3, 7, 1000000000000000, 100], 13],
[[1000, 1, 10, 1000000000, 50], None],
[[1000, 1, 1000, 1100, 100000], 101],
]


def _call(fn, args):
    got = fn(*args)
    if got is not None and (not isinstance(got, int) or isinstance(got, bool)):
        raise TypeError('crossover_day must return int or None')
    return got


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.crossover_day
    except Exception as e:  # noqa: BLE001
        print("SCORE 0/{0}  (candidate failed to load: {1!r})".format(len(VECTORS), e))
        return 1
    ok, fails = 0, []
    for args, want in VECTORS:
        try:
            got = _call(fn, args)
            if json.dumps(got) == json.dumps(want):
                ok += 1
            else:
                fails.append("{0}: got {1!r}, want {2!r}".format(args, got, want))
        except Exception as e:  # noqa: BLE001
            fails.append("{0}: raised {1}".format(args, type(e).__name__))
    print("SCORE {0}/{1}".format(ok, len(VECTORS)))
    for f in fails[:6]:
        print("  FAIL", f)
    return 0 if ok == len(VECTORS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
