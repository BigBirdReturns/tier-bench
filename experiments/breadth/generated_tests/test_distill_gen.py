# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=scripts\distill.py  mutation_score=3/7
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
"""Characterization tests for distill.py public behavior."""


import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

from distill import build_curriculum, format_exemplar, load_traces, main as distill_main, passed_only, render_text


def _run_main_with_args(argv: list[str], spec_path: Path | None = None) -> tuple[int, str]:
    original_argv = sys.argv
    old_spec_path = None
    if spec_path is not None:
        import distill

        old_spec_path = distill.DRIVER_SPEC_PATH
        distill.DRIVER_SPEC_PATH = spec_path
    output = io.StringIO()
    try:
        sys.argv = argv
        with contextlib.redirect_stdout(output):
            status = distill_main()
    finally:
        sys.argv = original_argv
        if spec_path is not None:
            import distill

            distill.DRIVER_SPEC_PATH = old_spec_path
    return status, output.getvalue()


def test_load_traces_filters_invalid_lines_and_requires_keys() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        traces = Path(tmpdir) / "traces.jsonl"
        traces.write_text(
            "\n"
            "   \n"
            "{invalid\n"
            "{\"task_id\":\"t2\",\"tier\":\"easy\",\"hands_model\":\"h2\",\"validator_report\":{},\"driver_model\":\"d2\",\"driver_output\":\"ok\"}\n"
            "\"just-a-string\"\n"
            "[1, 2, 3]\n"
            "{\"task_id\":\"t1\",\"tier\":\"hard\",\"hands_model\":\"h1\",\"hands_output\":\"attempt\",\"validator_report\":[],\"driver_model\":\"d1\",\"driver_output\":\"fix\",\"passed\":true}\n",
            encoding="utf-8",
        )
        traces_data = load_traces(traces)
        assert len(traces_data) == 1
        assert traces_data[0]["task_id"] == "t1"
        assert traces_data[0]["passed"] is True
        assert traces_data[0]["hands_output"] == "attempt"


def test_load_traces_raises_file_not_found_for_missing_path() -> None:
    try:
        load_traces(Path("does_not_exist_123456789.jsonl"))
    except FileNotFoundError:
        return
    assert False, "Expected FileNotFoundError when traces file does not exist"


def test_passed_only_matches_strict_true() -> None:
    traces = [
        {"passed": True, "x": 1},
        {"passed": False, "x": 2},
        {"passed": 1, "x": 3},
        {"x": 4},
    ]
    result = passed_only(traces)
    assert len(result) == 1
    assert result[0]["x"] == 1


def test_format_exemplar_includes_fallbacks_and_report() -> None:
    trace = {
        "task_id": "task-1",
        "tier": "2",
        "hands_model": "hands-A",
        "hands_output": None,
        "validator_report": {"status": "good", "line": 1},
        "driver_model": "driver-B",
        "driver_output": None,
    }
    expected = (
        "### Exemplar 3 -- task-1 (2)\n\n"
        "TASK: task-1 (tier 2), attempted by hands model `hands-A`.\n\n"
        "FAILED ATTEMPT:\n"
        "(no usable output)\n\n"
        "VALIDATOR REPORT:\n"
        '{\n  "status": "good",\n  "line": 1\n}\n\n'
        "CORRECT REPAIR (by driver `driver-B`):\n"
        "(no output)\n"
    )
    assert format_exemplar(trace, 3) == expected


