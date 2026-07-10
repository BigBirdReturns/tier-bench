"""Calendar helper (read-only)."""


def jdn(y: int, m: int, d: int) -> int:
    """Julian day number of the civil date y-m-d (integer, noon-based)."""
    a = (14 - m) // 12
    y2 = y + 4800 - a
    m2 = m + 12 * a - 3
    return d + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - y2 // 100 + y2 // 400 - 32045
