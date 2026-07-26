# Sovereign desktop experiments

This directory contains zero-model-call fixtures for the attention-first desktop execution plane and distillation lab.

- `desktop_3090_4060.json` models a 24 GiB 3090, an 8 GiB 4060, CPU, RAM, NVMe, and one frontier subscription lane.
- `distillation_lab.json` models behavioral, mechanistic, and transport-contaminated residue.
- `context/` contains small source files whose exact hashes let CI exercise context-pack materialization.

The examples are architecture fixtures. Runtime versions marked `freeze-on-target-machine` and absent backend bindings must be replaced with machine-observed values before live execution. No example starts a model, writes provider credentials, applies a patch, or claims a measured performance result.