def test_build_curriculum_filters_passed_respects_limit_and_preserves_fields() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        traces = Path(tmpdir) / "traces.jsonl"
        traces.write_text(
            "\n"
            "{\"task_id\":\"t1\",\"tier\":\"low\",\"hands_model\":\"h1\",\"hands_output\":\"out1\",\"validator_report\":{},\"driver_model\":\"d1\",\"driver_output\":\"fix1\",\"passed\":true}\n"
            "{\"task_id\":\"t2\",\"tier\":\"low\",\"hands_model\":\"h2\",\"hands_output\":\"out2\",\"validator_report\":{\"ok\":true},\"driver_model\":\"d2\",\"driver_output\":\"fix2\",\"passed\":false}\n"
            "{\"task_id\":\"t3\",\"tier\":\"high\",\"hands_model\":\"h3\",\"hands_output\":\"out3\",\"validator_report\":{\"nested\":{\"value\":1}},\"driver_model\":\"d3\",\"driver_output\":\"fix3\",\"passed\":true}\n",
            encoding="utf-8",
        )
        spec_path = Path(tmpdir) / "README.md"
        spec_path.write_text("SPEC BODY", encoding="utf-8")
        import distill

        original_spec = distill.DRIVER_SPEC_PATH
        distill.DRIVER_SPEC_PATH = spec_path
        try:
            curriculum = build_curriculum(traces, 1)
            assert curriculum["spec"] == "SPEC BODY"
            assert curriculum["total_passed_traces"] == 2
            assert len(curriculum["exemplars"]) == 1
            assert curriculum["exemplars"][0] == {
                "task_id": "t1",
                "tier": "low",
                "hands_model": "h1",
                "hands_output": "out1",
                "validator_report": {},
                "driver_model": "d1",
                "driver_output": "fix1",
            }
        finally:
            distill.DRIVER_SPEC_PATH = original_spec


def test_build_curriculum_negative_limit_uses_python_slice_semantics() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        traces = Path(tmpdir) / "traces.jsonl"
        traces.write_text(
            "{\"task_id\":\"a\",\"tier\":\"low\",\"hands_model\":\"h\",\"hands_output\":\"1\",\"validator_report\":{},\"driver_model\":\"d\",\"driver_output\":\"x\",\"passed\":true}\n"
            "{\"task_id\":\"b\",\"tier\":\"low\",\"hands_model\":\"h\",\"hands_output\":\"2\",\"validator_report\":{},\"driver_model\":\"d\",\"driver_output\":\"y\",\"passed\":true}\n"
            "{\"task_id\":\"c\",\"tier\":\"low\",\"hands_model\":\"h\",\"hands_output\":\"3\",\"validator_report\":{},\"driver_model\":\"d\",\"driver_output\":\"z\",\"passed\":true}\n",
            encoding="utf-8",
        )
        spec_path = Path(tmpdir) / "README.md"
        spec_path.write_text("SPEC", encoding="utf-8")
        import distill

        original_spec = distill.DRIVER_SPEC_PATH
        distill.DRIVER_SPEC_PATH = spec_path
        try:
            curriculum = build_curriculum(traces, -1)
            assert [entry["task_id"] for entry in curriculum["exemplars"]] == ["a", "b"]
            assert curriculum["total_passed_traces"] == 3
        finally:
            distill.DRIVER_SPEC_PATH = original_spec


def test_render_text_no_exemplars_message() -> None:
    curriculum = {
        "spec": "SPEC BODY",
        "exemplars": [],
        "total_passed_traces": 0,
    }
    text = render_text(curriculum)
    assert text == (
        "SPEC BODY\n\n\n---\n\n(No passed driver_repair traces yet -- spec only. "
        "Run a driver_repair benchmark to generate exemplars.)\n"
    )


def test_render_text_with_exemplars() -> None:
    curriculum = {
        "spec": "SPEC BODY",
        "exemplars": [
            {
                "task_id": "task-1",
                "tier": "low",
                "hands_model": "hands-A",
                "hands_output": "attempt",
                "validator_report": {"ok": True},
                "driver_model": "driver-B",
                "driver_output": "fix",
            },
        ],
        "total_passed_traces": 3,
    }
    text = render_text(curriculum)
    assert text.startswith(
        "SPEC BODY\n\n\n---\n\n## Worked examples (1 of 3 passed traces)\n\n\n"
        "### Exemplar 1 -- task-1 (low)\n\nTASK: task-1 (tier low), attempted by "
        "hands model `hands-A`.\n\nFAILED ATTEMPT:\nattempt\n\n"
    )
    assert text.endswith(
        'CORRECT REPAIR (by driver `driver-B`):\nfix\n'
    )


