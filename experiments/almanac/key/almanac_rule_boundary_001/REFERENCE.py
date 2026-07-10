# Key material (never in a solver packet): correct implementation per the spec.
import solar

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def year_month_pillars(y, m, d, hour, tz):
    lam = solar.sun_longitude(solar.jd_ut(y, m, d, hour, tz))
    k = int(((lam - 315.0) % 360.0) // 30.0)
    solar_year = y - 1 if (k >= 10 and m <= 3) else y
    ys, yb = (solar_year - 4) % 10, (solar_year - 4) % 12
    first = ((ys % 5) * 2 + 2) % 10
    ms, mb = (first + k) % 10, (2 + k) % 12
    return STEMS[ys] + BRANCHES[yb], STEMS[ms] + BRANCHES[mb]
