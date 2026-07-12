"""Four Pillars day + hour — bind each pillar to the record that governs it.

Implement:

    def day_hour_pillars(y, m, d, hour, tz) -> tuple[str, str]

Input is a civil local datetime: year/month/day ints, `hour` a float in
[0, 24) local clock time, `tz` the UTC offset in hours (may be negative or
fractional). Return `(day_pillar, hour_pillar)`, each a two-character string:
a heavenly stem from STEMS followed by an earthly branch from BRANCHES.

The rules (complete — every sentence is normative):

1. THE DAY PILLAR follows the unbroken sexagenary day cycle over civil dates.
   The cycle index of civil date (y, m, d) is
       idx = (cal.jdn(y, m, d) - 2458631) % 60
   where JDN 2458631 is the anchor date 2019-05-27, whose cycle index is 0
   (pillar 甲子). A day's pillar is stem STEMS[idx % 10], branch
   BRANCHES[idx % 12]. The day is the CIVIL LOCAL DATE as given, and it rolls
   at local midnight.

2. THE HOUR PILLAR divides the civil local clock into twelve two-hour
   branches: the branch index is int((hour + 1) // 2) % 12 (so 23:00-00:59 is
   子, 01:00-02:59 is 丑, and so on). Its stem follows the five-rats rule:
   STEMS[((day_stem_index % 5) * 2 + hb) % 10], where day_stem_index is the
   index in STEMS of the day pillar's stem for the SAME civil date used in
   rule 1, and hb is the hour-branch index.

Notes that decide edge cases: these two pillars are functions of the civil
record — the local calendar date and the local clock reading. In the wider
system other pillars are computed from the sun's position at the absolute
instant (which is why `tz` is part of every birth record); the day and hour
pillars are not among them. A 23:xx birth is in the 子 branch of the same
civil day it was recorded under.

STEMS = "甲乙丙丁戊己庚辛壬癸"   (index 0..9)
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"   (index 0..11)
"""
import cal  # noqa: F401  (read-only helper: jdn)

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def day_hour_pillars(y: int, m: int, d: int, hour: float, tz: float) -> tuple[str, str]:
    idx = (cal.jdn(y, m, d) - 2458631) % 60
    day_stem = idx % 10
    day_pillar = STEMS[day_stem] + BRANCHES[idx % 12]
    hb = int((hour + 1) // 2) % 12
    hour_pillar = STEMS[((day_stem % 5) * 2 + hb) % 10] + BRANCHES[hb]
    return (day_pillar, hour_pillar)


def main() -> int:
    checks = [
        ((2019, 5, 27, 0.5, 0.0), ("甲子", "甲子")),
        ((1975, 6, 21, 13.0, 3.0), ("戊戌", "己未")),
        ((2010, 10, 10, 22.9, 0.0), ("癸巳", "癸亥")),
    ]
    ok = True
    for args, want in checks:
        got = day_hour_pillars(*args)
        if tuple(got) != want:
            print(f"FAIL {args}: got {got}, want {want}")
            ok = False
    if ok:
        print("OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
