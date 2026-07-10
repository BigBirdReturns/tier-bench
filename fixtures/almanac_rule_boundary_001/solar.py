"""Solar helpers (read-only). Provided so the task is the RULE, not the ephemeris."""
import math


def jdn(y: int, m: int, d: int) -> int:
    """Julian day number of the civil date y-m-d (integer, noon-based)."""
    a = (14 - m) // 12
    y2 = y + 4800 - a
    m2 = m + 12 * a - 3
    return d + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - y2 // 100 + y2 // 400 - 32045


def jd_ut(y: int, m: int, d: int, hour: float = 12.0, tz: float = 0.0) -> float:
    """Julian date (UT) for local civil time `hour` at UTC offset `tz` hours."""
    return jdn(y, m, d) - 0.5 + (hour - tz) / 24.0


def _sind(x):
    return math.sin(math.radians(x))


def sun_longitude(jd: float) -> float:
    """Apparent-ish solar longitude in degrees [0, 360), Meeus low precision."""
    t = (jd - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * _sind(m)
         + (0.019993 - 0.000101 * t) * _sind(2 * m) + 0.000289 * _sind(3 * m))
    return (l0 + c) % 360.0
