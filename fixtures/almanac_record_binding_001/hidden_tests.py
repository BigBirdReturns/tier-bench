#!/usr/bin/env python3
"""Hidden grader for almanac_record_binding_001. Frozen vectors derived from
experiments/almanac/reference/engine.py by experiments/almanac/generate_vectors.py
(--check in CI guards drift). The deciding vectors probe which record governs:
identical civil readings across offsets must yield identical day/hour pillars,
23:xx stays on its own civil day, and the sexagenary anchor must hold at ±60k."""
import importlib.util
import json  # noqa: F401
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VECTORS = [
[[1993, 8, 17, 23.5, -11.0], ["庚午", "丙子"]],
[[1993, 8, 17, 23.5, 0.0], ["庚午", "丙子"]],
[[1993, 8, 17, 23.5, 13.0], ["庚午", "丙子"]],
[[2020, 2, 4, 12.0, 8.0], ["丁丑", "丙午"]],
[[2020, 2, 4, 12.0, 0.0], ["丁丑", "丙午"]],
[[2019, 5, 27, 0.5, 0.0], ["甲子", "甲子"]],
[[2019, 7, 26, 12.0, 0.0], ["甲子", "庚午"]],
[[2002, 12, 20, 12.0, 0.0], ["壬戌", "丙午"]],
[[1999, 12, 31, 23.98, 0.0], ["丁巳", "庚子"]],
[[2000, 1, 1, 0.0, 0.0], ["戊午", "壬子"]],
[[1988, 3, 3, 1.0, -5.0], ["丁巳", "辛丑"]],
[[1988, 3, 3, 0.99, -5.0], ["丁巳", "庚子"]],
[[1975, 6, 21, 13.0, 3.0], ["戊戌", "己未"]],
[[2010, 10, 10, 22.9, 0.0], ["癸巳", "癸亥"]]
]


def main() -> int:
    spec = importlib.util.spec_from_file_location("cand", Path(__file__).resolve().parent / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.day_hour_pillars
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
