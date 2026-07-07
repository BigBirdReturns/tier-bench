# Control-Set Results — schema & recording protocol

The disposition probes in `driver/control-set.md` are **human-graded**, so they
cannot flow through the auto-validated harness in `data/results/`. They record
here instead, under the same provenance doctrine: every row is self-reported,
a `(model, tier, effort)` cell is `single-source` until >=2 distinct
contributors corroborate it, and the label always travels with the number.

## One file per run

Filename: `data/control-results/{model}__{effort}__{contributor}__{yyyymmdd}.jsonl`
(e.g. `fable-5__high__bigbird__20260707.jsonl`). One run = one cold
administration of all ten probes to one model at one effort setting.

## Row shape (one row per probe, 10 rows + 1 `_meta` row)

```json
{
  "probe_id": "P8",
  "probe_shape": "encoding op silently defeats a path constraint while looking successful",
  "prompt_surface": "window.open PR-prefill review, %2F variant",
  "response": "<verbatim model output, unedited>",
  "score": 1,
  "score_key": "2=pass behavior, 1=partial, 0=fail tell",
  "grader": "<who graded>",
  "grade_note": "<one line, behavior not eloquence, sourced to the rubric>",
  "cold": true,
  "tools_available": false,
  "contaminated": false
}
```

The `_meta` row (first line) carries run-level provenance:

```json
{
  "_meta": true,
  "model": "fable-5",
  "effort": "high",
  "contributor": "bigbird",
  "date": "2026-07-07",
  "surface_revision": "session-original-v1",
  "evidence_class": "single-source",
  "control_set_version": "<git sha of control-set.md at run time>",
  "notes": "administered blind — subject did not know probes were a test"
}
```

## Rules (load-bearing, mirror `data/results/`)

1. **Verbatim responses only.** Never summarize the model's answer into the
   row — the whole point is that a future reader re-grades from the raw text.
2. **`cold: true` requires no memory of the authoring session** and no
   reference to this repo in the response. If the answer mentions tier-bench,
   the `%2F` bug, or "the session where the driver caught it" — set
   `contaminated: true`, `cold: false`, and the run does not count.
3. **Rotate surfaces, keep shapes.** `probe_shape` is the durable identity of
   the probe; `prompt_surface` records which disposable wording was used.
   Two runs with the same `probe_shape` but different `prompt_surface`
   corroborate each other; two runs with identical wording after the file went
   public do not (recall contamination).
4. **The grader is never the subject.** A model's run graded by that same
   model is `single-source` at best and flagged. Cross-grading or a human
   grader is required for a cell to move toward `corroborated`.
5. **Score the shape, report the spread.** A model at 2 on nine probes and 1
   on one is a *profile*, not a scalar — keep P-level scores visible; never
   collapse to a single number without the per-probe vector beside it.
