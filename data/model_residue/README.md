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
