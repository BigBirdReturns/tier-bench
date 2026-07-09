# Promotion record — authoring batch 1 (closure packet per docs/burden-discipline.md)

- **requested_outcome:** promote 3 authored novel-reasoning tasks into the measured
  breadth set (`experiments/tier-uplift/`).
- **claimant:** the Fable authoring session (commit `3b25139`, branch `claude/setup-5akhb4`),
  which correctly logged them as GATED `task_definition` proposals (`applied=False`).
- **authority:** the operator, explicitly ("the word"), in the driving session.
- **predicates:** acceptance (a)–(e) per `AUTHORING_BRIEF.md`; spec does not leak the
  derivation; design claims true; graders re-verified at the promoted location.
- **burden_holder:** the reviewing driver (this session) — independent of the author.
- **evidence:** acceptance re-run 15/15 PASS in a clean worktree; slot-01 trap-trap
  reproduced by direct execution (textbook input handled correctly, claimed break
  returns None vs truth 12); specs read for leakage; destination re-check
  naive-fails/reference-passes ×3; `breadth_tasks.py` lists 8 valid tasks.
- **verifier:** deterministic graders + `acceptance.py`, re-run by the reviewer (not
  the author's self-report).
- **gap:** none for validity. Capability is UNMEASURED — no model results exist for
  task08/09/10 yet; whether they wall the cheap floor is exactly the next run's question.
- **closure_decision:** accepted — promoted as
  `task08_select_exchange` (was t_novel_01), `task09_pattern_class` (was t_novel_02),
  `task10_topo_endmin` (was t_novel_03). `NAIVE.py`/`REFERENCE.py` are retained as key
  material only and must NEVER appear in a solver packet (same convention as task06's
  answer key; the solver sees spec.md + subject.py only).
- **failure_default:** had any predicate failed, the slot stayed a proposal in
  `authoring/` — not promoted, not measured.

## Next run (for the session that types `go`)

Cheap-floor **K=3** over `task08_select_exchange`, `task09_pattern_class`,
`task10_topo_endmin` per `RUNBOOK.md`/`LESSONS.md`: solver sees ONLY spec.md (+
subject.py where present) — never the grader, never NAIVE/REFERENCE; grade with the
hidden grader and **re-run the grader yourself** on every candidate; log every attempt
to `run/ledger.jsonl`; a cell is settled only at 3/3; report settled/unstable/wall and
append the sediment layer. If a task walls the floor, that is the program's residual —
escalate one rung at a time with K/K receipts, per the ladder.
