# Universal Model Floor Observatory

The Universal Model Floor Observatory turns the existing pairwise waterline instrument into a complete model-routing map. It keeps three evidence objects separate:

1. **Internal waterlines**, where every model receives the same frozen task, tools, context contract, acceptance authority, and runtime attestation.
2. **External benchmark baselines**, where the benchmark operator publishes structured model scores and enough metadata to define a comparison cell.
3. **Community intelligence**, where practitioners report prices, throughput, memory, failures, scaffolds, and benchmark results that can open experiments but cannot settle them.

The system does not produce one universal model ranking. It produces the cheapest adequate route for each bounded task family and leaves every unmeasured model visible.

## The Opus 5 and Fable 5 delta

The existing protocol remains the direct internal instrument:

```text
experiments/model_waterlines/opus5_fable5/protocol.json
experiments/model_waterlines/opus5_fable5/tasks.json
```

The native route ladder is:

```text
Opus 5 low
Opus 5 medium
Opus 5 high
Opus 5 max
Fable 5 high
Fable 5 max
```

A token-price ratio is only a declared economic input. Replacement is measured through cost per independently accepted outcome, operator attention, escaped defects, and task-family coverage.

The focused delta report answers:

```text
Which tasks clear natively on Opus?
Which tasks require a Fable-derived augmentation?
Which tasks remain Fable-only residue?
What is the observed Opus/Fable accepted-outcome cost ratio?
What externally reported cells contain both models under a comparable setup?
Which model labels or runtime identities remain conflicted?
```

### Current run sequence

First produce or update the pairwise waterline report through the existing instrument:

```powershell
tierwaterline analyze `
  --protocol experiments\model_waterlines\opus5_fable5\protocol.json `
  --tasks experiments\model_waterlines\opus5_fable5\tasks.json `
  --campaigns D:\TierRuns\Opus5-Fable5\campaigns `
  --interventions D:\TierRuns\Opus5-Fable5\interventions.jsonl `
  --audits D:\TierRuns\Opus5-Fable5\audits.jsonl `
  --out D:\TierRuns\Opus5-Fable5\waterline-report.json
```

Convert every route and task result into the common observation format:

```powershell
tierfloor ingest-waterline `
  --protocol experiments\model_waterlines\opus5_fable5\protocol.json `
  --report D:\TierRuns\Opus5-Fable5\waterline-report.json `
  --out D:\TierEstate\ModelFloor\internal-observations.jsonl
```

For a whole estate of completed waterline reports, use the report-tree ingester:

```powershell
tierfloor ingest-root `
  --protocol-root experiments\model_waterlines `
  --reports-root D:\TierRuns `
  --out D:\TierEstate\ModelFloor\internal-observations.jsonl `
  --receipt D:\TierEstate\ModelFloor\internal-ingest.json
```

Reports with no matching frozen protocol remain visible as unmatched and do not enter the internal floor.

Create the full registry from every model currently listed in `models.json`:

```powershell
tierfloor registry-from-models `
  --models models.json `
  --overrides experiments\model_floor\registry.overrides.local.json `
  --id tier-bench-all-models `
  --out D:\TierEstate\ModelFloor\registry.json

tierfloor registry-validate `
  --registry D:\TierEstate\ModelFloor\registry.json
```

Then produce the focused delta:

```powershell
tierfloor delta `
  --registry D:\TierEstate\ModelFloor\registry.json `
  --protocol experiments\model_waterlines\opus5_fable5\protocol.json `
  --waterline-report D:\TierRuns\Opus5-Fable5\waterline-report.json `
  --external-observations D:\TierEstate\ModelFloor\external\observations.jsonl `
  --out D:\TierEstate\ModelFloor\opus5-fable5-delta.json
