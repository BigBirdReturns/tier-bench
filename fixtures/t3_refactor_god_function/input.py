"""Tests for pipeline.py refactoring.

Tests both correctness (same output) and structure (actually refactored).
"""
import ast
import inspect
from pipeline import process_report

SAMPLE_CSV = """name,region,amount,quarter
Alice,North,1500.00,Q1
Bob,South,2300.50,Q2
Carol,North,800.00,Q1
Dave,South,-100.00,Q3
Eve,West,1200.00,Q2
Eve,West,1200.00,Q2
,North,500.00,Q1
Frank,East,bad_number,Q4
"""

EXPECTED_FRAGMENTS = [
    "SALES REPORT",
    "Records: 4 valid, 4 errors",
    "Total: $5,800.50",
    "Average: $1,450.12",
    "Highest: Bob $2,300.50",
    "Lowest: Carol $800.00",
    "North: $2,300.00 (2 sales)",
    "South: $2,300.50 (1 sales)",
    "West: $1,200.00 (1 sales)",
    "negative amount",
    "duplicate entry",
    "empty name",
    "invalid amount",
]


def test_correctness():
    """The refactored code must produce the same report."""
    result = process_report(SAMPLE_CSV)
    for frag in EXPECTED_FRAGMENTS:
        assert frag in result, f"Missing in report: '{frag}'\n\nGot:\n{result}"


def test_edge_empty():
    assert process_report("").startswith("ERROR")


def test_edge_header_only():
    assert process_report("name,amount\n").startswith("ERROR")


def test_edge_missing_columns():
    assert "Missing required" in process_report("foo,bar\n1,2\n")


def test_structure_refactored():
    """The god function must actually be broken up.

    Rules:
    - process_report must exist and still work (tested above)
    - pipeline.py must have at least 3 top-level functions (was 1)
    - process_report body must be <=40 lines (was ~70)
    """
    source = inspect.getsource(inspect.getmodule(process_report))
    tree = ast.parse(source)

    top_level_funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    func_names = [f.name for f in top_level_funcs]

    assert len(top_level_funcs) >= 3, (
        f"Expected at least 3 top-level functions (refactored), "
        f"found {len(top_level_funcs)}: {func_names}"
    )

    # Find process_report and check its length
    pr_node = None
    for f in top_level_funcs:
        if f.name == "process_report":
            pr_node = f
            break
    assert pr_node is not None, "process_report function not found"

    body_lines = pr_node.end_lineno - pr_node.lineno
    assert body_lines <= 40, (
        f"process_report is still {body_lines} lines. "
        f"Refactor it to <=40 lines by extracting helpers."
    )


def main():
    tests = [
        test_correctness,
        test_edge_empty,
        test_edge_header_only,
        test_edge_missing_columns,
        test_structure_refactored,
    ]
    for t in tests:
        try:
            t()
        except AssertionError as e:
            raise SystemExit(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            raise SystemExit(f"ERROR {t.__name__}: {e}")
    print("OK")


if __name__ == "__main__":
    main()
