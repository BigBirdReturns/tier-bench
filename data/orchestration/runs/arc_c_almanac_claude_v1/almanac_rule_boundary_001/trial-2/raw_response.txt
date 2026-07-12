"""Four Pillars year + month — the solar-boundary rules, applied exactly.

Implement:

    def year_month_pillars(y, m, d, hour, tz) -> tuple[str, str]

Input is a civil local datetime: year/month/day ints, `hour` a float in
[0, 24) local clock time, `tz` the UTC offset in hours (may be negative or
fractional). Return `(year_pillar, month_pillar)`, each a two-character
string: a heavenly stem from STEMS followed by an earthly branch from
BRANCHES.

The rules (complete — every sentence is normative):

1. All boundaries in this system are positions of the sun. Compute the sun's
   apparent longitude λ (degrees, [0, 360)) at the instant of birth using the
   provided helpers: `solar.sun_longitude(solar.jd_ut(y, m, d, hour, tz))`.

2. THE SOLAR YEAR begins at the instant λ reaches 315° (the term lichun,
   early February) and runs until λ next reaches 315°. The solar year that
   begins at lichun of calendar year Y is numbered Y. A birth belongs to the
   solar year in effect at the birth instant.
   The year pillar of solar year Y is: stem STEMS[(Y - 4) % 10],
   branch BRANCHES[(Y - 4) % 12].

3. THE SOLAR MONTH is a 30° band of λ. Month index k (k = 0..11) spans
   λ ∈ [315° + 30k, 345° + 30k) (mod 360). Its branch is
   BRANCHES[(2 + k) % 12]. Its stem follows the five-tigers rule: the stem of
   month k is STEMS[(first + k) % 10] where
   first = ((year_stem_index % 5) * 2 + 2) % 10 and year_stem_index is the
   index in STEMS of the year pillar's stem for the solar year in effect.

Notes that decide edge cases: the boundary comparisons are on λ at the exact
birth instant in UT — the civil calendar date, the calendar month, and the
timezone label play no role beyond fixing that instant. Inputs are ordinary
birth datetimes; you do not need sub-minute boundary precision.

STEMS = "甲乙丙丁戊己庚辛壬癸"   (index 0..9)
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"   (index 0..11)
"""
import solar  # noqa: F401  (read-only helper: jdn, jd_ut, sun_longitude)

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def year_month_pillars(y: int, m: int, d: int, hour: float, tz: float) -> tuple[str, str]:
    lam = solar.sun_longitude(solar.jd_ut(y, m, d, hour, tz))

    # Month index k: lambda in [315 + 30k, 345 + 30k) mod 360
    k = int(((lam - 315.0) % 360.0) // 30.0)

    # Solar year: begins at lichun (lambda = 315) of calendar year Y.
    # Determine whether birth is before or after this calendar year's lichun.
    # lambda in [315, 360): after lichun, but which calendar year's?
    # Lichun falls in early February. If birth is in Jan/early Feb before
    # lichun (lambda in [270, 315)), solar year is y - 1. If lambda >= 315
    # and the civil date is early in the year (Jan-Feb), solar year is y
    # (just past lichun of year y). If lambda >= 315 and civil date is late
    # in the year (Dec), lichun of year y+1 hasn't happened in reality —
    # but lambda only reaches [315, 360) in Feb-Mar and Jan?? No: lambda
    # increases ~1 deg/day; [315,360) corresponds to ~Feb 4 - Mar 20, and
    # [270,315) to ~Dec 21 - Feb 4. So:
    # lambda in [315, 360): after lichun of year y (Feb-Mar) -> solar year y
    # lambda in [0, 315): 
    #   if civil month is Jan/Feb (before lichun, lambda in [280,315)) or
    #   Dec (lambda in [270,280)) -> could be y-1 or y.
    # Robust rule: birth is before lichun of calendar year y iff the birth
    # instant precedes the moment lambda hits 315 in early Feb of year y.
    # Since lambda in [270, 315) only occurs Dec 21 (year Y) - Feb 4 (year
    # Y+1): if lambda >= 270 and lambda < 315 and m >= 6 -> Dec of year y,
    # solar year y; if m < 6 -> Jan/early-Feb, before lichun, solar year y-1.
    if 270.0 <= lam < 315.0 and m < 6:
        sy = y - 1
    else:
        sy = y

    year_stem_i = (sy - 4) % 10
    year_branch_i = (sy - 4) % 12
    year_pillar = STEMS[year_stem_i] + BRANCHES[year_branch_i]

    first = ((year_stem_i % 5) * 2 + 2) % 10
    month_pillar = STEMS[(first + k) % 10] + BRANCHES[(2 + k) % 12]
    return (year_pillar, month_pillar)


def main() -> int:
    checks = [
        ((2000, 5, 5, 18.0, 0.0), ("庚辰", "辛巳")),
        ((1993, 8, 17, 23.5, 0.0), ("癸酉", "庚申")),
        ((1970, 11, 8, 12.0, 0.0), ("庚戌", "丁亥")),
    ]
    ok = True
    for args, want in checks:
        got = year_month_pillars(*args)
        if tuple(got) != want:
            print(f"FAIL {args}: got {got}, want {want}")
            ok = False
    if ok:
        print("OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
