# SOL-2 P2 remediation proposal

Date: 2026-07-10

Branch: `codex/sol2-p2-durability-proposals`

Disposition: proposal only; every changed measurement surface remains
`applied=false` in `experiments/breadth/run/harness_log.jsonl` until human review.

## Scope and invariants

This proposal repairs the four P2 durability findings from the SOL-2 ARC-A/ARC-B
review. It does not change a task's success predicate, hidden vectors, expected
answers, K, escalation policy, or any sealed result.

1. **Replay evidence schema — already remediated on main.** The merged CLAUDE-4
   hardening replaced the contradictory string schema with structured,
   hash-bound replay events and added schema/validator regression coverage. This
   proposal deliberately does not duplicate or weaken that repair.
2. **Hidden-grader admission — proposed here.** `is_gameable()` now requires the
   declared files to be regular files inside the fixture, outside the target and
   editable set, and referenced by the deciding command. A manifest whose hidden
   command runs `input.py` remains gameable even if it truthily declares
   `hidden_tests.py`.
3. **Almanac task identity — proposed here.** The contribution gate accepts only
   the three already-receipted `almanac_*` IDs as legacy-stable exceptions. New
   tasks still require the tier prefix. This avoids invalidating sealed receipts
   and does not create a general opt-out.
4. **Repeatable, bounded grading — proposed here.** Fixture copies ignore Python
   bytecode residue, hidden graders run with bytecode writes disabled, and all
   harness/self-run hidden-grader paths share a 60-second deadline. Timeout is a
   recorded failed hidden result rather than an unbounded harness hang.

## Verification

- `tests/test_almanac_vectors.py`: 12/12 passed, including adversarial false
  declarations, legacy-ID gate coverage, bytecode filtering, and timeout behavior.
- `scripts/validate_task.py tasks`: 17 tasks checked, 0 problems.
- Python compilation passed for every touched Python module.
- `tests/test_capture_roi.py`: 8/8 passed.
- `tests/test_capture_ledger.py`: 32/33 passed in the Windows checkout. The sole
  failure is the pre-existing CRLF receipt-hash mismatch that PR #63 addresses;
  this proposal does not touch those artifacts or normalization policy.

## Burden packet

- requested outcome: human application of the three remaining P2 durability
  repairs after review
- claimant: SOL-2 Codex driver
- authority: executable counterexamples in the SOL-2 review and the regression
  tests named above
- burden holder: human reviewer applying gated measurement changes
- verifier: rerun the commands above in a fresh clone, then confirm the three
  appended harness-log rows remain `applied=false` before merge approval
- gap: proposal has not been human-applied; the Windows receipt hash failure is
  intentionally left to PR #63
- closure_decision: open pending human review
- failure_default: retain current gates and do not claim the defects remediated
