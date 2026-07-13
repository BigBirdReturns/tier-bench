#!/usr/bin/env python3
"""Hidden grader for t3_billing_anchor_001. Frozen vectors derived mechanically from
experiments/breadth/authoring2/build_vectors.py (--check in CI guards drift).
The deciding vectors sit on the anchor-restore boundary (clamp must not cascade) the visible checks never touch."""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[2024, 3, 10, 3], [[2024, 4, 10], [2024, 5, 10], [2024, 6, 10]]],
[[2023, 11, 5, 4], [[2023, 12, 5], [2024, 1, 5], [2024, 2, 5], [2024, 3, 5]]],
[[2022, 7, 20, 2], [[2022, 8, 20], [2022, 9, 20]]],
[[2024, 1, 31, 4], [[2024, 2, 29], [2024, 3, 31], [2024, 4, 30], [2024, 5, 31]]],
[[2023, 1, 31, 3], [[2023, 2, 28], [2023, 3, 31], [2023, 4, 30]]],
[[2024, 11, 30, 4], [[2024, 12, 30], [2025, 1, 30], [2025, 2, 28], [2025, 3, 30]]],
[[2023, 12, 31, 14], [[2024, 1, 31], [2024, 2, 29], [2024, 3, 31], [2024, 4, 30], [2024, 5, 31], [2024, 6, 30], [2024, 7, 31], [2024, 8, 31], [2024, 9, 30], [2024, 10, 31], [2024, 11, 30], [2024, 12, 31], [2025, 1, 31], [2025, 2, 28]]],
[[2024, 2, 29, 13], [[2024, 3, 29], [2024, 4, 29], [2024, 5, 29], [2024, 6, 29], [2024, 7, 29], [2024, 8, 29], [2024, 9, 29], [2024, 10, 29], [2024, 11, 29], [2024, 12, 29], [2025, 1, 29], [2025, 2, 28], [2025, 3, 29]]],
[[2024, 5, 31, 0], []],
]


def _call(fn, args):
    return [list(x) for x in fn(*args)]


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.billing_dates
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
