# Offline model residue index

`model_residue_v1.json` is the single offline query point for the model evidence
currently produced by the local-first and Tier-Bench experiments. It covers:

- `gpt-5.6-sol`
- `gpt-5.3-codex-spark`
- Terra (the retained report does not identify a version)
- `qwen2.5:7b`
- `qwen3.5:9b-q4_K_M`
- `claude-fable-5`

The index does not replace evidence. Tier-Bench run entries point to their
sealed receipts. External local-first and token-parity sources are copied
byte-for-byte under `sources/`, with SHA-256 and byte count recorded in the
index. This makes the joined artifact usable offline even though the original
`token-parity-proof` evidence tree was not a Git repository.

`spark_effort_public_v1/` adds a matched clean-room matrix for
`gpt-5.3-codex-spark` at low, medium, and high effort. It contains 27 sealed
first-pass cells (three public-synthetic tasks, three replicates, no retries),
raw CLI JSONL, exact returned source, stderr, validator output, token/time
receipts, and a deterministic summary. This is effort-routing evidence, not a
substitute for the separately blocked private hidden-grade cell.

`fable_effort_public_v1/` currently preserves one green native Claude CLI
administrative canary for `claude-fable-5@low`. The canary established the
real result-envelope, session-identity, inherited-context, auxiliary-model,
and cost-accounting boundaries. It contains zero scientific observations;
the matched 27-cell Fable matrix remains pending.

The generated `coverage.thin_band` section keeps three different claims from
being blurred together: observed model separations, authored tasks that were
absorbed by the cheap floor, and capture-transfer economics. The current
capture state is deliberately not called free or amortized: the reusable
artifact has retired two frontier calls on distinct hidden-graded work items,
but the projected mixed-basis break-even is four validated replays. Reusing the
artifact itself is free; running the floor model is not.

Rebuild and verify on this workstation:

```powershell
python scripts/build_model_residue_index.py `
  --local-first 'C:\Users\BAM-Desktop\Documents\Tier Bench\local-first' `
  --token-parity 'C:\Users\BAM-Desktop\Documents\Tier Bench\token-parity-proof' `
  --out data/model_residue/model_residue_v1.json

python scripts/build_model_residue_index.py `
  --local-first 'C:\Users\BAM-Desktop\Documents\Tier Bench\local-first' `
  --token-parity 'C:\Users\BAM-Desktop\Documents\Tier Bench\token-parity-proof' `
  --out data/model_residue/model_residue_v1.json `
  --check
```

The `gaps` array is part of the result. In particular, the Spark hidden-graded
Tier-Bench cell remains unmeasured with zero calls, and the early Terra/Qwen
2.5 route measurements remain report-level mechanism evidence rather than a
hidden-graded capability map.
