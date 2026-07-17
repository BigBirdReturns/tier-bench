# Local Qwen no-think residue: SQL null-filter knot

## Durable conclusion

The prior empty-final wall was a model/transport-condition failure, not evidence
that the model attempted and failed the SQL task. Setting Ollama `think:false`
changed that boundary: all three fresh calls emitted full Python programs.

Under the resulting frozen condition, `qwen3.5:9b-q4_K_M` still hit a sealed
0/3 task wall. All three independent seeds made the same implementation error:
inside a per-record evaluator they used `records[field]`, indexing the outer
list with a string, instead of indexing the current record. Every candidate
compiled, then the visible command crashed with `TypeError: list indices must
be integers or slices, not str`; both hidden reruns also failed. The residue
broker therefore abstained.

This conclusion is scoped to this model, quantization, prompt, task, and
sampling condition. It does not establish a general inability to implement
three-valued logic.

## Controlled comparison

The only model condition changed from `local_qwen_residue_t3_null_filter_v1`
was Ollama `think:false`. Model, task bytes, prompt hash, temperature, seeds,
fresh-context rule, no-tool rule, three-call ceiling, grading, and broker policy
were held fixed. The administrative canary is preserved separately and is not
part of either scientific K-window.

| Trial | Seed | Input tokens | Output tokens | Final chars | Wall time | Visible | Hidden reruns | Repeated residue |
|---:|---:|---:|---:|---:|---:|---|---|---|
| 1 | 101 | 974 | 1,131 | 4,395 | 34.03 s | fail | fail, fail | `records[field]` |
| 2 | 202 | 974 | 1,247 | 4,796 | 37.07 s | fail | fail, fail | `records[field]` |
| 3 | 303 | 974 | 1,243 | 4,768 | 36.75 s | fail | fail, fail | `records[field]` |

Packet SHA-256:
`3b2969c1e9fd85cf0819f740e846930d2c67e6677731657c989abce941572305`.
Prompt SHA-256:
`bd13aca4ee9899f26df03206d6a78eb5e1dc061018ee6d90fb2b07a40c7a1bcd`.
Hidden grader SHA-256:
`183d1539ad94e928ee917aa3958ee8359591312246aa44ccbc58e45c32059dd5`.

## Next deterministic task

The next justified experiment is a visible-error repair relay: give each failed
candidate only its visible traceback, ask for one full-file correction under
the same no-think condition, then grade the sealed repair against the unchanged
hidden grader. That tests whether repository-driven refinement removes the
stable binding defect without leaking hidden evidence.
