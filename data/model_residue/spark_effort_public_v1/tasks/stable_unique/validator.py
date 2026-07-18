from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load(path: Path):
    spec = importlib.util.spec_from_file_location("candidate", path)
    if spec is None or spec.loader is None:
        raise AssertionError("candidate could not be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load(Path(sys.argv[1]))
    function = getattr(module, "stable_unique")
    nested = [{"a": [1, 2]}, {"a": [1, 2]}, [1, {"b": 2}], [1, {"b": 2}]]
    original = repr(nested)
    cases = [
        ([], []),
        ([3, 1, 3, 2, 1], [3, 1, 2]),
        ([True, 1, False, 0, 2], [True, False, 2]),
        (nested, [{"a": [1, 2]}, [1, {"b": 2}]]),
        ([{"x": 1}, {"x": 2}, {"x": 1}], [{"x": 1}, {"x": 2}]),
    ]
    for items, expected in cases:
        before = repr(items)
        actual = function(items)
        assert actual == expected, (items, actual, expected)
        assert repr(items) == before, "input mutated"
        assert isinstance(actual, list), "result is not a list"
    assert repr(nested) == original, "nested input mutated"
    print("PASS stable_unique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

