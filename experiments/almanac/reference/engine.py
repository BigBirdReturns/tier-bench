#!/usr/bin/env python3
"""Reference almanac engine — deterministic, stdlib-only, citation-trailed.

Every public function returns {"value": ..., "method": ..., "steps": [...]}.
Conventions per experiments/almanac/DESIGN.md. This is the GRADER's ground
truth; it is corroborated against independently hand-computed charts before
anything is graded with it.
"""
from __future__ import annotations

import math

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
         "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

# Sexagenary day anchor: 2019-05-27 is 甲子 (index 0), corroborated across the
# operator's charts (all nine known day pillars, mutually 60-consistent).
_ANCHOR_JDN, _ANCHOR_IDX = 2458631, 0  # jdn(2019,5,27)


def jdn(y: int, m: int, d: int) -> int:
    a = (14 - m) // 12
    y2 = y + 4800 - a
    m2 = m + 12 * a - 3
    return d + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - y2 // 100 + y2 // 400 - 32045


def _sind(x): return math.sin(math.radians(x))


def sun_longitude(jd_ut: float) -> float:
    """Apparent-ish solar longitude, Meeus low precision (~0.01 deg)."""
    t = (jd_ut - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * _sind(m)
         + (0.019993 - 0.000101 * t) * _sind(2 * m) + 0.000289 * _sind(3 * m))
    return (l0 + c) % 360.0


def moon_longitude(jd_ut: float) -> float:
    """Geocentric lunar longitude, truncated main terms (~0.3 deg)."""
    t = (jd_ut - 2451545.0) / 36525.0
    lp = 218.3164477 + 481267.88123421 * t
    d = 297.8501921 + 445267.1114034 * t
    m = 357.5291092 + 35999.0502909 * t
    mp = 134.9633964 + 477198.8675055 * t
    f = 93.2720950 + 483202.0175233 * t
    lon = (lp + 6.288774 * _sind(mp) + 1.274027 * _sind(2 * d - mp)
           + 0.658314 * _sind(2 * d) + 0.213618 * _sind(2 * mp)
           - 0.185116 * _sind(m) - 0.114332 * _sind(2 * f)
           + 0.058793 * _sind(2 * d - 2 * mp) + 0.057066 * _sind(2 * d - m - mp)
           + 0.053322 * _sind(2 * d + mp) + 0.045758 * _sind(2 * d - m))
    return lon % 360.0


def _jd_ut(y, m, d, hour=12.0, tz=0.0):
    """JD (UT) for local civil time `hour` at UTC offset `tz` (hours)."""
    return jdn(y, m, d) - 0.5 + (hour - tz) / 24.0


# ---------------------------------------------------------------- numerology
def _reduce(n: int, steps: list) -> int:
    while n > 9 and n not in (11, 22, 33):
        s = sum(int(c) for c in str(n))
        steps.append(f"{n} -> {'+'.join(str(n))} = {s}")
        n = s
    return n


def life_path(y: int, m: int, d: int) -> dict:
    steps: list = []
    rm, rd, ry = _reduce(m, steps), _reduce(d, steps), _reduce(sum(int(c) for c in str(y)), steps)
    steps.append(f"year {y} digit-sum first; components: month={rm} day={rd} year={ry}")
    total = rm + rd + ry
    steps.append(f"{rm}+{rd}+{ry} = {total}")
    v = _reduce(total, steps)
    return {"value": v, "method": "Pythagorean life path, masters 11/22/33 preserved", "steps": steps}


