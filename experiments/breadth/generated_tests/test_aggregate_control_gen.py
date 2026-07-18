# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=scripts\aggregate_control.py  mutation_score=2/6
# Pins CURRENT behavior; review before trusting.
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from aggregate_control import _lineage, aggregate, load, main as aggregate_main


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row))
            f.write("\n")


def test_lineage_mapping_is_lexically_matched():
    assert _lineage("claude-3-opus") == "anthropic"
    assert _lineage("gpt-4") == "openai"
    assert _lineage("Gemini-1.5") == "google"
    assert _lineage("qwen-2") == "qwen"
    assert _lineage("ultrone") == "other"


def test_load_empty_directory_returns_no_runs():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert load(tmpdir) == []


def test_load_raises_on_missing_meta_row():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir, "x.jsonl")
        _write_jsonl(p, [{"probe_id": "p", "score": 1, "grader": "a"}])
        try:
            load(tmpdir)
            assert False, "expected assertion for missing _meta row"
        except AssertionError as e:
            assert "_meta" in str(e)


def test_load_reads_sorted_files_and_defaults_administration_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        _write_jsonl(
            data_dir / "z.jsonl",
            [
                {"_meta": True, "model": "claude", "effort": "base", "contributor": "b"},
                {"probe_id": "p2", "score": 1, "grader": "c"},
            ],
        )
        _write_jsonl(
            data_dir / "a.jsonl",
            [
                {"_meta": True, "model": "gpt", "effort": "base", "contributor": "a"},
                {"probe_id": "p1", "score": 0, "grader": "d"},
                {"probe_id": "p3", "score": 2, "grader": "e"},
                {},
            ],
        )

        runs = load(tmpdir)

        assert len(runs) == 2
        (meta_a, probes_a), (meta_z, probes_z) = runs
        assert meta_a["administration_id"] == "a"
        assert meta_z["administration_id"] == "z"
        assert meta_a["model"] == "gpt"
        assert meta_z["model"] == "claude"
        assert len(probes_a) == 3
        assert len(probes_z) == 1


def test_aggregate_empty_data_dir_is_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert aggregate(tmpdir) == {}


def test_aggregate_single_source_and_contamination_filtering():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_jsonl(
            Path(tmpdir) / "run.jsonl",
            [
                {"_meta": True, "model": "claude-3-5", "effort": "default", "contributor": "reviewer-1"},
                {"probe_id": "p1", "score": 2, "grader": "gpt-4", "contaminated": False},
                {"probe_id": "p2", "score": 0, "grader": "gpt-4", "contaminated": True},
            ],
        )

        out = aggregate(tmpdir)
        assert out["claude-3-5|default|p1"]["scores"] == [2]
        assert out["claude-3-5|default|p1"]["mean"] == 2
        assert out["claude-3-5|default|p1"]["evidence_class"] == "single-source"
        assert out["claude-3-5|default|p1"]["n_runs"] == 1
        assert out["claude-3-5|default|p1"]["n_judgments"] == 1
        assert out["claude-3-5|default|p1"]["n_graded"] == 1
        assert out["claude-3-5|default|p1"]["n_independent_graded"] == 1

        assert out["claude-3-5|default|p2"]["n_graded"] == 0
        assert out["claude-3-5|default|p2"]["n_judgments"] == 0
        assert out["claude-3-5|default|p2"]["evidence_class"] == "UNGRADED"
        assert out["claude-3-5|default|p2"]["scores"] == []
        assert out["claude-3-5|default|p2"]["mean"] is None


def test_aggregate_corroborated_label_with_multiple_contributors():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_jsonl(
            Path(tmpdir) / "a.jsonl",
            [
                {"_meta": True, "model": "gpt-4", "effort": "high", "contributor": "alice"},
                {"probe_id": "probe", "score": 2, "grader": "claude-3"},
            ],
        )
        _write_jsonl(
            Path(tmpdir) / "b.jsonl",
            [
                {"_meta": True, "model": "gpt-4", "effort": "high", "contributor": "bob"},
                {"probe_id": "probe", "score": 0, "grader": "claude-3"},
            ],
        )

        out = aggregate(tmpdir)
        cell = out["gpt-4|high|probe"]
        assert cell["scores"] == [2, 0]
        assert cell["mean"] == 1.0
        assert cell["evidence_class"] == "corroborated"
        assert cell["n_runs"] == 2
        assert cell["n_judgments"] == 2
        assert cell["n_graded"] == 2
        assert cell["n_independent_graded"] == 2
        assert cell["grader_lineage_flag"] is False


def test_aggregate_lineage_conflict_only_and_external_grades():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_jsonl(
            Path(tmpdir) / "single.jsonl",
            [
                {"_meta": True, "model": "gpt-4", "effort": "baseline", "contributor": "alice"},
                {
                    "probe_id": "p",
                    "score": 2,
                    "grader": "gpt-4.5",
                    "external_grades": [
                        {"grader": "gpt-4.1", "score": 1},
                        {"grader": "alice", "score": 0},
                        {"score": 0},
                    ],
                },
            ],
        )

        out = aggregate(tmpdir)
        cell = out["gpt-4|baseline|p"]
        assert cell["scores"] == [2, 1]
        assert cell["evidence_class"] == "single-source · grader shares subject lineage"
        assert cell["grader_lineage_flag"] is True
        assert cell["n_graded"] == 2
        assert cell["n_independent_graded"] == 0


def test_main_json_flag_prints_json_for_aggregate_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        data_dir.mkdir()
        _write_jsonl(
            data_dir / "run.jsonl",
            [
                {"_meta": True, "model": "qwen-2", "effort": "full", "contributor": "z"},
                {"probe_id": "p", "score": 1, "grader": "claude-3"},
            ],
        )

        argv = sys.argv
        sys.argv = ["aggregate_control.py", "--data", str(data_dir), "--json"]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                aggregate_main()
            parsed = json.loads(buf.getvalue())
        finally:
            sys.argv = argv

        assert parsed == {"qwen-2|full|p": {"model": "qwen-2", "effort": "full", "probe": "p", "n_runs": 1, "n_judgments": 1, "n_graded": 1, "n_independent_graded": 1, "administration_ids": ["run"], "scores": [1], "mean": 1.0, "evidence_class": "single-source", "grader_lineage_flag": False, "note": "all self-reported; corroborated=>=2 distinct non-subject contributors; lineage flag set when no grader is independent of the subject's lineage"}}


def main():
    test_lineage_mapping_is_lexically_matched()
    test_load_empty_directory_returns_no_runs()
    test_load_raises_on_missing_meta_row()
    test_load_reads_sorted_files_and_defaults_administration_id()
    test_aggregate_empty_data_dir_is_empty()
    test_aggregate_single_source_and_contamination_filtering()
    test_aggregate_corroborated_label_with_multiple_contributors()
    test_aggregate_lineage_conflict_only_and_external_grades()
    test_main_json_flag_prints_json_for_aggregate_output()
    print("OK")


if __name__ == "__main__":
    main()
