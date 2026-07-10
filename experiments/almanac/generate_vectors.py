#!/usr/bin/env python3
"""Generate / check the almanac hidden-knot vectors from the reference engine.

The three almanac tasks (tasks/almanac_*.json) grade against frozen vectors
embedded in their fixtures' hidden graders. Those expectations are never
hand-computed: this script derives every expected value from
reference/engine.py (the corroborated oracle) and either prints the frozen
blocks (--emit) or verifies that the committed fixtures still match a fresh
derivation (--check, run in CI — silent drift between the reference and the
graders fails the build).

Vector design (see VECTORS.md): each set covers ordinary cases PLUS the knot
the task exists to probe — lichun/jieqi boundary application (rule_boundary),
which record governs which pillar (record_binding), master-number terminal
stages (exception_class). Boundary vectors are checked to sit safely off the
knife edge (sun λ at least 0.1° from any 30° band edge) so float noise can
never flip a verdict: deterministic graders, no ties.

    python experiments/almanac/generate_vectors.py --emit
    python experiments/almanac/generate_vectors.py --check
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments" / "almanac" / "reference"))
import engine  # noqa: E402

# ---- vector inputs (expectations always derived from the engine) ----

RULE_BOUNDARY_INPUTS = [
    # (y, m, d, hour_UT-localizable, tz) — year/month pillar knots
    (2020, 1, 15, 12.0, 0.0),    # January belongs to the PREVIOUS solar year
    (2020, 2, 3, 12.0, 0.0),     # day before lichun
    (2020, 2, 4, 3.0, 0.0),      # lichun day, hours BEFORE the λ=315 instant
    (2020, 2, 4, 15.0, 0.0),     # lichun day, hours AFTER the instant
    (2020, 2, 5, 0.0, 0.0),
    (2020, 2, 4, 12.0, 8.0),     # local noon at +8 => UT 04:00, still before
    (2020, 2, 4, 22.0, 8.0),     # local 22:00 at +8 => UT 14:00, after
    (2020, 12, 31, 12.0, 0.0),   # Dec 31 stays in the solar year begun at lichun
    (2021, 1, 1, 12.0, 0.0),     # Jan 1 does NOT start a new solar year
    (2019, 8, 7, 0.0, 0.0),      # around liqiu (λ=135): month-branch boundary
    (2019, 8, 8, 12.0, 0.0),
    (1984, 2, 6, 12.0, 0.0),     # different year stem (five-tigers coverage)
    (2000, 5, 5, 18.0, 0.0),     # mid-band ordinary
    (1970, 11, 8, 12.0, 0.0),    # around lidong (λ=225)
]

RECORD_BINDING_INPUTS = [
    # (y, m, d, local_hour, tz) — day/hour pillars bind to the CIVIL record
    (1993, 8, 17, 23.5, -11.0),  # same civil instant record, three offsets:
    (1993, 8, 17, 23.5, 0.0),    #   day+hour pillars must be identical
    (1993, 8, 17, 23.5, 13.0),
    (2020, 2, 4, 12.0, 8.0),     # tz flips the λ-based fields on this date...
    (2020, 2, 4, 12.0, 0.0),     #   ...but day+hour must not move
    (2019, 5, 27, 0.5, 0.0),     # the committed anchor date itself (甲子)
    (2019, 7, 26, 12.0, 0.0),    # anchor + 60 days: same day pillar
    (2002, 12, 20, 12.0, 0.0),   # anchor - 6000 days: same day pillar
    (1999, 12, 31, 23.98, 0.0),  # 23:xx is the zi branch of the SAME civil day
    (2000, 1, 1, 0.0, 0.0),
    (1988, 3, 3, 1.0, -5.0),     # branch band edge: 01:00 is 丑
    (1988, 3, 3, 0.99, -5.0),    # 00:59 is 子
    (1975, 6, 21, 13.0, 3.0),
    (2010, 10, 10, 22.9, 0.0),
]

EXCEPTION_CLASS_INPUTS = [
    # (y, m, d) — life path; masters are terminal at EVERY stage
    (1996, 7, 8),    # total hits 22 and must stay 22
    (1902, 3, 5),    # total hits 11
    (1948, 2, 9),    # year component is 22; total hits 33
    (2002, 11, 11),  # component masters, ordinary-looking total
    (1988, 11, 29),  # day 29 -> 11 mid-reduction, preserved
    (1975, 4, 22),   # day 22 preserved; year component 22
    (1990, 6, 15),   # ordinary
    (1966, 3, 6),    # ordinary
    (2000, 1, 1),    # ordinary, tiny digits
    (1929, 11, 22),  # both component masters
    (1984, 12, 28),  # day 28 -> 10 -> 1 (two-stage ordinary reduction)
    (1959, 9, 9),    # ordinary
]

_EDGE_MARGIN_DEG = 0.1


def _lam(y, m, d, hour, tz):
    return engine.sun_longitude(engine._jd_ut(y, m, d, hour, tz))


def build() -> dict:
    rb = []
    for (y, m, d, hour, tz) in RULE_BOUNDARY_INPUTS:
        lam = _lam(y, m, d, hour, tz)
        dist = min((lam - 15.0) % 30.0, (15.0 - lam) % 30.0)  # distance to nearest 315+30k edge
        assert dist >= _EDGE_MARGIN_DEG, f"knife-edge vector {(y, m, d, hour, tz)}: λ={lam:.4f}"
        v = engine.bazi(y, m, d, hour, tz)["value"]
        rb.append([[y, m, d, hour, tz], [v["year"], v["month"]]])
    rec = []
    for (y, m, d, hour, tz) in RECORD_BINDING_INPUTS:
        v = engine.bazi(y, m, d, hour, tz)["value"]
        rec.append([[y, m, d, hour, tz], [v["day"], v["hour"]]])
    exc = []
    for (y, m, d) in EXCEPTION_CLASS_INPUTS:
        exc.append([[y, m, d], engine.life_path(y, m, d)["value"]])
    return {"almanac_rule_boundary_001": rb,
            "almanac_record_binding_001": rec,
            "almanac_exception_class_001": exc}


def frozen_vectors(task_id: str) -> list:
    """Read the VECTORS block frozen inside a fixture's hidden grader."""
    grader = REPO / "fixtures" / task_id / "hidden_tests.py"
    m = re.search(r"VECTORS = (\[.*?\n\])\n", grader.read_text(encoding="utf-8"), re.S)
    if not m:
        raise ValueError(f"no VECTORS block in {grader}")
    return json.loads(m.group(1))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    vecs = build()
    if mode == "--emit":
        for task, rows in vecs.items():
            block = "VECTORS = [\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]"
            print(f"# {task}\n{block}\n")
        return 0
    bad = 0
    for task, rows in vecs.items():
        frozen = frozen_vectors(task)
        if frozen != rows:
            bad += 1
            print(f"DRIFT: {task}: frozen vectors do not match a fresh derivation from reference/engine.py")
    if bad:
        return 1
    n = sum(len(r) for r in vecs.values())
    print(f"almanac vectors OK — {n} frozen vectors across 3 tasks match the reference derivation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
