"""Four Pillars year + month — the solar-boundary rules, applied exactly."""
import solar  # noqa: F401

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def year_month_pillars(y: int, m: int, d: int, hour: float, tz: float) -> tuple[str, str]:
    lam = solar.sun_longitude(solar.jd_ut(y, m, d, hour, tz))
    # Solar year: begins at lichun (lambda = 315) of calendar year Y.
    # In Jan/early-Feb, lambda is in (~280, 315) before lichun -> previous solar year.
    if m < 3 and 180.0 < lam < 315.0:
        Y = y - 1
    else:
        Y = y
    ys = (Y - 4) % 10
    yb = (Y - 4) % 12
    year_pillar = STEMS[ys] + BRANCHES[yb]

    k = int(((lam - 315.0) % 360.0) // 30.0)
    branch = BRANCHES[(2 + k) % 12]
    first = ((ys % 5) * 2 + 2) % 10
    stem = STEMS[(first + k) % 10]
    return (year_pillar, stem + branch)


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
