#!/usr/bin/env python3
"""Hidden grader for almanac_rule_boundary_001. Frozen vectors derived from
experiments/almanac/reference/engine.py by experiments/almanac/generate_vectors.py
(--check in CI guards drift). The deciding vectors sit around the lichun and
jieqi boundaries the visible checks never touch."""
import importlib.util
import json  # noqa: F401  (kept for parity with sibling graders)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[2020, 1, 15, 12.0, 0.0], ["己亥", "丁丑"]],
[[2020, 2, 3, 12.0, 0.0], ["己亥", "丁丑"]],
[[2020, 2, 4, 3.0, 0.0], ["己亥", "丁丑"]],
[[2020, 2, 4, 15.0, 0.0], ["庚子", "戊寅"]],
[[2020, 2, 5, 0.0, 0.0], ["庚子", "戊寅"]],
[[2020, 2, 4, 12.0, 8.0], ["己亥", "丁丑"]],
[[2020, 2, 4, 22.0, 8.0], ["庚子", "戊寅"]],
[[2020, 12, 31, 12.0, 0.0], ["庚子", "戊子"]],
[[2021, 1, 1, 12.0, 0.0], ["庚子", "戊子"]],
[[2019, 8, 7, 0.0, 0.0], ["己亥", "辛未"]],
[[2019, 8, 8, 12.0, 0.0], ["己亥", "壬申"]],
[[1984, 2, 6, 12.0, 0.0], ["甲子", "丙寅"]],
[[2000, 5, 5, 18.0, 0.0], ["庚辰", "辛巳"]],
[[1970, 11, 8, 12.0, 0.0], ["庚戌", "丁亥"]]
]


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.year_month_pillars
    except Exception as e:  # noqa: BLE001
        print(f"SCORE 0/{len(VECTORS)}  (candidate failed to load: {e!r})")
        return 1
    ok, fails = 0, []
    for args, want in VECTORS:
        try:
            got = fn(*args)
            if tuple(got) == tuple(want):
                ok += 1
            else:
                fails.append(f"{tuple(args)}: got {got!r}, want {tuple(want)!r}")
        except Exception as e:  # noqa: BLE001
            fails.append(f"{tuple(args)}: raised {type(e).__name__}")
    print(f"SCORE {ok}/{len(VECTORS)}")
    for f in fails[:6]:
        print("  FAIL", f)
    return 0 if ok == len(VECTORS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
