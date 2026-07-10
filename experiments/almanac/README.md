# experiments/almanac — the hidden-knot corpus (ARC-B)

Deterministic calendrical/numerological engines as graded task families. The
design (`DESIGN.md`) and the corroborated reference implementation
(`reference/engine.py`, checked 34/35 against operator-held hand-computed
charts — held locally, never committed) predate this corpus; ARC-B turns the
designed boundary vectors into three breadth-valid graded tasks:

```
tasks/almanac_rule_boundary_001.json    lichun/jieqi solar boundaries   (T3)
tasks/almanac_record_binding_001.json   civil-record binding, day/hour  (T3)
tasks/almanac_exception_class_001.json  master-number exception class   (T2)
```

- **Hidden grading**: each fixture ships a `hidden_tests.py` the harness
  strips from the solver's working copy and prompt (`hidden_files` mechanism);
  `breadth_tasks.py` lists all three as capability-valid.
- **Vector provenance**: `generate_vectors.py` derives every expected value
  from the reference engine; `--check` (CI) fails the build if the frozen
  fixtures drift. Coverage map: `VECTORS.md`.
- **Key material**: `key/<task>/{REFERENCE,NAIVE}.py` — a correct
  implementation and the plausible wrong school per task, verified
  (reference passes each grader, naive fails on the knot vectors). Never part
  of a solver packet.
- **PII rule**: every committed date is synthetic, constructed to exercise a
  boundary. Real birth data stays out of the repo, unconditionally.
- **Authoring bar**: per LESSONS rule 11 — the specs are complete black-letter
  rule text (the almanac doctrine: declared convention, cite the math); no
  spec sentence flags or defuses a knot, and the visible `main()` checks
  exercise only ordinary mid-band cases. The knots live in boundary
  APPLICATION, decided by hidden vectors.
- **No results claimed**: no model has been graded on these tasks. That
  measurement is future work with its own sealed layer.
