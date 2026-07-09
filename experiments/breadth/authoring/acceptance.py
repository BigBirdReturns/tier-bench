#!/usr/bin/env python3
"""Mechanical acceptance check for a novel-reasoning authoring slot.

Given a slot directory (a `t_novel_0N/` under `experiments/breadth/authoring/`), a
candidate module that is expected to FAIL the hidden grader, and a reference
module that is expected to PASS it, this runs the five criteria from
`AUTHORING_BRIEF.md` and prints PASS/FAIL for each:

  (a) grader is deterministic         — same input, same verdict, twice
  (b) naive/unsolved candidate FAILS  — the plausible-looking implementation is wrong
  (c) reference solution PASSES       — a correct implementation is provably reachable
  (d) breadth_tasks.py would list it  — hidden-grader filename is a recognized name
  (e) solver prompt never contains the hidden grader — spec.md doesn't leak it

This script is deterministic Python; it never calls a model, and it never edits
a grader — writing/adjusting the grader itself is the driver's (Fable's) job per
adapt.py's FREE/GATED gate. Running this script is a FREE action (verification of
existing content), not a change to what counts as passing.

    python acceptance.py --slot t_novel_01 --candidate NAIVE.py --reference REFERENCE.py
    python acceptance.py --slot t_novel_01 --candidate REFERENCE.py --reference REFERENCE.py --skip-b

Exit code is 0 iff every requested criterion PASSes, 1 otherwise — so this can
gate a commit script or CI step without parsing output.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "experiments" / "breadth"))

try:
    from breadth_tasks import HIDDEN_GRADER_NAMES  # type: ignore
except ImportError:
    # Fallback if run standalone without the package on path — keep in sync with
    # experiments/breadth/breadth_tasks.py:HIDDEN_GRADER_NAMES by hand if this fires.
    HIDDEN_GRADER_NAMES = ("hidden_tests.py", "hidden_oracle.py", "grader.py")


def find_hidden_grader(slot: Path) -> Path | None:
    for name in HIDDEN_GRADER_NAMES:
        p = slot / name
        if p.exists():
            return p
    return None


def run_grader(grader: Path, candidate: Path) -> tuple[int, str, str]:
    """Invoke the grader contract: `python <grader> <candidate>`. Returns
    (exit_code, stdout, stderr). A grader that itself errors out (traceback,
    missing file) is reported as its real exit code — never silently coerced to
    a pass or a fail; the caller decides what that means for the criterion."""
    r = subprocess.run(
        [sys.executable, str(grader), str(candidate)],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


def check_a_deterministic(grader: Path, candidate: Path) -> tuple[bool, str]:
    rc1, out1, _ = run_grader(grader, candidate)
    rc2, out2, _ = run_grader(grader, candidate)
    ok = (rc1 == rc2) and (out1 == out2)
    detail = f"run1=(exit {rc1}) run2=(exit {rc2})" + ("" if ok else " — MISMATCH, not deterministic")
    return ok, detail


def check_b_naive_fails(grader: Path, naive: Path) -> tuple[bool, str]:
    rc, out, err = run_grader(grader, naive)
    ok = rc != 0
    return ok, f"naive candidate exit={rc} (want !=0){'' if ok else ' — naive candidate PASSED, task has no bite'}"


def check_c_reference_passes(grader: Path, reference: Path) -> tuple[bool, str]:
    rc, out, err = run_grader(grader, reference)
    ok = rc == 0
    return ok, f"reference candidate exit={rc} (want 0){'' if ok else ' — reference FAILED its own grader, bar unreachable'}"


def check_d_breadth_valid(grader: Path) -> tuple[bool, str]:
    ok = grader.name in HIDDEN_GRADER_NAMES
    return ok, f"hidden grader filename '{grader.name}' {'is' if ok else 'is NOT'} a name breadth_tasks.py recognizes"


def check_e_no_leak(slot: Path, grader: Path) -> tuple[bool, str]:
    """Solver-facing files (spec.md and any non-grader, non-reference file meant
    for the solver) must not name or embed the hidden grader."""
    leaks = []
    grader_text = grader.read_text(encoding="utf-8", errors="ignore")
    for f in sorted(slot.iterdir()):
        if f.name == grader.name or not f.is_file():
            continue
        if f.suffix not in (".md", ".py", ".txt"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        if grader.name in text and "TODO" not in text:
            # filename mentions are fine in placeholders/briefs ("do not rename"),
            # so only flag once the file is no longer a TODO placeholder.
            leaks.append(f.name)
        # A crude but real content leak: a solver-facing file containing a
        # substantial verbatim slice of the grader's own source.
        grader_body = "\n".join(l for l in grader_text.splitlines() if l.strip() and not l.strip().startswith(("#", '"""')))
        if grader_body and len(grader_body) > 40 and grader_body in text:
            leaks.append(f.name)
    ok = not leaks
    return ok, ("no leak detected" if ok else f"possible leak in: {', '.join(sorted(set(leaks)))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", required=True, help="slot directory, e.g. t_novel_01 or its full path")
    ap.add_argument("--candidate", default="NAIVE.py", help="naive/unsolved candidate filename within the slot")
    ap.add_argument("--reference", default="REFERENCE.py", help="reference (correct) candidate filename within the slot")
    ap.add_argument("--skip-b", action="store_true", help="skip criterion (b), e.g. when re-checking only the reference")
    args = ap.parse_args()

    slot = Path(args.slot)
    if not slot.is_absolute():
        here = Path(__file__).resolve().parent
        slot = (here / slot) if (here / slot).exists() else (REPO / slot)
    if not slot.is_dir():
        print(f"FAIL: slot not found: {args.slot}")
        return 1

    grader = find_hidden_grader(slot)
    if grader is None:
        print(f"FAIL (d): no recognized hidden grader ({', '.join(HIDDEN_GRADER_NAMES)}) found in {slot}")
        return 1

    candidate = slot / args.candidate
    reference = slot / args.reference
    missing = [str(p) for p in (candidate, reference) if not p.exists()]
    if missing:
        print(f"FAIL: missing file(s): {', '.join(missing)}")
        return 1

    results: list[tuple[str, bool, str]] = []
    ok, detail = check_a_deterministic(grader, reference)
    results.append(("(a) grader deterministic", ok, detail))

    if not args.skip_b:
        ok, detail = check_b_naive_fails(grader, candidate)
        results.append(("(b) naive candidate FAILS", ok, detail))

    ok, detail = check_c_reference_passes(grader, reference)
    results.append(("(c) reference candidate PASSES", ok, detail))

    ok, detail = check_d_breadth_valid(grader)
    results.append(("(d) breadth_tasks.py would list it", ok, detail))

    ok, detail = check_e_no_leak(slot, grader)
    results.append(("(e) solver prompt never contains grader", ok, detail))

    print(f"acceptance check — slot: {slot.name}  grader: {grader.name}")
    all_ok = True
    for label, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label} — {detail}")
        all_ok = all_ok and ok

    print(f"\n{'PASS' if all_ok else 'FAIL'} overall")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