def test_main_missing_traces_returns_two_with_help_text() -> None:
    status, output = _run_main_with_args([
        "distill",
        "--traces",
        "definitely-missing-traces.jsonl",
    ])
    assert status == 2
    assert output.startswith("No traces at definitely-missing-traces.jsonl.")


def test_main_empty_traces_file_returns_two() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_file = Path(tmpdir) / "empty.jsonl"
        trace_file.write_text("", encoding="utf-8")
        status, output = _run_main_with_args(["distill", "--traces", str(trace_file)])
        assert status == 2
        assert "No traces at" in output


def test_main_json_mode_emits_expected_fields_and_limits() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_file = Path(tmpdir) / "traces.jsonl"
        trace_file.write_text(
            "{\"task_id\":\"t1\",\"tier\":\"low\",\"hands_model\":\"h\",\"hands_output\":\"attempt\",\"validator_report\":{},\"driver_model\":\"d\",\"driver_output\":\"fix\",\"passed\":true}\n"
            "{\"task_id\":\"t2\",\"tier\":\"high\",\"hands_model\":\"h\",\"hands_output\":\"attempt2\",\"validator_report\":{\"x\":1},\"driver_model\":\"d\",\"driver_output\":\"fix2\",\"passed\":true}\n",
            encoding="utf-8",
        )
        spec_file = Path(tmpdir) / "README.md"
        spec_file.write_text("SPEC", encoding="utf-8")
        status, output = _run_main_with_args(
            [
                "distill",
                "--traces",
                str(trace_file),
                "--json",
                "--limit",
                "1",
            ],
            spec_path=spec_file,
        )
        assert status == 0
        payload = json.loads(output)
        assert payload["spec"] == "SPEC"
        assert payload["total_passed_traces"] == 2
        assert len(payload["exemplars"]) == 1
        assert payload["exemplars"][0] == {
            "task_id": "t1",
            "tier": "low",
            "hands_model": "h",
            "hands_output": "attempt",
            "validator_report": {},
            "driver_model": "d",
            "driver_output": "fix",
        }


def test_main_limits_negative_to_zero_and_emits_no_examples_text() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_file = Path(tmpdir) / "traces.jsonl"
        trace_file.write_text(
            "{\"task_id\":\"t1\",\"tier\":\"low\",\"hands_model\":\"h\",\"hands_output\":\"attempt\",\"validator_report\":{},\"driver_model\":\"d\",\"driver_output\":\"fix\",\"passed\":true}\n",
            encoding="utf-8",
        )
        spec_file = Path(tmpdir) / "README.md"
        spec_file.write_text("SPEC", encoding="utf-8")
        status, output = _run_main_with_args(
            [
                "distill",
                "--traces",
                str(trace_file),
                "--limit",
                "-2",
            ],
            spec_path=spec_file,
        )
        assert status == 0
        assert "## Worked examples" not in output
        assert "(No passed driver_repair traces yet -- spec only. Run a driver_repair benchmark to generate exemplars.)" in output


def main() -> None:
    tests = [
        test_load_traces_filters_invalid_lines_and_requires_keys,
        test_load_traces_raises_file_not_found_for_missing_path,
        test_passed_only_matches_strict_true,
        test_format_exemplar_includes_fallbacks_and_report,
        test_build_curriculum_filters_passed_respects_limit_and_preserves_fields,
        test_build_curriculum_negative_limit_uses_python_slice_semantics,
        test_render_text_no_exemplars_message,
        test_render_text_with_exemplars,
        test_main_missing_traces_returns_two_with_help_text,
        test_main_empty_traces_file_returns_two,
        test_main_json_mode_emits_expected_fields_and_limits,
        test_main_limits_negative_to_zero_and_emits_no_examples_text,
    ]
    for test in tests:
        test()
    print("OK")


if __name__ == "__main__":
    main()
