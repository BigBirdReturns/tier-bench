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
    # Compute sun's longitude at the birth instant
    jd_ut_val = solar.jd_ut(y, m, d, hour, tz)
    lam = solar.sun_longitude(jd_ut_val)

    # Determine solar year
    # Lichun (315°) occurs around Feb 4 each year.
    # If month > 2, we're past February, so we're in solar year y.
    # If month == 2, check λ: if λ >= 315°, we haven't reached lichun yet (solar year y-1),
    # otherwise we've passed it (solar year y).
    # If month < 2, we're before February, so we're in solar year y-1.
    if m > 2:
        solar_year = y
    elif m == 2:
        if lam >= 315.0:
            solar_year = y - 1
        else:
            solar_year = y
    else:  # m < 2, i.e., m == 1
        solar_year = y - 1

    # Year pillar calculation
    year_stem_idx = (solar_year - 4) % 10
    year_branch_idx = (solar_year - 4) % 12
    year_stem = STEMS[year_stem_idx]
    year_branch = BRANCHES[year_branch_idx]
    year_pillar = year_stem + year_branch

    # Determine solar month (k = 0..11)
    # Month k spans λ ∈ [315 + 30k, 345 + 30k) (mod 360)
    # We shift λ so that 315° becomes 0°, then divide by 30 to get the month index
    lam_shifted = (lam - 315.0) % 360.0
    month_idx = int(lam_shifted / 30.0) % 12

    # Month pillar calculation
    month_branch_idx = (2 + month_idx) % 12
    month_branch = BRANCHES[month_branch_idx]

    # Five-tigers rule for month stem
    first = ((year_stem_idx % 5) * 2 + 2) % 10
    month_stem_idx = (first + month_idx) % 10
    month_stem = STEMS[month_stem_idx]

    month_pillar = month_stem + month_branch

    return (year_pillar, month_pillar)


def main() -> int:
    checks = [
        # ordinary mid-band dates (no boundary in play)
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
