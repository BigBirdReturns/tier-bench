# Local coding flight protocol

This experiment qualifies the physical path from a GPU-UUID-pinned Ollama server through Claude Code into the existing sealed `tier run` boundary. It compares `gpt-oss:20b`, `qwen3-coder:30b`, and `devstral-small-2:24b` on identical hidden-graded repair tasks.

The flight has three evidence layers. The committed backend manifest binds the software and model surfaces. Each adapter call binds live Ollama model identity, context allocation, GPU residency, and the dedicated-server attestation. The outer launcher samples both NVIDIA GPUs and independently hashes the final report.

The initial result can establish executable-path qualification, task-level model differences, and physical GPU placement. It cannot establish production routing fitness, long-context fitness, repository-history generalization, or merge authority. Those claims require repeated historical replay or shadow-production receipts.

Run the protocol through `scripts/run-local-coding-flight.ps1`. The operator runbook and failure map are in `docs/local-coding-flight.md`.
