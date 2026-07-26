# Frontier Residue Refinery

Frontier Residue Refinery is the campaign layer above Monster Wrangler. It turns one bounded repository task into an unattended sequence of independent `tier run` trials across an operator-declared route ladder. The route may begin with a slow local model, continue through remotely hosted open weights, and end at closed frontier services. The existing acceptance command remains the sole referee.

The product objective is verified yield per unit of operator attention. Wall-clock latency is recorded but is not optimized. A local model may work for hours if the job remains bounded, supervised, and independently verifiable.

## Authority boundary

The refinery owns campaign sequencing and local residue records. It does not:

- hold provider credentials or call provider APIs;
- grade model output;
- alter a backend manifest, prompt template, or acceptance command;
- apply a patch or merge a branch;
- claim general model superiority from one task;
- claim that behavioral imitation recovered proprietary weights;
- promote a residue candidate into the capture ledger without a real reusable artifact and replay receipts.

Every trial is an ordinary Monster Wrangler task. `tier run` prepares the isolated packet, invokes the committed backend adapter, runs the operator acceptance command, and emits a receipt. `tier verify` remains authoritative.

## Two campaign modes

### `local_first`

The route ladder is a production escalation path. The controller begins at the first route and follows the existing ARC-C broker law:

- a route clears only after the latest `K` decisive receipts are all passes;
- a route becomes a measured wall only after the latest `K` decisive receipts are all failures;
- errors remain visible but never buy escalation;
- mixed pass and fail windows collect another trial;
- a frontier route is reached only after every preceding route earns a wall;
- the campaign stops at the first route that clears.

Set `k` to `1` for ordinary bounded work. Set `k` to `3` or more when the purpose is a repeated capability measurement rather than delivery of one accepted patch.

### `survey`

Every declared route receives its own `K`-receipt evaluation. A clearing route does not stop the survey. This mode measures the frontier map and is appropriate for scheduled bakeoffs, new-model intake, and residue discovery. The survey never presents later routes as earned escalation because their execution was preregistered by the operator.

## Trial ceiling and non-decisive evidence

`max_trials_per_route` bounds unstable or transport-damaged routes. When a route reaches that ceiling without a clear or wall, it becomes `inconclusive`. A `local_first` campaign stops there because errors and mixed evidence do not justify spending a more privileged route. A `survey` records the inconclusive route and continues to the next preregistered route.

This is intentional. A broken local adapter is an adapter problem, not proof that the local model lacked the capability.

## Residue candidates

A residue candidate is created when a later route clears and no earlier route cleared.

- `capability_residue`: every earlier route reached a measured wall.
- `transport_contaminated_residue`: one or more earlier routes remained inconclusive, usually because transport or infrastructure errors prevented a clean comparison.

The candidate binds the exact task fingerprint, route order, `K`, backend manifest bindings, trial receipt hashes, patch hashes when available, cost telemetry, and source-access classification. It remains scoped to the exact frozen task.

The candidate also chooses a capture lane:

- `mechanistic` when weights or runtime source are available;
- `behavioral` when access is API-only or subscription-only.

That lane is a next action, not a closure claim. The existing capture ledger still requires a reusable artifact and distinct hidden-graded replays before a frontier call can be described as amortized.

## Storage

Campaign control state lives in the same SQLite database as Monster Wrangler:

```text
.git/tier-desk/desk.sqlite3
```

Human and machine-readable projections are materialized locally:

```text
.git/tier-desk/residue/
  campaigns/<campaign-id>.json
  candidates/<residue-id>.json
```

Trial evidence remains under the established receipt root:

```text
.git/tier-runs/monster-wrangler/<task-id>/attempt-###/
```

The repository checkout is not modified.

## Campaign plan

A plan is a JSON object. Backend manifests must already be committed at the managed repository's current `HEAD`.

```json
{
  "schema": "tier-bench/frontier-residue-campaign@1",
  "id": "overnight-local-first-001",
  "title": "Repair the parser without spending frontier quota unless necessary",
  "mode": "local_first",
  "k": 1,
  "max_trials_per_route": 4,
  "queue_now": false,
  "task": {
    "task": "Fix the parser bug described by the failing tests. Preserve all unrelated behavior.",
    "files": ["src/parser.py", "tests/test_parser.py"],
    "acceptance": "python -m pytest -q tests/test_parser.py",
    "priority": 70
  },
  "policy": {
    "max_total_cost_usd": 2.00,
    "max_remote_trials": 3,
    "materialize_candidates": true
  },
  "routes": [
    {
      "id": "local-3090",
      "label": "Resident 3090 cartridge",
      "manifest": "backends/local-qwen.json",
      "arm": "arm_b",
      "execution_class": "local",
      "source_access": "source_and_weights",
      "capability_basis": "measured",
      "estimated_max_cost_usd": 0
    },
    {
      "id": "open-frontier",
      "label": "Hosted open-weight frontier",
      "manifest": "backends/kimi-k3.json",
      "arm": "arm_b",
      "execution_class": "remote_open_weight",
      "source_access": "weights",
      "capability_basis": "unmeasured",
      "estimated_max_cost_usd": 0.50
    },
    {
      "id": "closed-frontier",
      "label": "Closed frontier driver",
      "manifest": "backends/frontier-driver.json",
      "arm": "arm_b",
      "execution_class": "remote_closed",
      "source_access": "subscription_only",
      "capability_basis": "measured",
      "estimated_max_cost_usd": 1.00
    }
  ]
}
```

`estimated_max_cost_usd` is a per-trial pre-dispatch bound. When a campaign has `max_total_cost_usd`, an unknown estimate blocks the next remote trial rather than silently spending through the cap.

## Operation

Start Monster Wrangler as usual:

```console
tierdesk --repo C:\path\to\repo --daemon
```

Create a draft campaign:

```console
tierresidue create --repo C:\path\to\repo --plan campaign.json
```

Create and start it in one command:

```console
tierresidue create --repo C:\path\to\repo --plan campaign.json --start
```

Inspect campaigns and candidates:

```console
tierresidue list --repo C:\path\to\repo
tierresidue show --repo C:\path\to\repo --id overnight-local-first-001
tierresidue candidates --repo C:\path\to\repo
```

A running campaign is canceled through the live Desk task controls so the supervised process tree is terminated. The CLI refuses to mark a campaign canceled while its task is still running.

## What this first slice proves

This slice makes the daily operating loop concrete:

1. The operator freezes one task, scope, acceptance predicate, route ladder, and spend policy.
2. The Desk runs local work unattended for as long as the backend requires.
3. The same deterministic referee decides every trial.
4. A frontier call occurs only after the declared evidence law permits it, or because `survey` preauthorized the comparison.
5. The controller preserves failures, accepted artifacts, costs, and route provenance.
6. A later success becomes a residue candidate without being mislabeled as a completed capture.

The next layer is capture execution: materialize a reusable scaffold, adapter, curriculum, or weight delta from a candidate, then feed distinct replay receipts into the existing capture ledger. This campaign layer supplies the bounded evidence packet that work was previously missing.
