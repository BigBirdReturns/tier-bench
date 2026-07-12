# Correction — f2 candidate was a coordinator transcription, not raw bytes

**Found 2026-07-12**, during mechanical re-extraction for the ARC-C sealed run.

`almanac_rule_boundary_001/f2/candidate.py` in this directory was transcribed
by hand from the solver's final message, and the coordinator condensed the
model's long inline comment block while doing so. The file graded here
(sha256 `a20c8752…`) is therefore **not byte-identical to the raw solver
response** (sha256 `6fc38a70…`, mechanically extracted from the preserved
subagent transcript). f1 and f3 were verified byte-faithful.

What this does and does not affect:

- The grade recorded here was internally consistent (the sealed file is the
  file that was graded, twice, deterministically) and the differences are
  comments only — but raw-response custody was broken, which is exactly the
  defect class the cross-engine protocol exists to catch.
- The capability conclusion (fable-low clears `rule_boundary` 3/3) is
  **re-established on clean provenance** in the sealed ARC-C run: the TRUE
  raw bytes (`6fc38a70…`) were mechanically extracted, sealed, regraded from
  the source-pinned packet at `3d38371`, and **pass** — see
  `data/orchestration/runs/arc_c_almanac_claude_v1/almanac_rule_boundary_001/trial-2/`,
  which includes the full raw event stream.
- Rule going forward (already applied in the ARC-C run): candidates are
  extracted mechanically from the preserved transcript, never transcribed.

This mirrors the Codex-side source-custody correction of the same date: the
error is preserved, named, and superseded — not overwritten.
