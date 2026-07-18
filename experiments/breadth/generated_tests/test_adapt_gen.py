# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# Gate: passes real adapt.py AND kills >=1 source mutation. Mutation score: 1/6
# Pins CURRENT behavior, not intended spec. Review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
#!/usr/bin/env python3
"""Characterization tests for adapt.py."""


import json
import tempfile
from pathlib import Path

from adapt import classify, load, pending_proposals, record


def test_classify_free():
    assert classify("solve_strategy") == "free"
    assert classify("prompt") == "free"
    assert classify("lens_selection") == "free"
    assert classify("trial_policy") == "free"
    assert classify("ordering") == "free"
    assert classify("effort_ladder") == "free"


def test_classify_gated_for_unknown_target():
    assert classify("grader") == "gated"
    assert classify("disable_task") == "gated"
    assert classify("something_unknown") == "gated"
    assert classify("") == "gated"


def test_record_appends_sorted_json_lines_and_returns_row():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "nested" / "log.jsonl"
        row = record(
            log,
            kind="adjustment",
            target="effort_ladder",
            change="added xhigh step",
            rationale="calibrate",
            applied=True,
        )

        assert log.exists()
        contents = log.read_text(encoding="utf-8").splitlines()
        assert len(contents) == 1

        parsed = json.loads(contents[0])
        assert parsed == row
        assert row["ts"] == "1970-01-01T00:00:00Z"
        assert row["kind"] == "adjustment"
        assert row["target"] == "effort_ladder"
        assert row["class"] == "free"
        assert row["change"] == "added xhigh step"
        assert row["rationale"] == "calibrate"
        assert row["applied"] is True
        assert row["needs_human_review"] is False
        assert contents[0] == json.dumps(row, sort_keys=True)


def test_record_forces_gated_applied_false_and_needs_review():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "proposal.log"
        row = record(
            log,
            kind="proposal",
            target="grader",
            change="alter pass criteria",
            rationale="attempted self-serve",
            applied=True,
        )

        assert row["class"] == "gated"
        assert row["applied"] is False
        assert row["needs_human_review"] is True
        assert row["ts"] == "1970-01-01T00:00:00Z"


def test_record_uses_provided_timestamp_and_path_string():
    with tempfile.TemporaryDirectory() as tmp:
        log = str(Path(tmp) / "with_ts.jsonl")
        row = record(
            log,
            kind="adjustment",
            target="prompt",
            change="rewrite",
            rationale="more concise",
            applied=False,
            ts="2020-01-01T00:00:00Z",
        )

        assert row["ts"] == "2020-01-01T00:00:00Z"
        lines = Path(log).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1


def test_load_returns_empty_when_missing():
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "no_file.jsonl"
        assert load(missing) == []


def test_load_ignores_blank_lines_and_parses_multiple_rows():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "log.jsonl"
        log.write_text(
            '\n{"a": 1}\n\n{"b": 2}\n',
            encoding="utf-8",
        )

        assert load(log) == [{"a": 1}, {"b": 2}]


def test_pending_proposals_filters_gated_rows_only():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "mixed.jsonl"
        record(
            log,
            kind="adjustment",
            target="prompt",
            change="tune",
            rationale="safe",
            applied=True,
        )
        record(
            log,
            kind="proposal",
            target="grader",
            change="touch grading",
            rationale="unsafe",
            applied=True,
        )
        record(
            log,
            kind="adjustment",
            target="ordering",
            change="swap",
            rationale="reorder",
            applied=True,
        )

        proposals = pending_proposals(log)

        assert len(proposals) == 1
        assert proposals[0]["target"] == "grader"
        assert proposals[0]["class"] == "gated"
        assert proposals[0]["applied"] is False
        assert proposals[0]["needs_human_review"] is True


def test_pending_proposals_empty_when_none_gated():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "free_only.jsonl"
        record(
            log,
            kind="adjustment",
            target="ordering",
            change="swap",
            rationale="reorder",
            applied=True,
        )
        assert pending_proposals(log) == []


def main() -> None:
    test_classify_free()
    test_classify_gated_for_unknown_target()
    test_record_appends_sorted_json_lines_and_returns_row()
    test_record_forces_gated_applied_false_and_needs_review()
    test_record_uses_provided_timestamp_and_path_string()
    test_load_returns_empty_when_missing()
    test_load_ignores_blank_lines_and_parses_multiple_rows()
    test_pending_proposals_filters_gated_rows_only()
    test_pending_proposals_empty_when_none_gated()
    print("OK")


if __name__ == "__main__":
    main()
