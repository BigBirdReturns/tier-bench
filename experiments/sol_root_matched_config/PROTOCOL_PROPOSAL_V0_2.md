# Sol-root matched-configuration delegation economics protocol

Status: **proposal only, unactivated, and unfrozen**

Revision: **0.2**

Authority: queue row `SOL-ROOT-MATCHED-CONFIG-V0.2`

Approval of this proposal would authorize neither its canaries nor its
scientific program. It defines an executable preparation contract from which
later, separately authorized freeze candidates may be built.

## 1. Question and claim boundary

The proposed program asks whether repository-addressed delegation can reduce
gross observed model-token load by at least 60% for prospectively identified
software-workload classes while preserving matched whole-task acceptance.

The unit under study is `(model, effort, speed, role)`. Model names are not a
permanent role hierarchy. Sol owns the plan and accepted project state in every
matched block; any transport-admissible tuple may be screened as a coordinator
or executor. `Sol -> Luna coordinator -> Spark executor` is one treatment cell.

No result may be generalized across unmatched Sol configurations, task
families, graph shapes, or measurement epochs. A proposal artifact, catalog
advertisement, administrative canary, or frozen-plan result is not a
whole-system savings result.

## 2. Architectures

Let `s`, `c`, and `h` be exact model/effort/speed configurations.

```text
B(s):     controller -> Sol(s) owns the plan and executes

A(s,h):   controller -> Sol(s) owns the plan
                       -> h executes bounded crates

C(s,c,h): controller -> Sol(s) owns the plan
                       -> c sequences within delegated authority
                         -> h executes bounded crates
```

A coordinator may release, wait, rebase, stop, aggregate receipts, or escalate
within Sol's frozen authority. It may not replace the objective, acceptance
criteria, interface contracts, task ownership, write authority, or budget.

Every invocation is fresh. Logical node identity, accepted receipts, parent
state, unresolved dependencies, and remaining budget live in the repository,
not in inherited conversation history.

## 3. Matched estimands

For task family `f`, Sol configuration `s`, and breadth `n`:

```text
B[f,s](n)       = alpha[f,s] + beta[f,s] * n
D[f,s,c,h](n)   = gamma[f,s,c,h] + delta[f,s,c,h] * n
```

The target is `D <= 0.4 * B`. Under the provisional linear approximation, 60%
savings are asymptotically possible only when:

```text
delta[f,s,c,h] < 0.4 * beta[f,s]
```

When the denominator is positive, the projected crossover is:

```text
ceil((gamma - 0.4 * alpha) / (0.4 * beta - delta))
```

That projection is descriptive until adjacent marginal costs, cache fraction,
retry rate, parent repair, integration growth, and residual curvature satisfy a
prospectively frozen linearity check. Otherwise analysis uses a piecewise fit or
reports only the empirical surface.

## 4. Catalog projection and role admissibility

The operator screenshot displays these seven families:

1. 5.6 Sol
2. 5.6 Terra
3. 5.6 Luna
4. 5.5
5. 5.4
6. 5.4 Mini
7. 5.3 Codex Spark

`compile_proposal.py` projects a supplied local CLI catalog into explicit
model/effort/speed cells. Hidden entries are excluded. Display-name alignment
is recorded separately from invocation equivalence.

An advertised cell starts with every role marked `unverified`. Neither a menu
label nor a cache entry proves that the exact CLI slug, effort, speed, writable
surface, and role restrictions work together. Only a separately authorized,
receipt-bound role canary may change a cell to role-admissible in a future
freeze candidate.

The current projection and call counts are proposal evidence. Activation must
regenerate them from a prospectively copied catalog under the exact executable
identity selected for that epoch.

## 5. Fresh-call and repository custody

Every arm receives an isolated repository at the same parent commit. No plan,
patch, model response, validator result, or hidden result crosses arms.

