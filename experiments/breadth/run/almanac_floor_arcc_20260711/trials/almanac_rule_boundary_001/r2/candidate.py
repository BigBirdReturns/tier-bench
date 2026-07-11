import solar

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def year_month_pillars(y: int, m: int, d: int, hour: float, tz: float) -> tuple[str, str]:
    # Compute sun's longitude at birth
    jd = solar.jd_ut(y, m, d, hour, tz)
    lambda_birth = solar.sun_longitude(jd)
    
    # Find the solar year (by which lichun crossing)
    solar_year = _find_solar_year(y, m, d, hour, tz)
    
    # Year pillar
    year_stem_index = (solar_year - 4) % 10
    year_branch_index = (solar_year - 4) % 12
    year_pillar = STEMS[year_stem_index] + BRANCHES[year_branch_index]
    
    # Find the solar month (which 30° band)
    month_index = _find_month_index(lambda_birth)
    
    # Month pillar
    month_branch_index = (2 + month_index) % 12
    first = ((year_stem_index % 5) * 2 + 2) % 10
    month_stem_index = (first + month_index) % 10
    month_pillar = STEMS[month_stem_index] + BRANCHES[month_branch_index]
    
    return (year_pillar, month_pillar)


def _find_solar_year(y: int, m: int, d: int, hour: float, tz: float) -> int:
    """Find the solar year number (by which calendar year's lichun) of a birth."""
    jd_birth = solar.jd_ut(y, m, d, hour, tz)
    
    most_recent_lichun_year = y - 1
    most_recent_lichun_jd = -1e9
    
    for check_year in range(y - 2, y + 2):
        # Binary search for when λ = 315° (lichun) in check_year
        jd_low = solar.jd_ut(check_year, 1, 1, 0, tz)
        jd_high = solar.jd_ut(check_year, 3, 1, 0, tz)
        
        # Binary search converges to λ = 315°
        for _ in range(100):
            jd_mid = (jd_low + jd_high) / 2
            lambda_mid = solar.sun_longitude(jd_mid)
            
            if lambda_mid < 315:
                jd_low = jd_mid
            else:
                jd_high = jd_mid
        
        jd_lichun = (jd_low + jd_high) / 2
        
        # Track the most recent lichun before or at birth
        if jd_lichun <= jd_birth and jd_lichun > most_recent_lichun_jd:
            most_recent_lichun_jd = jd_lichun
            most_recent_lichun_year = check_year
    
    return most_recent_lichun_year


def _find_month_index(lambda_birth: float) -> int:
    """Find the month index (0-11) from sun's longitude.
    
    Month k spans λ ∈ [315° + 30k, 345° + 30k) (mod 360).
    """
    offset = (lambda_birth - 315) % 360
    month = int(offset / 30)
    return month % 12


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
