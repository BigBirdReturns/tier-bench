#!/usr/bin/env python3
"""Hidden grader for t3_due_date_shift_001. Frozen vectors derived mechanically from
experiments/breadth/authoring2/build_vectors.py (--check in CI guards drift).
The deciding vectors sit on the month-crossing reversal (modified-following) the visible checks never touch."""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[[2024, 7, 15], []], [2024, 7, 15]],
[[[2024, 7, 13], []], [2024, 7, 15]],
[[[2024, 7, 15], [[2024, 7, 15]]], [2024, 7, 16]],
[[[2024, 11, 30], []], [2024, 11, 29]],
[[[2024, 8, 31], []], [2024, 8, 30]],
[[[2024, 8, 31], [[2024, 8, 30]]], [2024, 8, 29]],
[[[2024, 3, 30], [[2024, 4, 1]]], [2024, 3, 29]],
[[[2023, 12, 30], []], [2023, 12, 29]],
[[[2024, 9, 28], [[2024, 9, 30]]], [2024, 9, 27]],
[[[2024, 5, 20], []], [2024, 5, 20]],
]


def _call(fn, args):
    nom, hol = args
    got = fn(nom[0], nom[1], nom[2], {tuple(h) for h in hol})
    if not isinstance(got, tuple):
        raise TypeError('due_date must return tuple[int, int, int]')
    return list(got)


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.due_date
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
