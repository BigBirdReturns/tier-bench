# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=scripts\validate_lens.py  mutation_score=2/5
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
#!/usr/bin/env python3

import io
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import types

def _ensure_capability_harness_stub():
    if "capability_harness" in sys.modules and "capability_harness.uplift" in sys.modules and "capability_harness.backends" in sys.modules:
        return

    package = types.ModuleType("capability_harness")
    package.__path__ = []  # Mark as package for nested imports.
    sys.modules.setdefault("capability_harness", package)

    uplift = types.ModuleType("capability_harness.uplift")

    class Lens:
        def __init__(self, lens_key, instruction):
            self.lens_key = lens_key
            self.instruction = instruction

    uplift.Lens = Lens
    uplift._PROMPT = """You are doing a careful code review through a SINGLE focused lens.

Given this lens: {instruction}

----- TARGET -----
{target}
----- END TARGET -----"""

    sys.modules.setdefault("capability_harness.uplift", uplift)

    backends = types.ModuleType("capability_harness.backends")

    def _identity_backend(prompt):
        return prompt

    def echo_backend():
        return _identity_backend

    def anthropic_backend(model):
        return lambda prompt: f"{model}: {prompt}"

    def openai_backend(model, base_url=None):
        return lambda prompt: f"{model}:{base_url}:{prompt}"

    backends.echo_backend = echo_backend
    backends.anthropic_backend = anthropic_backend
    backends.openai_backend = openai_backend

    sys.modules.setdefault("capability_harness.backends", backends)


_ensure_capability_harness_stub()

import validate_lens
from validate_lens import main as validate_lens_main


def _with_subject(content: str) -> Path:
    fp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".py")
    fp.write(content)
    fp.flush()
    fp.close()
    return Path(fp.name)


def _run(argv):
    original_argv = sys.argv[:]
    sys.argv = argv
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            returncode = validate_lens_main()
            raised = None
    except SystemExit as exc:
        raised = exc
        returncode = exc.code
    finally:
        sys.argv = original_argv

    return returncode, stdout.getvalue(), stderr.getvalue(), raised


def test_main_echo_backend_returns_ok_for_nonempty_subject():
    path = _with_subject("hello\n")
    rc, out, err, raised = _run(
        [
            "validate_lens.py",
            "--lens-key",
            "smoke",
            "--lens",
            "Lens text",
            "--subject",
            str(path),
            "--backend",
            "echo",
        ]
    )

    assert raised is None
    assert rc == 0
    assert err == ""
    assert f"[validate_lens] backend=echo model=claude-haiku-4-5 subject={path}" in out
    assert "[validate_lens] echo smoke: OK" in out


def test_main_echo_backend_with_empty_subject_is_still_ok():
    path = _with_subject("")
    rc, out, err, raised = _run(
        [
            "validate_lens.py",
            "--lens-key",
            "smoke-empty",
            "--lens",
            "Lens text",
            "--subject",
            str(path),
            "--backend",
            "echo",
        ]
    )

    assert raised is None
    assert rc == 0
    assert "[validate_lens] echo smoke: OK" in out
    assert "[validate_lens] baseline pass" in out
    assert err == ""


def test_main_non_echo_with_empty_expect_passes():
    path = _with_subject("a\nb\nc\n")
    original_get_backend = validate_lens._get_backend

    def fake_backend(prompt):
        fake_backend.calls += 1
        if fake_backend.calls == 1:
            return "baseline finding"
        return "lensed finding"

    fake_backend.calls = 0

    try:
        validate_lens._get_backend = lambda name, model, base_url: fake_backend
        rc, out, err, raised = _run(
            [
                "validate_lens.py",
                "--lens-key",
                "boundary",
                "--lens",
                "Inspect for hidden bug",
                "--subject",
                str(path),
                "--backend",
                "openai",
            ]
        )
    finally:
        validate_lens._get_backend = original_get_backend

    assert raised is None
    assert rc == 0
    assert "[validate_lens] PASS — lens surfaced a distinct finding that the baseline pass missed on held-out code." in out
    assert err == ""
    assert fake_backend.calls == 2


def test_main_non_echo_missing_expected_output_is_failure():
    path = _with_subject("x\ny\n")
    original_get_backend = validate_lens._get_backend

    def fake_backend(prompt):
        fake_backend.calls += 1
        if fake_backend.calls == 1:
            return "found issue: alpha"
        return "found issue: beta"

    fake_backend.calls = 0

    try:
        validate_lens._get_backend = lambda name, model, base_url: fake_backend
        rc, out, err, raised = _run(
            [
                "validate_lens.py",
                "--lens-key",
                "missing-evidence",
                "--lens",
                "Look for gamma",
                "--subject",
                str(path),
                "--backend",
                "openai",
                "--expect",
                "delta",
            ]
        )
    finally:
        validate_lens._get_backend = original_get_backend

    assert raised is None
    assert rc == 1
    assert "[validate_lens] FAIL — lens output missing required evidence: ['delta']" in out
    assert err == ""


def test_main_non_echo_passes_when_expectation_added():
    path = _with_subject("x\n")
    original_get_backend = validate_lens._get_backend

    def fake_backend(prompt):
        fake_backend.calls += 1
        if fake_backend.calls == 1:
            return "found issue: alpha"
        return "found issue: alpha and delta"

    fake_backend.calls = 0

    try:
        validate_lens._get_backend = lambda name, model, base_url: fake_backend
        rc, out, err, raised = _run(
            [
                "validate_lens.py",
                "--lens-key",
                "added",
                "--lens",
                "Find unexpected state changes",
                "--subject",
                str(path),
                "--backend",
                "openai",
                "--expect",
                "delta",
            ]
        )
    finally:
        validate_lens._get_backend = original_get_backend

    assert raised is None
    assert rc == 0
    assert "[validate_lens] PASS — lens surfaced ['delta'] that the baseline pass missed on held-out code." in out
    assert err == ""
    assert "[validate_lens] baseline pass" in out


def test_main_non_echo_fails_when_baseline_already_caught_expected():
    path = _with_subject("return x")
    original_get_backend = validate_lens._get_backend

    def fake_backend(prompt):
        fake_backend.calls += 1
        return "shared issue: alpha"

    fake_backend.calls = 0

    try:
        validate_lens._get_backend = lambda name, model, base_url: fake_backend
        rc, out, err, raised = _run(
            [
                "validate_lens.py",
                "--lens-key",
                "duplicate",
                "--lens",
                "Duplicate issue",
                "--subject",
                str(path),
                "--backend",
                "openai",
                "--expect",
                "alpha",
            ]
        )
    finally:
        validate_lens._get_backend = original_get_backend

    assert raised is None
    assert rc == 1
    assert "[validate_lens] FAIL — baseline already surfaced every expected item; the lens added no lift on this subject." in out
    assert fake_backend.calls == 2


def test_main_missing_required_args_fails_with_parser_error():
    rc, out, err, raised = _run(["validate_lens.py"])
    assert isinstance(raised, SystemExit)
    assert rc == 2
    assert out == ""
    assert "usage: validate_lens.py" in err


def main() -> None:
    tests = [
        test_main_echo_backend_returns_ok_for_nonempty_subject,
        test_main_echo_backend_with_empty_subject_is_still_ok,
        test_main_non_echo_with_empty_expect_passes,
        test_main_non_echo_missing_expected_output_is_failure,
        test_main_non_echo_passes_when_expectation_added,
        test_main_non_echo_fails_when_baseline_already_caught_expected,
        test_main_missing_required_args_fails_with_parser_error,
    ]

    for test in tests:
        test()

    print("OK")


if __name__ == "__main__":
    main()
