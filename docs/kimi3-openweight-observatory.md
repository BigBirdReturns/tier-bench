# Kimi K3 Open-Weight Observatory

The Kimi K3 Open-Weight Observatory keeps two estates separate:

1. the **frozen baseline lane**, which binds the canonical downloaded bytes to the
   completed Tier Bench grid before any intervention; and
2. the **dissection lane**, which performs static analysis, sampled numerical work,
   runtime tracing, community reconnaissance, simulation, and later ablations without
   modifying the canonical weight directory.

The system is headless, zero-dependency for static work, local-first, and designed for
an interrupted multi-day download. It does not import Python from the downloaded model
repository during static analysis.

## What it records

A frequent scan inventories stable files, ignores partial-download suffixes, parses
safetensors headers directly, reconciles the weight index, maps layers and experts,
indexes architecture symbols with Python AST parsing, and writes a stable model-estate
digest. A nightly scan additionally creates resumable chunk-tree custody for large
shards and performs deterministic numerical samples. A full scan can also compute
whole-file SHA-256 for large shards, although chunk-tree custody is sufficient for the
baseline contract.

The dissection plan contains fifteen bounded work orders:

```text
A00 download convergence
A01 byte custody
A02 weight-index concordance
B01 source architecture map
B02 layer topology
B03 expert estate
B04 precision and packed-dtype map
C01 numeric fingerprints
C02 expert redundancy candidates
D01 runtime module trace
D02 router-utilization grid
D03 long-context state accounting
E01 desktop expert-offload simulation
E02 controlled ablation grid
F01 desktop capability capture
```

Static similarity never establishes runtime importance. Runtime claims must bind the
exact model revision, runtime revision, frozen prompt family, and external acceptance.

## Baseline and current grid

Create an active marker before or during the current full grid:

```powershell
New-Item D:\TierRuns\Kimi-K3\.grid-active -ItemType File -Force
```

Install the package and run the lightweight cycle while download and grid work continue:

```powershell
cd D:\Projects\Cloud\BigBirdReturns\tier-bench
py -m pip install -e .

tierkimi validate `
  --config experiments\kimi3_observatory\observatory.local.json

tierkimi observe `
  --config experiments\kimi3_observatory\observatory.local.json `
  --profile frequent
```

The frequent profile reads metadata and safetensors headers but does not stream every
large shard. It can therefore discover missing shards, index disagreement, unsupported
packed dtypes, topology anomalies, and source/runtime clues while the grid owns the
expensive execution plane.

When the grid is terminal, remove the marker and build content custody:

```powershell
Remove-Item D:\TierRuns\Kimi-K3\.grid-active -ErrorAction SilentlyContinue

tierkimi observe `
  --config experiments\kimi3_observatory\observatory.local.json `
  --profile nightly
```

Freeze only after all model files are stable, every stable file has a full or chunk-tree
content identity, the safetensors index is concordant, shard headers have no anomalies,
and the grid root contains Tier Bench receipts:

```powershell
tierkimi baseline-freeze `
  --config experiments\kimi3_observatory\observatory.local.json `
  --label kimi3-grid-2026-07-27
```

The baseline binds the model-estate digest, tensor census, dissection plan, every grid
receipt, and the grid-receipt-set digest. Later community discoveries can open new
experiments, but cannot rewrite this baseline.

## Continuous observation

Generate and install two Windows Scheduled Tasks:

```powershell
tierkimi schedule-windows `
  --config experiments\kimi3_observatory\observatory.local.json `
  --out .git\tier-kimi\install-kimi3-observatory.ps1

powershell -ExecutionPolicy Bypass `
  -File .git\tier-kimi\install-kimi3-observatory.ps1
```

The frequent task defaults to every thirty minutes. The nightly task defaults to 02:00.
Both use `MultipleInstances IgnoreNew`, and the observatory also holds a local exclusive
lock. A heavy cycle is downgraded when any configured grid marker exists.

Inspect the current state and the compiled execution bundle:

```powershell
tierkimi status --config experiments\kimi3_observatory\observatory.local.json

tierkimi work-bundle `
  --config experiments\kimi3_observatory\observatory.local.json `
  --out D:\TierEstate\Kimi-K3\execution-bundle.json
```

