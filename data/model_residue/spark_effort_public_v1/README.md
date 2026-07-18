# Spark 5.3 public effort matrix v1

This is a clean-room, public-synthetic measurement of
`gpt-5.3-codex-spark` at `low`, `medium`, and `high` reasoning effort.

The matrix is fixed at three tasks, three efforts, and three fresh replicates:
27 scientific calls total. Every effort receives byte-identical task prompts.
The controller sends only the selected `PROMPT.md` bytes to the provider, runs
from an otherwise empty temporary directory, seals the response and CLI event
stream, and only then invokes the repository-owned validator. There are no
retries. Failed calls and invalid candidates remain in the aggregate.

This cell does not contain, derive from, or claim to measure the private
Tier-Bench hidden-grade corpus. Its purpose is narrower: measure how Spark 5.3
effort changes success, tokens, latency, and recurring defect shape on a small
deterministic public suite.

Run the model-free contract check:

```powershell
python scripts/run_public_spark_effort_matrix.py --self-test
```

Run or safely resume the fixed matrix:

```powershell
python scripts/run_public_spark_effort_matrix.py --run --resume
```

Rebuild only the aggregate from already-sealed cells:

```powershell
python scripts/run_public_spark_effort_matrix.py --summarize
```