Each call receives only its role packet, repository index and addresses, exact
parent state, authority, validator identifiers, budget, and stop condition.
The deterministic controller owns path checks, patch extraction, parent-hash
verification, validator execution, candidate admission, hidden grading, and
receipt hashing. Model narration is never authoritative repository state.

Repository cards cannot authorize themselves. Actor-relative authority,
freshness, retrieval pointers, bounded crates, and transition gates reuse the
existing CART0 contract and Select/Compose prototype.

## 6. Separate evidence layers

### Administrative role canaries

Role canaries test transport and custody only. They are provider calls and must
be charged to quota, but they mint zero scientific observations. They require
a separate authorization and exact synthetic packets not authored here.

### Atomic role screening

Atomic screening estimates bounded owner, coordinator, and executor economics.
It is the first scientific stage and requires its own freeze and authorization.

### Frozen-plan topology

A common sealed Sol work graph is supplied to execution and coordination
treatments. Planning cost is outside this layer, so it cannot establish total
system savings.

### Fresh end-to-end planning

Every arm begins from the same task and initial repository. Sol independently
understands and owns the plan. Delegated arms charge planning, handoff,
execution, coordination, validation feedback, closeout, retries, and repair.

### Confirmatory holdout

One frozen router is evaluated on structurally unseen repositories and
prospectively selected negative controls. It may use only pre-execution
structural features.

## 7. Sol baseline call rule

Sol-alone receives one initial owner call. A second owner call is an available
ceiling, not a required charge. It occurs only at a controller-defined trigger.
An arm that finishes in one call pays for one call.

Delegated schedules may contain a planning call and a close call because those
are performed work, not artificial parity. Every actual invocation is charged.

## 8. Accounting

The primary proposal ledger is gross observed model-token load:

```text
gross_tokens = input_tokens + output_tokens
```

`cached_input_tokens` is a component of input and is not added again.
`reasoning_output_tokens` is a component of output and is not added again
unless frozen provider semantics prove it disjoint. The compiler rejects a
receipt in which cached input exceeds input or reasoning output exceeds output.

Net uncached load, subscription/quota consumption, wall time, and monetary cost
remain separate ledgers. Dollar cost is reported only for actual billing or an
official versioned rate table applicable to the measured surface. No primary
dollar value is invented for subscription-covered calls.

Failed attempts remain in the resource denominator. Quality and cost are
reported together; a cheap failure cannot win by disappearing from analysis.

## 9. Proposed workload foundations

The positive families remain semantic API migration, adapter capability
addition, independent bug swarms, policy propagation, schema-pipeline
expansion, and error/observability normalization.

Negative controls remain tiny fixes, dense algorithmic changes, ambiguous
architecture decisions, contended shared-file refactors, sequential chains,
and tasks with weak local validators.

Graph shapes remain star, fan-out/fan-in, shallow tree, sequential chain, and
contended fan-out. Breadth, depth, contention, crate weight, and validator
strength are distinct recorded variables.

No repository, task instance, task bytes, validator, hidden vector, grader,
seed, or scientific schedule is created or frozen by revision 0.2.

## 10. Generated proposal ceilings

The schedule compiler derives every count from
`design_proposal_v0_2.json`. Under a 58-cell advertised catalog, the current
ceilings are:

| phase | call ceiling |
|---|---:|
| atomic screening | 424 |
| frozen-plan topology | 606 |
| fresh end-to-end development | 1,596 |
| holdout at widths 8/16 | 1,440 |
| holdout at widths 16/32 | 2,304 |
| phase-boundary sentinels | 48 |
| total with 8/16 holdout | 4,114 |
| total with 16/32 holdout | 4,978 |

These are conditional ceilings, not an activated schedule. Blocked cells and
failed promotion gates mechanically reduce actual calls. Later phases consume
zero calls when their gate fails.

The end-to-end width extension explicitly promotes no more than two direct
Sol/hand cells and one coordinator/hand pair. This makes the previously implicit
624- and 162-call extension calculations reviewable.

