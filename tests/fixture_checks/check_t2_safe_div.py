from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

fixture = Path(__file__).resolve().parents[2] / "fixtures" / "t2_fix_failing_test_div" / "input.py"
spec = spec_from_file_location("checked_t2_input", fixture)
if spec is None or spec.loader is None:
    raise SystemExit("FAIL: could not load t2 fixture")
module = module_from_spec(spec)
spec.loader.exec_module(module)

cases = [
    (10, 2, 5.0),
    (1, 0, 0.0),
    (-4, 2, -2.0),
    (7.5, 2.5, 3.0),
    (-3, 0.0, 0.0),
    (9, -0.0, 0.0),
    (1, -4, -0.25),
]
for a, b, expected in cases:
    try:
        actual = module.safe_div(a, b)
    except Exception as exc:
        raise SystemExit(f"FAIL {a!r},{b!r}: raised {type(exc).__name__}: {exc}") from exc
    if type(actual) is not float:
        raise SystemExit(f"FAIL {a!r},{b!r}: result type {type(actual).__name__} is not float")
    if actual != expected:
        raise SystemExit(f"FAIL {a!r},{b!r}: {actual!r} != {expected!r}")
print("OK")
