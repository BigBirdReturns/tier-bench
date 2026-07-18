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


def expect_value_error(function, value):
    try:
        function(value)
    except ValueError:
        return
    raise AssertionError(f"ValueError not raised for {value!r}")


def main() -> int:
    module = load(Path(sys.argv[1]))
    function = getattr(module, "dependency_batches")
    graph = {"ship": ["test", "docs"], "test": ["build"], "docs": [], "build": []}
    before = repr(graph)
    cases = [
        ({}, []),
        ({"b": [], "a": []}, [["a", "b"]]),
        (graph, [["build", "docs"], ["test"], ["ship"]]),
        ({"d": {"b", "c"}, "c": {"a"}, "b": {"a"}, "a": set()}, [["a"], ["b", "c"], ["d"]]),
    ]
    for dependencies, expected in cases:
        frozen = repr(dependencies)
        actual = function(dependencies)
        assert actual == expected, (dependencies, actual, expected)
        assert repr(dependencies) == frozen, "input mutated"
        assert all(batch == sorted(batch) for batch in actual)
    expect_value_error(function, {"a": ["missing"]})
    expect_value_error(function, {"a": ["a"]})
    expect_value_error(function, {"a": ["b"], "b": ["c"], "c": ["a"]})
    assert repr(graph) == before, "shared input mutated"
    print("PASS dependency_batches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

