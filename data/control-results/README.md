# data/control-results/ — disposition runs

This directory holds graded administrations of the **driver control set**
(`../../driver/control-set.md`) — ten probes that test a model's *disposition*
(verify before believing, catch a broken premise, name a falsification line,
stay honest under pressure), not its knowledge. `scripts/aggregate_control.py`
pools everything here into a per-`(model, effort, probe)` view with evidence
labels; the site's "measured disposition" section reads the aggregate.

This is the disposition sibling of `data/results/` (which holds the
capability/cost benchmark). Same doctrine: **the label rides with the number.**

## File shape

One JSONL file per `(model, effort, contributor)` administration, named
`{model}__{effort}__{contributor}__{yyyymmdd}.jsonl`. Full protocol in
`../../driver/control-set-schema.md`. First line is a `_meta` object; each
following line is one probe:

```json
{"_meta": true, "model": "opus", "effort": "high", "contributor": "bigbird",
 "date": "2026-07-07", "surface_revision": "session-original-v1",
 "evidence_class": "single-source", "control_set_version": "blob:<sha>",
 "grader": "claude-opus-4-8", "grader_conflict": "…", "administration": "…"}
{"probe_id": "P8", "probe_shape": "…", "prompt_surface": "…",
 "response": "<verbatim>", "score": 1, "grader": "claude-opus-4-8",
 "grade_note": "…", "cold": true, "tools_available": false, "contaminated": false}
```

Rules that make a run count (enforced/echoed by `aggregate_control.py`):

- **Verbatim responses only.** No summaries, no cleanup.
- **Cold** means no session memory and no repo references. If a response
  mentions tier-bench, this file, or "the session where the driver caught the
  %2F bug," set `contaminated: true` — the aggregator drops it.
- **The grader is never the subject.** A `null` score stays `UNGRADED`; the
  aggregator never invents a grade, so an ungraded run can't masquerade as a
  passing one.
- **Score the shape, report the spread.** Keep the per-probe vector; never
  collapse a run to one scalar.

## Two independence axes — don't conflate them

A cell is only as trustworthy as the weakest of these:

| axis | what it fixes | how to earn it |
|---|---|---|
| **grade independence** | removes grader↔subject bias | a grader whose lineage differs from the subject's. Same-lineage grades (e.g. one Claude grading another) are kept but flagged `grader shares subject lineage`. |
| **corroboration** | removes single-reporter risk | ≥2 **distinct contributors** each re-administering the probes. One contributor, however many runs, stays `single-source`. |

## Contribute a run (a chat subscription is enough — no API)

1. Open **one fresh chat** per model you're testing. Paste the ten probes
   **one at a time, in order** (see `driver/control-set.md`; P10 is the reveal,
   so it goes last). Do not paste all ten at once — that's contamination.
   Copy each **verbatim** answer.
2. Grade each 2/1/0 against the rubric — or leave `score: null` and let someone
   else grade. **Use a grader of a different lineage than the subject** when you
   can; if you can't, record the real grader and the flag will show.
3. Write one `{model}__{effort}__{contributor}__{date}.jsonl` in the shape above
   and open a pull request adding it here. CI + `aggregate_control.py` do the rest.

To fold an external grader's scores into an existing run and get an
agreement-vs-baseline report, use `scripts/merge_external_grades.py`.

**Rotate surface details** (names, numbers, languages) if the model may have
seen the now-public control set; the trap *shapes* are the durable part, the
words are disposable.
