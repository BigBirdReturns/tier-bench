# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=tier_runner\events.py  mutation_score=5/6
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tier_runner"))

from pathlib import Path
import tempfile
import uuid as uuid_module

import events


def assert_raises(exc_type, message, call):
    try:
        call()
    except exc_type as e:
        assert str(e) == message
        return
    except Exception as e:  # pragma: no cover
        raise AssertionError(
            f"Expected {exc_type.__name__}, got {type(e).__name__}: {e}"
        )
    raise AssertionError(f"Expected {exc_type.__name__} with message {message!r}")


def test_event_hash_ignores_stored_hash_and_is_deterministic():
    row = {"b": 2, "event_sha256": "stored", "a": 1}
    assert events.event_hash(row) == (
        "e8d38819d39f705646bfb643368eca78f7db476c16471dbc33b941b27326410d"
    )
    assert events.event_hash(row) == events.event_hash(
        {"event_sha256": "other", "a": 1, "b": 2}
    )


def test_load_events_nonexistent_path_returns_empty_list():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        assert events.load_events(path) == []


def test_load_events_skips_blank_and_parses_objects():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        path.write_text(
            "\n".join(
                [
                    "",
                    "  ",
                    "{\"a\": 1}",
                    "",
                    "{\"b\": 2}",
                ]
            ),
            encoding="utf-8",
        )
        rows = events.load_events(path)
        assert rows == [{"a": 1}, {"b": 2}]


def test_load_events_invalid_json_line_fails_with_line_number():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        path.write_text('{"a": 1}\n{bad}', encoding="utf-8")

        def attempt():
            events.load_events(path)

        assert_raises(events.InterventionError, "invalid event JSON at line 2", attempt)


def test_load_events_non_object_line_fails_with_line_number():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        path.write_text("[1]\n", encoding="utf-8")

        def attempt():
            events.load_events(path)

        assert_raises(events.InterventionError, "event line 1 is not an object", attempt)


def _event_row(
    event: str,
    intervention_id: str,
    task_id: str = "task-1",
    arm: str = "arm_a",
    category: str = "brief",
    reference_id=None,
    ts: str = "2026-07-17T00:00:00Z",
    previous_event_sha256=None,
) -> dict:
    row = {
        "arm": arm,
        "category": category,
        "event": event,
        "intervention_id": intervention_id,
        "previous_event_sha256": previous_event_sha256,
        "reference_id": reference_id,
        "task_id": task_id,
        "ts": ts,
    }
    row["event_sha256"] = events.event_hash(row)
    return row


def test_open_intervention_accepts_closed_and_open_chain():
    iid = str(uuid_module.uuid4())
    start = _event_row("start", iid)
    stop = _event_row("stop", iid, previous_event_sha256=start["event_sha256"])
    rows = [start, stop]
    assert events.open_intervention(rows) is None

    iid2 = str(uuid_module.uuid4())
    only_start = _event_row("start", iid2)
    assert events.open_intervention([only_start]) == only_start


def test_open_intervention_requires_exact_fields_set():
    row = _event_row("start", str(uuid_module.uuid4()))
    row["extra"] = "not allowed"

    def attempt():
        events.open_intervention([row])

    assert_raises(
        events.InterventionError,
        "intervention event fields do not match the frozen schema",
        attempt,
    )


def test_open_intervention_rejects_invalid_uuid_and_ids():
    row = _event_row("start", "not-a-uuid")
    assert_raises(
        events.InterventionError,
        "every intervention event needs a UUID intervention_id",
        lambda: events.open_intervention([row]),
    )


def test_open_intervention_rejects_bad_reference_id():
    row = _event_row("start", str(uuid_module.uuid4()), reference_id="has space")
    assert_raises(
        events.InterventionError,
        "intervention reference_id is unsafe",
        lambda: events.open_intervention([row]),
    )


def test_open_intervention_rejects_unordered_timestamps():
    iid = str(uuid_module.uuid4())
    first = _event_row("start", iid, ts="2026-07-17T01:00:00Z")
    second = _event_row(
        "stop",
        iid,
        ts="2026-07-17T00:59:00Z",
        previous_event_sha256=first["event_sha256"],
    )
    assert_raises(
        events.InterventionError,
        "intervention timestamps are out of order",
        lambda: events.open_intervention([first, second]),
    )


def test_open_intervention_rejects_invalid_hash_chain():
    iid = str(uuid_module.uuid4())
    first = _event_row("start", iid)
    second = _event_row("stop", iid, previous_event_sha256="incorrect")
    assert_raises(
        events.InterventionError,
        "intervention event hash chain is broken",
        lambda: events.open_intervention([first, second]),
    )


def test_open_intervention_rejects_invalid_event_hash():
    iid = str(uuid_module.uuid4())
    first = _event_row("start", iid)
    first["event_sha256"] = "bad"
    assert_raises(
        events.InterventionError,
        "intervention event hash is invalid",
        lambda: events.open_intervention([first]),
    )


def test_open_intervention_rejects_overlap_and_reuse_start():
    iid_one = str(uuid_module.uuid4())
    iid_two = str(uuid_module.uuid4())
    start_one = _event_row("start", iid_one)
    start_two = _event_row("start", iid_two, previous_event_sha256=start_one["event_sha256"])
    assert_raises(
        events.InterventionError,
        "overlapping or reused intervention start",
        lambda: events.open_intervention([start_one, start_two]),
    )


