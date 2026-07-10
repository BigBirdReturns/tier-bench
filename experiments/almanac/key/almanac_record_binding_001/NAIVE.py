# Key material: the plausible wrong binding — converts to UT first (as one
# must for the sun-position pillars) and computes day/hour from the UT record.
import cal

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def day_hour_pillars(y, m, d, hour, tz):
    j = cal.jdn(y, m, d)
    ut = hour - tz
    while ut < 0:
        ut += 24.0
        j -= 1
    while ut >= 24.0:
        ut -= 24.0
        j += 1
    idx = (j - 2458631) % 60
    ds, db = idx % 10, idx % 12
    hb = int((ut + 1) // 2) % 12
    hs = ((ds % 5) * 2 + hb) % 10
    return STEMS[ds] + BRANCHES[db], STEMS[hs] + BRANCHES[hb]