```

The internal report can settle a routing boundary. External rows remain directional unless benchmark revision, scaffold, tools, attempts, context policy, and metric all match.

## Identity law

A model name is not an identity. The registry separates:

```text
canonical model
declared alias
provider surface
runtime model ID
model revision
effort
quantization
hardware
```

Internal observations require runtime attestation. A request labeled `claude-opus-5` that reports another runtime ID is classified as `conflicted`, not as an Opus success or failure. A transport error, fallback, absent runtime ID, or ambiguous provider alias cannot create a capability wall.

External leaderboards often contain only a display name. Those rows may remain `unattested` and contribute to an external comparison distribution, but they cannot settle an internal routing decision.

Inspect identity state:

```powershell
tierfloor identity-audit `
  --registry D:\TierEstate\ModelFloor\registry.json `
  --observations D:\TierEstate\ModelFloor\internal-observations.jsonl `
  --observations D:\TierEstate\ModelFloor\external\observations.jsonl `
  --out D:\TierEstate\ModelFloor\identity-audit.json
```

## Full model floor

The floor configuration names task families and settlement thresholds. The supplied example includes:

```text
spec-following
judgment-boundary
repo-repair
cross-repository-reconciliation
architecture-contradiction
incomplete-referee
long-horizon-migration
evidence-synthesis
visual-fidelity
autonomous-recovery
counterexample-construction
authority-routing
computer-use
long-context
tool-use
knowledge-reasoning
```

For each family, the report contains:

```text
selected adequate floor
Pareto frontier
every measured route
every registered model as adequate, wall, collecting, or unmeasured
identity exclusions
cost per verified success
attention per verified success
escaped-defect count
external comparison cells
```

Compute the full floor:

```powershell
tierfloor compute `
  --registry D:\TierEstate\ModelFloor\registry.json `
  --config experiments\model_floor\floor.local.json `
  --observations D:\TierEstate\ModelFloor\internal-observations.jsonl `
  --observations D:\TierEstate\ModelFloor\external\observations.jsonl `
  --out D:\TierEstate\ModelFloor\floor-report.json
```

The selected route is the cheapest adequate route under the configured objective order. Wall-clock latency can remain a later objective because operator attention and accepted cost are the primary optimization targets.

## External benchmark plane

Copy the source configuration:

```powershell
Copy-Item `
  experiments\model_floor\sources.example.json `
  experiments\model_floor\sources.local.json

Copy-Item `
  experiments\model_floor\floor.example.json `
  experiments\model_floor\floor.local.json

Copy-Item `
  experiments\model_floor\registry.overrides.example.json `
  experiments\model_floor\registry.overrides.local.json
```

Validate and synchronize:

```powershell
tierfloor sources-validate `
  --sources experiments\model_floor\sources.local.json

tierfloor sync `
  --sources experiments\model_floor\sources.local.json `
  --state-dir D:\TierEstate\ModelFloor\external
```

The initial adapters are:

```text
hf_official_benchmarks
  discovers the official benchmark catalog on Hugging Face

hf_leaderboard
  imports ranked entries from an official benchmark dataset

hf_model_evals
  imports model-centric evaluation results

github_search
  captures issues and pull requests discussing model behavior and benchmarks

reddit_oauth
  captures approved Reddit API results without retaining author identities

http_json
  maps a public JSON leaderboard into observations

http_csv
  maps a public CSV leaderboard into observations

atom
  captures release and community feeds

jsonl_import
  imports manually preserved community claims or structured statistics
