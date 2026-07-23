#!/usr/bin/env python3
"""Hidden grader for t3_null_filter_001. Frozen vectors derived mechanically from
experiments/breadth/authoring3/build_vectors.py (--check in CI guards drift).
The deciding vectors sit on the three-valued UNKNOWN under negation (the boolean prior) the visible checks never touch."""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[[{'id': 1, 'price': 50, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': 'b'}, {'id': 3, 'price': 99, 'cat': 'a'}], ['cmp', 'price', '>', 100]], [2]],
[[[{'id': 1, 'price': 50, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': 'b'}, {'id': 3, 'price': 99, 'cat': 'a'}], ['not', ['cmp', 'cat', '==', 'a']]], [2]],
[[[{'id': 1, 'price': 50, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': 'b'}, {'id': 3, 'price': 99, 'cat': 'a'}], ['and', ['cmp', 'price', '<', 100], ['cmp', 'cat', '==', 'a']]], [1, 3]],
[[[{'id': 1, 'price': None, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': None}, {'id': 3, 'price': 50, 'cat': 'b'}], ['cmp', 'price', '>', 100]], [2]],
[[[{'id': 1, 'price': None, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': None}, {'id': 3, 'price': 50, 'cat': 'b'}], ['not', ['cmp', 'price', '>', 100]]], [3]],
[[[{'id': 1, 'price': None, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': None}, {'id': 3, 'price': 50, 'cat': 'b'}], ['not', ['cmp', 'cat', '!=', 'b']]], [3]],
[[[{'id': 1, 'price': None, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': None}, {'id': 3, 'price': 50, 'cat': 'b'}], ['or', ['cmp', 'cat', '==', 'a'], ['cmp', 'price', '>', 100]]], [1, 2]],
[[[{'id': 1, 'price': None, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': None}, {'id': 3, 'price': 50, 'cat': 'b'}], ['and', ['cmp', 'price', '>', 100], ['cmp', 'cat', '==', 'zzz']]], []],
[[[{'id': 1, 'price': None, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': None}, {'id': 3, 'price': 50, 'cat': 'b'}], ['not', ['not', ['cmp', 'price', '>', 100]]]], [2]],
[[[{'id': 1, 'price': None, 'cat': 'a'}, {'id': 2, 'price': 150, 'cat': None}, {'id': 3, 'price': 50, 'cat': 'b'}], ['and', ['not', ['cmp', 'price', '<=', 100]], ['or', ['cmp', 'cat', '==', 'x'], ['not', ['cmp', 'cat', '==', 'y']]]]], []],
]


def _call(fn, args):
    got = fn(args[0], args[1])
    if not isinstance(got, list) or not all(
            isinstance(x, int) and not isinstance(x, bool) for x in got):
        raise TypeError('select_ids must return list[int]')
    return got


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.select_ids
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
