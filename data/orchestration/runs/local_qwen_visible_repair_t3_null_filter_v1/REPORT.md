# Local Qwen visible-error repair residue

## Result

One repository-driven visible-error repair did not clear the stable binding
defect. The repair rung sealed at 0/3 and the residue broker abstained.

Each repair subject received one distinct sealed parent candidate plus only its
visible command, exit code, stdout, and traceback. Repair packets excluded the
hidden grader and hidden outputs, and bound the parent candidate and normalized
visible-failure hashes. Subjects ran with `qwen3.5:9b-q4_K_M`, Ollama
`think:false`, temperature 0.2, seeds 101/202/303, fresh context, and no tools.
There were exactly three calls and no retries.

## Receipts

| Repair | Input tokens | Output tokens | Wall time | Compile | Visible | Hidden reruns | Residue |
|---:|---:|---:|---:|---|---|---|---|
| 1 | 1,515 | 2,542 | 116.39 s | fail | fail | fail, fail | syntax-corrupt full-file merge |
| 2 | 1,632 | 1,366 | 47.92 s | pass | fail | fail, fail | added `rec=` call without changing evaluator signature |
| 3 | 1,628 | 1,459 | 51.17 s | pass | fail | fail, fail | passed a second positional argument to a one-argument evaluator |

All three repairs identified that the evaluator needed the current record. The
failure was integration: each output changed only part of the required
function boundary or corrupted the surrounding file. This is a durable 3/3
diagnosis-versus-integration split, not an inference from one bad completion.

## Cross-layer conclusion

The three additive K-windows now separate three failure layers:

1. Default Ollama thinking: 0/3 empty final responses after 7,220 output tokens.
2. `think:false` one-shot: 0/3 complete programs, all with the same
   `records[field]` binding bug.
3. One visible-error repair: 0/3; all diagnosed the bug, none integrated a
   valid full-file fix.

Therefore the durable conclusion is not simply "Qwen cannot solve the task."
Under these exact conditions, disabling thinking fixes response emission, but
the model has a repeatable full-file state-integration weakness that one
traceback-driven repair does not remove.

The next justified design change is smaller edit scope: ask for a localized
patch to the evaluator boundary and let the repository apply and validate it,
rather than asking the model to regenerate the entire file. That would be a
new experiment, not a reinterpretation or retry of this sealed wall.
