import solar  # noqa: F401  (read-only helper: jdn, jd_ut, sun_longitude)

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def year_month_pillars(y: int, m: int, d: int, hour: float, tz: float) -> tuple[str, str]:
    # Compute sun's longitude at birth
    jd = solar.jd_ut(y, m, d, hour, tz)
    lam = solar.sun_longitude(jd)
    
    # Determine solar year
    if m < 2:
        solar_year = y - 1
    elif m > 2:
        solar_year = y
    else:  # m == 2
        if lam >= 315:
            solar_year = y
        else:
            solar_year = y - 1
    
    # Compute year pillar
    year_stem_index = (solar_year - 4) % 10
    year_branch_index = (solar_year - 4) % 12
    year_stem = STEMS[year_stem_index]
    year_branch = BRANCHES[year_branch_index]
    year_pillar = year_stem + year_branch
    
    # Determine month index
    offset = (lam - 315) % 360
    month = int(offset // 30)
    
    # Compute month pillar
    month_branch_index = (2 + month) % 12
    month_branch = BRANCHES[month_branch_index]
    
    first = ((year_stem_index % 5) * 2 + 2) % 10
    month_stem_index = (first + month) % 10
    month_stem = STEMS[month_stem_index]
    month_pillar = month_stem + month_branch
    
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
