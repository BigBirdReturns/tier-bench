# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=experiments\breadth\ledger.py  mutation_score=2/6
# Pins CURRENT behavior; review before trusting.
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "experiments/breadth"))
import json
import tempfile
from pathlib import Path

from ledger import Call, log_call, load, reconcile, totals


def test_log_call_routes_unknown_keys_and_explicit_extra():
    with tempfile.TemporaryDirectory() as td:
        ledger_path = Path(td) / "ledger.jsonl"
        row = log_call(
            ledger_path,
            ts="2026-01-01T00:00:00Z",
            account="acct-a",
            model="m1",
            tier="max",
            task_id="t1",
            phase="baseline",
            outcome="pass",
            effort="high",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.123,
            unknown="abc",
            another=7,
            extra={"note_override": "explicit", "another": "from_extra"},
        )
        assert isinstance(row, Call)
        assert row.ts == "2026-01-01T00:00:00Z"
        assert row.account == "acct-a"
        assert row.model == "m1"
        assert row.input_tokens == 10
        assert row.output_tokens == 5
        assert row.cost_usd == 0.123
        assert row.extra == {"unknown": "abc", "another": "from_extra", "note_override": "explicit"}

        raw_lines = ledger_path.read_text(encoding="utf-8").splitlines()
        assert len(raw_lines) == 1
        payload = json.loads(raw_lines[0])
        assert payload["account"] == "acct-a"
        assert payload["model"] == "m1"
        assert payload["input_tokens"] == 10
        assert payload["output_tokens"] == 5
        assert payload["cost_usd"] == 0.123
        assert payload["extra"] == {"another": "from_extra", "note_override": "explicit", "unknown": "abc"}


def test_load_empty_and_skips_blank_lines():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ledger.jsonl"
        path.write_text("\n{}\n\n{\"a\":1}\n", encoding="utf-8")
        rows = load(path)
        assert rows == [{}, {"a": 1}]


def test_load_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        missing = Path(td) / "missing.jsonl"
        assert load(missing) == []


def test_totals_rollup_and_ordering_and_missing_keys():
    rows = [
        {
            "account": "a2",
            "model": "b",
            "tier": "mid",
            "input_tokens": 5,
            "output_tokens": 1,
            "cache_read_tokens": 2,
            "cost_usd": 0.01,
            "latency_ms": 300,
        },
        {
            "account": "a1",
            "model": "a",
            "tier": "max",
            "input_tokens": 3,
            "output_tokens": 4,
            "cache_write_tokens": 1,
            "cost_usd": 0.02,
            "latency_ms": 100,
            "foo": "bar",
        },
        {
            "account": "a2",
            "model": "b",
            "tier": "mid",
            "input_tokens": 2,
            "output_tokens": 3,
            "cost_usd": 0.005,
        },
    ]
    result = totals(rows)
    assert result["overall"]["calls"] == 3
    assert result["overall"]["input_tokens"] == 10
    assert result["overall"]["output_tokens"] == 8
    assert result["overall"]["cache_read_tokens"] == 2
    assert result["overall"]["cache_write_tokens"] == 1
    assert abs(result["overall"]["cost_usd"] - 0.035) < 1e-12
    assert result["overall"]["latency_ms"] == 400.0

    by = result["by_account_model_tier"]
    assert list(by.keys()) == ["a1/a/max", "a2/b/mid"]
    assert by["a1/a/max"]["calls"] == 1
    assert by["a1/a/max"]["input_tokens"] == 3
    assert by["a2/b/mid"]["calls"] == 2
    assert by["a2/b/mid"]["output_tokens"] == 4
    assert by["a2/b/mid"]["cache_read_tokens"] == 2
    assert by["a2/b/mid"]["cache_write_tokens"] == 0


def test_totals_empty_input():
    result = totals([])
    assert result["overall"] == {
        "input_tokens": 0.0,
        "output_tokens": 0.0,
        "cache_read_tokens": 0.0,
        "cache_write_tokens": 0.0,
        "cost_usd": 0.0,
        "latency_ms": 0.0,
        "calls": 0,
    }
    assert result["by_account_model_tier"] == {}


def test_reconcile_account_filter_and_bounds():
    rows = [
        {"account": "acct-a", "cost_usd": 0.10},
        {"account": "acct-a", "cost_usd": 0.04},
        {"account": "acct-b", "cost_usd": 0.11},
    ]
    r_all = reconcile(rows, billed_usd=0.25, tol=0.2)
    assert r_all["account"] == "*"
    assert r_all["calls"] == 3
    assert r_all["ledger_usd"] == 0.25
    assert r_all["drift_frac"] == 0.0
    assert r_all["ok"] is True

    r_a = reconcile(rows, billed_usd=0.13, account="acct-a", tol=0.0)
    assert r_a["account"] == "acct-a"
    assert r_a["calls"] == 2
    assert r_a["ledger_usd"] == 0.14
    assert r_a["drift_usd"] == 0.01
    assert r_a["drift_frac"] == 0.0769
    assert r_a["ok"] is False
    assert r_a["verdict"] == "UNRECONCILED — 0.0100 USD unaccounted (7.7%); a call went unlogged"

    r_a_tight = reconcile(rows, billed_usd=0.14, account="acct-a", tol=0.0)
    assert r_a_tight["ok"] is True
    assert r_a_tight["drift_frac"] == 0.0


def test_reconcile_when_billed_zero_and_calls_missing():
    empty_rows = [{"account": "x", "cost_usd": 0.0}]
    zero_nonzero = reconcile(empty_rows, billed_usd=0.0)
    assert zero_nonzero["ledger_usd"] == 0.0
    assert zero_nonzero["drift_frac"] == 0.0
    assert zero_nonzero["ok"] is True

    charged_rows = [{"account": "x", "cost_usd": 0.01}]
    charged_vs_zero = reconcile(charged_rows, billed_usd=0.0)
    assert charged_vs_zero["drift_frac"] == 1.0
    assert charged_vs_zero["ok"] is False
    assert charged_vs_zero["drift_usd"] == 0.01


def test_log_call_raises_on_missing_required_keys():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ledger.jsonl"
        try:
            log_call(
                p,
                ts="2026-01-01T00:00:00Z",
                account="acct-a",
                model="m1",
                # missing tier
                task_id="t1",
                phase="baseline",
                outcome="pass",
            )
        except TypeError as exc:
            assert "missing 1 required" in str(exc)
        else:
            raise AssertionError("expected TypeError for missing required Call field")


def main():
    test_log_call_routes_unknown_keys_and_explicit_extra()
    test_load_empty_and_skips_blank_lines()
    test_load_missing_file_returns_empty()
    test_totals_rollup_and_ordering_and_missing_keys()
    test_totals_empty_input()
    test_reconcile_account_filter_and_bounds()
    test_reconcile_when_billed_zero_and_calls_missing()
    test_log_call_raises_on_missing_required_keys()
    print("OK")


if __name__ == "__main__":
    main()