# ---------------------------------------------------------------------- bazi
def _month_index(lam: float) -> int:
    """0 = yin month (starts at lichun, sun λ=315); each month is 30° of λ."""
    return int(((lam - 315.0) % 360.0) // 30.0)


def bazi(y: int, m: int, d: int, hour: float | None = None, tz: float = 0.0) -> dict:
    steps: list = []
    jd = _jd_ut(y, m, d, hour if hour is not None else 12.0, tz)
    lam = sun_longitude(jd)
    steps.append(f"sun λ = {lam:.2f}° at JD {jd:.3f} (UT)")

    # Year: begins at lichun (λ crossing 315°). Before lichun -> previous year.
    solar_year = y
    if (m, d) < (3, 15) and not (315.0 <= lam < 345.0 + 360.0):  # only Jan-mid Mar can precede lichun
        if lam >= 255.0:  # 丑/子 months at year start => before lichun
            solar_year = y - 1
            steps.append(f"before lichun -> solar year {solar_year}")
    ys, yb = (solar_year - 4) % 10, (solar_year - 4) % 12
    steps.append(f"({solar_year}-4)%10={ys} -> {STEMS[ys]}; ({solar_year}-4)%12={yb} -> {BRANCHES[yb]}")

    # Month: branch from λ band; stem by five tigers from year stem.
    mi = _month_index(lam)
    mb = (2 + mi) % 12
    first_stem = ((ys % 5) * 2 + 2) % 10
    ms = (first_stem + mi) % 10
    steps.append(f"month index {mi} from λ -> branch {BRANCHES[mb]}; five-tigers start {STEMS[first_stem]} -> stem {STEMS[ms]}")

    # Day: sexagenary cycle from corroborated anchor.
    di = (_ANCHOR_IDX + jdn(y, m, d) - _ANCHOR_JDN) % 60
    ds, db = di % 10, di % 12
    steps.append(f"day cycle index {di} -> {STEMS[ds]}{BRANCHES[db]}")

    out = {"year": STEMS[ys] + BRANCHES[yb], "month": STEMS[ms] + BRANCHES[mb],
           "day": STEMS[ds] + BRANCHES[db]}

    # Hour: civil time, 2h branches, five rats.
    if hour is not None:
        hb = int((hour + 1) // 2) % 12
        hs = ((ds % 5) * 2 + hb) % 10
        steps.append(f"hour {hour:.2f} -> branch {BRANCHES[hb]}; five-rats from day stem -> {STEMS[hs]}")
        out["hour"] = STEMS[hs] + BRANCHES[hb]

    return {"value": out, "method": "Four Pillars: solar-longitude months, lichun year, JDN day cycle, civil-time hours",
            "steps": steps}


# ------------------------------------------------------------------- western
def _sign(lam: float) -> tuple[str, float]:
    return SIGNS[int(lam // 30) % 12], lam % 30


def western(y: int, m: int, d: int, hour: float = 12.0, tz: float = 0.0) -> dict:
    steps: list = []
    jd = _jd_ut(y, m, d, hour, tz)
    ls, lm = sun_longitude(jd), moon_longitude(jd)
    sun_sign, sun_deg = _sign(ls)
    moon_sign, moon_deg = _sign(lm)
    steps.append(f"sun λ={ls:.2f}° -> {sun_sign} {sun_deg:.1f}°; moon λ={lm:.2f}° -> {moon_sign} {moon_deg:.1f}°")
    cusp = min(sun_deg, 30 - sun_deg) < 1.0 or min(moon_deg, 30 - moon_deg) < 1.0
    return {"value": {"sun": {"sign": sun_sign, "deg": round(sun_deg, 1)},
                      "moon": {"sign": moon_sign, "deg": round(moon_deg, 1)},
                      "cusp_warning": cusp},
            "method": "tropical zodiac; Meeus low-precision sun, truncated lunar theory (sign-accurate; ~1° cusp flagged)",
            "steps": steps}


if __name__ == "__main__":
    import json
    import sys
    y, m, d = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    hour = float(sys.argv[4]) if len(sys.argv) > 4 else None
    tz = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
    print(json.dumps({"life_path": life_path(y, m, d),
                      "bazi": bazi(y, m, d, hour, tz),
                      "western": western(y, m, d, hour if hour is not None else 12.0, tz)},
                     ensure_ascii=False, indent=1))