```

Every network response receives an immutable raw snapshot and a receipt containing the source, capture time, response metadata, payload hash, and byte count.

### Hugging Face benchmark discovery

The default source configuration discovers official benchmark datasets and imports the current SWE-bench Verified and Humanity's Last Exam leaderboards. It also imports the current LM Arena text, agent, web-development, search, and document cells through the Hugging Face dataset viewer. The rows endpoint is paginated to completion with bounded request pacing and rate-limit cooldown, every page receives an immutable snapshot receipt, and the published `category` field is preserved as an exact comparison dimension. A source that reports a partial dataset view, exhausts its retry budget, or exceeds its declared page ceiling fails closed instead of presenting an incomplete external baseline.

Add any official benchmark dataset by copying an `hf_leaderboard` or paginated `http_json` source and preserving the exact benchmark revision, dimensions, and setup fields.

The observatory never averages rows across different:

```text
benchmark revisions
scaffolds
tool policies
retry counts
context policies
metrics
directions
```

Each distinct setup receives its own comparison key. Optional benchmark dimensions such as category, language, modality, hardware class, or agent policy are included in that key, so leaderboard subcategories cannot be averaged together accidentally.

### GitHub and practitioner reports

GitHub search captures relevant issues and pull requests, extracts technical quantities such as throughput, latency, memory, and percentages, and preserves model-name candidates. These records remain community claims. They can identify a missing runtime fix, quantization, harness, or benchmark result, but do not enter the settled floor until converted into a structured observation or reproduced locally.

### Reddit boundary

The Reddit source remains blocked while:

```json
"approval_confirmed": false
```

After approved API access exists, set the required environment variables:

```powershell
$env:REDDIT_CLIENT_ID = "..."
$env:REDDIT_CLIENT_SECRET = "..."
$env:REDDIT_USER_AGENT = "windows:tier-bench-model-floor:v1 (by /u/<account>)"
```

Then set `approval_confirmed` to `true` in the local source configuration. There is no fallback scraping path.

Manual claims can be added to:

```text
experiments/model_floor/community.manual.jsonl
```

Structured statistics can be added using the shape in:

```text
experiments/model_floor/stats-import.example.jsonl
```

and written into a local `stats.manual.jsonl` file.

Community popularity can alter triage priority. It cannot increase evidence tier. Community text remains prohibited from training use unless a separate licensing review changes that status.

## External baseline interpretation

External baseline cells report:

```text
count
verified count
minimum
25th percentile
median
75th percentile
maximum
best model rows
full provenance-bearing row set
```

This supplies the external check the internal grid lacks. It can show that an internal result is unusually weak, unusually strong, or missing a community-discovered configuration. It cannot establish equivalence when the setups differ.

The practical reconciliation loop is:

```text
external result or community finding
  -> immutable snapshot
  -> identity resolution
  -> comparison cell
  -> discrepancy or missing-surface hypothesis
  -> local reproduction campaign
  -> internal accepted receipt
  -> model-floor update
```

## Continuous operation

A single refresh performs the complete reconciliation:

```powershell
tierfloor refresh `
  --sources experiments\model_floor\sources.local.json `
  --registry D:\TierEstate\ModelFloor\registry.json `
  --config experiments\model_floor\floor.local.json `
  --state-dir D:\TierEstate\ModelFloor `
  --protocol-root experiments\model_waterlines `
  --reports-root D:\TierRuns `
  --opus-protocol experiments\model_waterlines\opus5_fable5\protocol.json `
  --opus-report D:\TierRuns\Opus5-Fable5\waterline-report.json
```

Generate Windows Scheduled Tasks:

```powershell
tierfloor schedule-windows `
  --repo D:\Projects\Cloud\BigBirdReturns\tier-bench `
  --sources experiments\model_floor\sources.local.json `
  --registry D:\TierEstate\ModelFloor\registry.json `
  --config experiments\model_floor\floor.local.json `
  --state-dir D:\TierEstate\ModelFloor `
  --protocol-root D:\Projects\Cloud\BigBirdReturns\tier-bench\experiments\model_waterlines `
  --reports-root D:\TierRuns `
  --frequent-minutes 60 `
  --nightly-hour 3 `
  --out .git\tier-floor\install-model-floor.ps1

powershell -ExecutionPolicy Bypass `
  -File .git\tier-floor\install-model-floor.ps1
```

Both scheduled tasks run the same idempotent refresh contract. A refresh snapshots external sources, discovers every completed internal waterline report, rebuilds the internal observation set, and recomputes the full floor. The hourly task minimizes staleness; the nightly task guarantees catch-up after missed windows. Both use `MultipleInstances IgnoreNew`.

Inspect state:

```powershell
tierfloor status `
  --state-dir D:\TierEstate\ModelFloor\external
```

## Evidence boundary

The observatory does not claim that every registered model has been tested. It makes absence explicit. It does not turn leaderboard rank into a local routing decision. It does not turn a model alias into runtime identity. It does not turn social score into evidence. It does not average incompatible benchmark setups. It does not treat provider errors as capability failures.

The governing control question is whether a model is the cheapest route that repeatedly clears the exact task family, acceptance authority, runtime identity, attention boundary, and defect audit that matter to the local estate.
