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
    function = getattr(module, "merge_closed_ranges")
    source = [(9, 7), (1, 3), (4, 6), (20, 20), (22, 21)]
    before = list(source)
    cases = [
        ([], []),
        ([(5, 1)], [(1, 5)]),
        ([(1, 3), (4, 7)], [(1, 7)]),
        ([(1, 3), (5, 7)], [(1, 3), (5, 7)]),
        (source, [(1, 9), (20, 22)]),
        ([(-1, -3), (-4, -4), (0, 0), (2, 1)], [(-4, 2)]),
        ([(1, 10), (3, 4), (10, 12)], [(1, 12)]),
    ]
    for ranges, expected in cases:
        frozen = list(ranges)
        actual = function(ranges)
        assert actual == expected, (ranges, actual, expected)
        assert ranges == frozen, "input mutated"
        assert all(isinstance(item, tuple) and len(item) == 2 for item in actual)
    assert source == before, "shared input mutated"
    print("PASS merge_closed_ranges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

