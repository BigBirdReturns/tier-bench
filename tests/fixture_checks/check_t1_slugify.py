from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re

fixture = Path(__file__).resolve().parents[2] / "fixtures" / "t1_impl_from_docstring" / "input.py"
spec = spec_from_file_location("checked_t1_input", fixture)
if spec is None or spec.loader is None:
    raise SystemExit("FAIL: could not load t1 fixture")
module = module_from_spec(spec)
spec.loader.exec_module(module)

source = fixture.read_text(encoding="utf-8")
if not callable(getattr(module, "main", None)):
    raise SystemExit("FAIL: fixture no longer defines a callable main()")
if re.search(r'if __name__ == .__main__.:\s*\n\s*main\(\)', source) is None:
    raise SystemExit("FAIL: fixture no longer retains the __main__ guard calling main()")

cases = [
    (" Hello_World  ", "hello-world"),
    ("A--B", "a-b"),
    ("", ""),
    ("Spaced   out", "spaced-out"),
    ("Café", "caf"),
    ("___Alpha!!!Beta___", "-alphabeta-"),
    ("  Mixed_CASE-123  ", "mixed-case-123"),
    ("a -_- b", "a-b"),
]
for source, expected in cases:
    try:
        actual = module.slugify(source)
    except Exception as exc:
        raise SystemExit(f"FAIL {source!r}: raised {type(exc).__name__}: {exc}") from exc
    if actual != expected:
        raise SystemExit(f"FAIL {source!r}: {actual!r} != {expected!r}")
print("OK")