The execution bundle shows which work orders are already automated by frequent or
nightly observation, which require a runtime worker, and which community hypotheses
currently point to each work order.

## Community reconnaissance

The watcher supports Reddit OAuth, GitHub issue and pull-request search, Hugging Face
model revisions, Atom feeds, and manual JSONL import. It stores no Reddit author field.
It keeps only a short title/excerpt, URL, timestamp, score, technical metadata, content
hash, taint, and a prohibition on training use.

Reddit API access requires explicit Reddit approval. Until that approval exists, keep:

```json
"approval_confirmed": false
```

The source is then reported as blocked rather than silently scraped. GitHub and manual
imports continue. After approval, set a descriptive user agent and credentials:

```powershell
$env:REDDIT_CLIENT_ID = "..."
$env:REDDIT_CLIENT_SECRET = "..."
$env:REDDIT_USER_AGENT = "windows:tier-bench-kimi3-observatory:v1 (by /u/<account>)"
```

Then set `approval_confirmed` to true in the local community configuration.

Manual imports use one JSON object per line:

```json
{"id":"local-001","url":"https://www.reddit.com/...","title":"K3 expert offload report","body":"Hardware, runtime commit, command, measurement, and observed failure.","score":0}
```

Synchronization deduplicates by source and external identity. Claim extraction assigns
one of five evidence tiers:

```text
official_release
reproducible_receipt
detailed_report
assertion
speculation
```

Social score can change triage priority but cannot increase evidence tier. Every claim
remains `UNVERIFIED`, is mapped to one or more local work orders, and enters a
hypothesis queue. A post or comment can open an experiment, but cannot close one.

```powershell
tierkimi community-sync `
  --config experiments\kimi3_observatory\observatory.local.json

tierkimi community-claims `
  --config experiments\kimi3_observatory\observatory.local.json `
  --minimum-score 40

tierkimi community-fuse `
  --config experiments\kimi3_observatory\observatory.local.json
```

## Runtime dissection

Static scans work before a full runtime exists. Router and state measurements require a
runtime capable of loading the frozen revision. The optional PyTorch probe records only
module identity, tensor shapes, sampled aggregate statistics, and router expert IDs. It
does not retain raw prompts or full activations.

```python
from pathlib import Path
from tier_runner.kimi3_probe import ProbeSession

with ProbeSession(
    model,
    trace_path=Path("D:/TierEstate/Kimi-K3/traces/grid-router.jsonl"),
    model_revision="<model-estate-sha256>",
    runtime_revision="<runtime-commit-or-image-digest>",
    task_family="tier-bench-grid",
    prompt_id_sha256="<frozen-prompt-sha256>",
):
    model.generate(**inputs)
```

Reduce router traces and replay them against a desktop cache model:

```powershell
tierkimi probe-reduce `
  --config experiments\kimi3_observatory\observatory.local.json `
  --trace D:\TierEstate\Kimi-K3\traces\grid-router.jsonl

tierkimi offload-simulate `
  --config experiments\kimi3_observatory\observatory.local.json `
  --trace D:\TierEstate\Kimi-K3\traces\grid-router.jsonl `
  --expert-bytes 268435456 `
  --gpu-experts 32 `
  --ram-experts 192 `
  --pcie-gbps 24 `
  --nvme-gbps 6.5 `
  --prewarm-experts 16
```

The simulator reports GPU, RAM, and NVMe hit rates plus estimated transfer bytes and
stall time. It is a routing-trace simulator, not an inference benchmark.

## State layout

```text
D:/TierEstate/Kimi-K3/
  model/
    model-scan.json
    tensor-census.json
    tensors.jsonl
    dissection-plan.json
    numeric-sample.json
    router-report.json
    expert-offload-simulation.json
  hash-state/
    hashes/*.json
  community/
    items.jsonl
    last-sync.json
    claims.jsonl
    claim-report.json
    hypothesis-queue.json
  baselines/
    <label>.json
  logs/
    cycle-*.json
  execution-bundle.json
  last-cycle.json
```

The canonical model directory remains outside this tree and is treated as read-only.
Derived quantizations, ablations, adapters, or patched runtimes should receive their own
content-addressed directories and must never overwrite the frozen source weights.
