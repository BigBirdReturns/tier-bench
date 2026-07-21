def safe_div(a: float, b: float) -> float:
    """Return a/b. If b is 0, return 0.0. Must not raise."""
    if b == 0:
        return 0.0
    return a / b

def main():
    cases = [(10, 2, 5.0), (1, 0, 0.0), (-4, 2, -2.0)]
    for a, b, exp in cases:
        got = safe_div(a, b)
        if got != exp:
            raise SystemExit(f"FAIL {a},{b}: {got} != {exp}")
    print("OK")

if __name__ == "__main__":
    main()
