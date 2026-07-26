# Model Waterline Observatory

Model Waterline Observatory turns a vendor or operator substitution claim into a
bounded routing instrument. The first protocol asks where Claude Opus 5 can
replace Claude Fable 5, where a reusable Fable-derived artifact can move the
boundary, and where Fable retains a measurable residue.

The unit of evidence is an independently accepted result on a frozen task. Token
price, benchmark reputation, and model narration do not establish the waterline.

## The four waterlines

The instrument reports four separate boundaries.

1. **Capability:** the cheapest route that clears the same hidden acceptance.
2. **Economic:** the cheapest route per verified success, including failed trials.
3. **Attention:** operator active minutes and interventions per verified success.
4. **Autonomy:** clarification, rescue, and escaped-defect behavior over the task
   horizon.

These axes are never collapsed into one score. The operator may willingly trade
wall-clock time for attention, so elapsed time remains descriptive unless a task
contract makes it binding.

## Native and augmented boundaries

A native route receives the same task, context, tools, and acceptance contract as
the reference route. An augmented route also receives a prospectively frozen
artifact derived from earlier frontier work.

```text
native Opus 5
    answers where Opus replaces Fable immediately

Opus 5 + Fable advisor packet
    answers whether Fable strategy can be paid once and reused

Opus 5 + admitted captured residue
    answers whether the frontier move has become durable local property
```

The augmented arms remain blocked until the artifact exists, is hash-bound, and
is carried by a distinct prompt manifest. The instrument does not simulate this
state by pasting an informal summary into the prompt.

## Settlement law

The Opus 5 and Fable 5 protocol freezes the following evidence law:

- `K=1` may deliver one bounded production result.
- `K=3` may settle one exact hidden-graded cell.
- at least ten distinct tasks are required before proposing a family-level route;
- ten tasks still produce a routing proposal, not universal equivalence or a
  formal non-inferiority claim;
- runtime model identity must match the requested model;
- a fallback, missing runtime identity, incomplete telemetry, provider error, or
  serialization failure is non-decisive;
- errors do not buy escalation or establish reference residue;
- operator attention and escaped defects remain separate required ledgers;
- absent evidence produces `PARTIAL`, never a favorable inference.

The existing Frontier Residue Refinery remains the execution vehicle. Every route
is an ordinary `tier run`; the same external acceptance command judges every
trial.

## Files

```text
experiments/model_waterlines/
  README.md
  catalog.json
  opus5_fable5/
    protocol.json
    tasks.json

tier_runner/model_waterline.py
scripts/freeze_claude_waterline.py
tests/test_model_waterline.py
```

`catalog.json` inventories model-tier, effort, context, execution-surface,
orchestration, hardware, capture, and project-estate waterlines. It is the queue
of places where the same method can recover attention or produce capturable
frontier residue.

## Validate the instrument

```console
python -m tier_runner.model_waterline validate ^
  --protocol experiments/model_waterlines/opus5_fable5/protocol.json ^
  --tasks experiments/model_waterlines/opus5_fable5/tasks.json ^
  --catalog experiments/model_waterlines/catalog.json

python tests/test_model_waterline.py
```

The test suite makes zero model calls. It exercises hidden-task compilation,
manifest custody, native and augmented classification, runtime-fallback refusal,
transport-error refusal, attention and audit gates, and catalog validation.

## Bind Claude Code routes on the target machine

The protocol names the routes, models, efforts, resource lane, and expected
prices. The target repository must still bind its installed Claude Code binary,
version, help surface, prompt bytes, and adapter version before execution.

```console
python scripts/freeze_claude_waterline.py ^
  --protocol experiments/model_waterlines/opus5_fable5/protocol.json ^
  --repo D:\Projects\Cloud\BigBirdReturns\tier-bench
```

This writes one shared prompt, six native-route backend manifests, and a binding
receipt under `waterlines/`. It does not run a model and does not commit files.
Review and commit those bytes. Campaign creation is blocked until the manifests
exist in the target repository's committed `HEAD`.

## Compile draft survey campaigns

```console
python -m tier_runner.model_waterline compile ^
  --protocol experiments/model_waterlines/opus5_fable5/protocol.json ^
  --tasks experiments/model_waterlines/opus5_fable5/tasks.json ^
  --repo D:\Projects\Cloud\BigBirdReturns\tier-bench ^
  --out .git\tier-desk\waterlines\opus5-fable5
```

The compiler emits one `tierresidue` survey plan per ready task. Every plan is a
draft. Nothing is queued automatically.

The initial corpus contains seven existing hidden-graded knots. They establish
the lower bounded floor but cannot satisfy the ten-distinct-task family gate.
Ten prospective frontier-boundary slots are also registered for real repository
work, including root-cause repair, cross-repository reconciliation, incomplete
acceptance discovery, long-horizon migration, evidence synthesis, visual
implementation, autonomous recovery, counterexample construction, and authority
routing.

## Create and start a selected campaign

```console
tierresidue create ^
  --repo D:\Projects\Cloud\BigBirdReturns\tier-bench ^
  --plan .git\tier-desk\waterlines\opus5-fable5\<campaign>.json

tierresidue create ^
  --repo D:\Projects\Cloud\BigBirdReturns\tier-bench ^
  --plan .git\tier-desk\waterlines\opus5-fable5\<campaign>.json ^
  --start
```

All Claude routes share `subscription:claude-code` with concurrency one. A survey
therefore cannot consume the same subscription lane in parallel.

## Analyze results

Export or point the analyzer at campaign projections:

```console
python -m tier_runner.model_waterline analyze ^
  --protocol experiments/model_waterlines/opus5_fable5/protocol.json ^
  --tasks experiments/model_waterlines/opus5_fable5/tasks.json ^
  --campaigns .git\tier-desk\residue\campaigns ^
  --interventions .git\tier-interventions.jsonl ^
  --audits .git\tier-desk\waterlines\opus5-fable5-audits.jsonl ^
  --out .git\tier-desk\waterlines\opus5-fable5-report.json
```

The analyzer opens each trial's `ledger.jsonl` through its receipt path and
checks `extra.runtime_model_id` and `extra.telemetry_complete`. A request for
Opus that actually ran a fallback model cannot count as an Opus observation.

The report distinguishes:

```text
REPLICATED_NATIVE
REPLICATED_AUGMENTED
REFERENCE_RESIDUE
NO_DECISION
REFERENCE_NOT_CLEAR
```

A capability result remains `PARTIAL` until the task-count, attention, and
escaped-defect gates are satisfied.

## Capture handoff

A Fable-clear and Opus-wall result is only a bounded residue observation. It
opens one of two capture lanes:

- **mechanistic**, when weights or runtime source are available;
- **behavioral**, when access is API-only or subscription-only.

Closure still belongs to the existing capture ledger. A reusable artifact must
exist, and distinct hidden-graded replay receipts must demonstrate that the
lower route now performs the work. The original task cannot prove amortization
by being replayed against itself.