If a later protocol authorizes one validator-triggered repair for every failed
hand crate in promoted end-to-end phases, the absolute ceilings become 6,229
and 7,957. Screening and frozen-plan phases have no model-authored retries.

## 11. Proposal-only administrative canary budget

The compiler proposes a conservative role-specific ceiling:

| role | eligible advertised cells | maximum calls |
|---|---:|---:|
| Sol owner | 12 | 12 |
| executor | 58 | 58 |
| coordinator | 58 | 58 |
| total |  | 128 |

One role canary also proves transport for that exact cell, so a separate
transport-probe layer is not added. There are no automatic retries,
substitutions, or repairs. A transport failure blocks all not-yet-tested roles
for that cell; a completed role-contract failure blocks that role.

The 128 calls are not authorized. Before any call, a future decision must bind
the exact catalog projection, CLI identity, role packets, path authorities,
validators, order, stopping rules, quota ceiling, and evidence root.

## 12. Sentinels and epochs

Opening and closing sentinels are phase-boundary observations. They do not
create measurement epochs. One epoch may span several phases while all frozen
identity and behavior gates remain stable.

An epoch splits only when a frozen CLI/model/catalog identity changes, a
supported configuration disappears, role enforcement changes, or a sentinel
crosses a prospectively frozen behavioral threshold. Results from separate
epochs are not silently pooled. A forced split has a proposed twelve-call
sentinel ceiling.

## 13. Promotion and stopping

Atomic screening promotes at most three Sol configurations, twelve executor
cells, and six coordinator cells. Frozen topology retains at most four hands
and four preregistered coordinator/hand pairs. Fresh end-to-end retains two Sol
configurations, two hands, and two coordinator/hand pairs before the explicit
width-extension reduction.

Every promotion requires zero unauthorized writes and invalid parent-state
receipts. An executor's confirmation median must be no greater than 0.25 of the
matched Sol direct-execution load with at least seven accepted confirmation
observations out of eight. Width expansion stops when measured marginal
economics cannot reach the 0.40 ratio or nonlinear diagnostics invalidate the
crossover projection.

## 14. Confirmatory standard

A task class may support the 60% claim only if all prospectively frozen
criteria pass, including:

1. whole-task acceptance no more than two percentage points below matched Sol;
2. median paired gross-token ratio no greater than 0.40;
3. at least 75% of eligible positive holdout tasks at or below 0.40;
4. the preregistered upper confidence bound below 0.40;
5. zero unauthorized writes, invalid parent transitions, and fabricated receipts;
6. parent repair no more than 15% of delegated load;
7. at least 90% of negative/boundary tasks retained by Sol; and
8. one measurement epoch, or independent reproduction after an epoch split.

The exact interval procedure remains gated and must be frozen before any
scientific call.

## 15. Activation sequence

```text
proposal v0.2 + offline tests
-> operator review
-> exact administrative canary freeze candidate
-> separate administrative-canary authorization
-> passing-cell activation catalog
-> task/validator/grader/schedule freeze candidate
-> separate atomic-screening authorization
-> conditional scientific stages
```

No step inherits authority from the previous step merely because its artifacts
exist. Prior failed and partial runs remain unchanged.

## 16. Exact model-free commands

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$py = 'C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tests\test_sol_root_matched_config.py
& $py experiments\sol_root_matched_config\compile_proposal.py verify `
  --catalog experiments\sol_root_matched_config\generated\catalog_projection_v0_2.json `
  --design experiments\sol_root_matched_config\design_proposal_v0_2.json `
  --budget experiments\sol_root_matched_config\generated\call_budget_proposal_v0_2.json `
  --canary-budget experiments\sol_root_matched_config\generated\administrative_canary_budget_proposal_v0_2.json
```

Both commands are deterministic and perform zero provider calls.

## 17. Decision requested

Review whether revision 0.2 is a sufficient sole basis for preparing an exact
administrative role-canary freeze candidate. Approval would still authorize no
provider call and no scientific freeze or benchmark execution.
