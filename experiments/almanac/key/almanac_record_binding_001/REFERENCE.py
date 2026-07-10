# Key material: correct implementation — day/hour bind to the civil record.
import cal

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def day_hour_pillars(y, m, d, hour, tz):
    idx = (cal.jdn(y, m, d) - 2458631) % 60
    ds, db = idx % 10, idx % 12
    hb = int((hour + 1) // 2) % 12
    hs = ((ds % 5) * 2 + hb) % 10
    return STEMS[ds] + BRANCHES[db], STEMS[hs] + BRANCHES[hb]
