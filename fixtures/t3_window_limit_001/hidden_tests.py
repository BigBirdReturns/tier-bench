#!/usr/bin/env python3
"""Hidden grader for t3_window_limit_001. Frozen vectors derived mechanically from
experiments/breadth/authoring2/build_vectors.py (--check in CI guards drift).
The deciding vectors sit on the half-open window old end (s == t-w excluded) the visible checks never touch."""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[[10, 20, 30], 25, 3, 40], True],
[[[10, 20, 30], 25, 2, 40], False],
[[[5, 6, 7, 8], 10, 5, 12], True],
[[[15, 20, 30], 25, 2, 40], False],
[[[15, 30], 25, 2, 40], True],
[[[15, 15, 15, 30], 25, 2, 40], True],
[[[40], 25, 1, 40], False],
[[[0, 1, 2], 100, 3, 50], False],
[[[], 10, 0, 100], False],
[[[7], 5, 1, 12], True],
]


def _call(fn, args):
    got = fn(args[0], args[1], args[2], args[3])
    if not isinstance(got, bool):
        raise TypeError('allow must return bool')
    return got


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.allow
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
