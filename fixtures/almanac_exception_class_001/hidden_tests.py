#!/usr/bin/env python3
"""Hidden grader for almanac_exception_class_001. Frozen vectors derived from
experiments/almanac/reference/engine.py by experiments/almanac/generate_vectors.py
(--check in CI guards drift). The deciding vectors are the ones where the
master-number exception class changes the answer — totals and components that
land on 11/22/33 and must stop there."""
import importlib.util
import json  # noqa: F401
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[1996, 7, 8], 22],
[[1902, 3, 5], 11],
[[1948, 2, 9], 33],
[[2002, 11, 11], 8],
[[1988, 11, 29], 3],
[[1975, 4, 22], 3],
[[1990, 6, 15], 4],
[[1966, 3, 6], 4],
[[2000, 1, 1], 4],
[[1929, 11, 22], 9],
[[1984, 12, 28], 8],
[[1959, 9, 9], 6]
]


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.life_path
    except Exception as e:  # noqa: BLE001
        print(f"SCORE 0/{len(VECTORS)}  (candidate failed to load: {e!r})")
        return 1
    ok, fails = 0, []
    for args, want in VECTORS:
        try:
            got = fn(*args)
            if got == want:
                ok += 1
            else:
                fails.append(f"{tuple(args)}: got {got!r}, want {want!r}")
        except Exception as e:  # noqa: BLE001
            fails.append(f"{tuple(args)}: raised {type(e).__name__}")
    print(f"SCORE {ok}/{len(VECTORS)}")
    for f in fails[:6]:
        print("  FAIL", f)
    return 0 if ok == len(VECTORS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