def test_open_intervention_rejects_unknown_event():
    row = _event_row("open", str(uuid_module.uuid4()))
    assert_raises(
        events.InterventionError,
        "unknown intervention event 'open'",
        lambda: events.open_intervention([row]),
    )


def test_open_intervention_rejects_stop_mismatched_context():
    iid_one = str(uuid_module.uuid4())
    start = _event_row("start", iid_one, category="brief", task_id="task-1")
    stop = _event_row(
        "stop",
        iid_one,
        category="brief",
        task_id="wrong-task",
        previous_event_sha256=start["event_sha256"],
    )
    assert_raises(
        events.InterventionError,
        "stop task/arm does not match start",
        lambda: events.open_intervention([start, stop]),
    )


def test_validate_events_handles_missing_file_and_closed_or_open_paths():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        rows = events.validate_events(path)
        assert rows == []

        iid = str(uuid_module.uuid4())
        events._append(path, _event_row("start", iid), [])
        assert_raises(
            events.InterventionError,
            f"unclosed intervention {iid}",
            lambda: events.validate_events(path),
        )
        assert events.validate_events(path, require_closed=False) == events.load_events(path)


def test_start_rejects_unknown_category():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        assert_raises(
            events.InterventionError,
            "category must be one of ['acceptance', 'brief', 'clarification', 'other', 'rescue', 'review']",
            lambda: events.start(path, task_id="task-1", arm="arm_a", category="bad"),
        )


def test_start_blocks_when_open_intervention_exists():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        iid = events.start(path, task_id="task-1", arm="arm_a", category="brief")

        def attempt():
            events.start(path, task_id="task-2", arm="arm_b", category="other")

        assert_raises(
            events.InterventionError,
            "another intervention is already open",
            attempt,
        )

        events.stop(path, iid)


def _run_start_stop(path: Path) -> tuple[str, list[dict]]:
    original_now = events._now
    original_uuid4 = events.uuid.uuid4
    original_now = events._now
    original_uuid4 = events.uuid.uuid4

    fixed_time = "2026-07-17T00:00:00Z"
    fixed_iid = uuid_module.UUID("11111111-1111-1111-1111-111111111111")

    try:
        events._now = lambda: fixed_time
        events.uuid.uuid4 = lambda: fixed_iid
        iid = events.start(path, task_id="task-1", arm="arm_a", category="brief")
        events.stop(path, iid)
        rows = events.load_events(path)
        return iid, rows
    finally:
        events._now = original_now
        events.uuid.uuid4 = original_uuid4


def test_start_and_stop_append_expected_rows_and_hash_chain():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        iid, rows = _run_start_stop(path)

        assert iid == "11111111-1111-1111-1111-111111111111"
        assert len(rows) == 2
        assert rows[0]["event"] == "start"
        assert rows[0]["task_id"] == "task-1"
        assert rows[0]["arm"] == "arm_a"
        assert rows[0]["category"] == "brief"
        assert rows[0]["previous_event_sha256"] is None
        assert rows[0]["ts"] == "2026-07-17T00:00:00Z"
        assert rows[0]["event_sha256"] == (
            "a9f2bbfe5774671ebae76c10cdec9abe0d4ea0e68df0866f699f8daaa600e190"
        )

        assert rows[1]["event"] == "stop"
        assert rows[1]["previous_event_sha256"] == rows[0]["event_sha256"]
        assert rows[1]["ts"] == "2026-07-17T00:00:00Z"
        assert rows[1]["event_sha256"] == (
            "58f697b301f05ab4d756aa610e53ffb6eb6e4a32c1ccb6f80a64760537931f8f"
        )


def test_stop_rejects_non_open_intervention_id():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.log"
        iid = events.start(path, task_id="task-1", arm="arm_a", category="brief")
        assert_raises(
            events.InterventionError,
            "intervention_id is not the globally open intervention",
            lambda: events.stop(path, "00000000-0000-0000-0000-000000000000"),
        )
        events.stop(path, iid)


def test_event_row_schema_constant_fields():
    rows = [
        _event_row("start", str(uuid_module.uuid4())),
    ]
    assert rows[0].keys() >= {
        "arm",
        "category",
        "event",
        "event_sha256",
        "intervention_id",
        "previous_event_sha256",
        "reference_id",
        "task_id",
        "ts",
    }


def main():
    test_event_hash_ignores_stored_hash_and_is_deterministic()
    test_load_events_nonexistent_path_returns_empty_list()
    test_load_events_skips_blank_and_parses_objects()
    test_load_events_invalid_json_line_fails_with_line_number()
    test_load_events_non_object_line_fails_with_line_number()
    test_open_intervention_accepts_closed_and_open_chain()
    test_open_intervention_requires_exact_fields_set()
    test_open_intervention_rejects_invalid_uuid_and_ids()
    test_open_intervention_rejects_bad_reference_id()
    test_open_intervention_rejects_unordered_timestamps()
    test_open_intervention_rejects_invalid_hash_chain()
    test_open_intervention_rejects_invalid_event_hash()
    test_open_intervention_rejects_overlap_and_reuse_start()
    test_open_intervention_rejects_unknown_event()
    test_open_intervention_rejects_stop_mismatched_context()
    test_validate_events_handles_missing_file_and_closed_or_open_paths()
    test_start_rejects_unknown_category()
    test_start_blocks_when_open_intervention_exists()
    test_start_and_stop_append_expected_rows_and_hash_chain()
    test_stop_rejects_non_open_intervention_id()
    test_event_row_schema_constant_fields()
    print("OK")


if __name__ == "__main__":
    main()
