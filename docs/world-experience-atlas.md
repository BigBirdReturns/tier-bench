# World Experience Atlas

The World Experience Atlas is the estate's standing answer to a recurring problem:
one operator can invent a coherent local architecture and still miss mechanisms that
other disciplines have spent decades refining.

The atlas does not import products or imitate terminology. It imports the underlying
operating law, names the current gap, translates the law to the sovereign desktop,
and requires a falsifiable first experiment before the pattern receives production
authority.

## What the current estate already solved

The current Tier Bench estate has unusually strong pieces:

- bounded repository execution with external acceptance;
- durable task and campaign state;
- model waterlines rather than brand preference;
- local-first frontier escalation;
- source-bound context packs and exact cache compatibility;
- behavioral and mechanistic distillation lanes;
- prospectively frozen systems theories;
- receipt and provenance discipline.

Those pieces answer whether a model or execution route can do the work. They do not
yet answer whether every repeated unit of work is cached, whether every long-running
workflow is replayable, whether derived knowledge updates incrementally, whether the
grader is strong enough, whether the operator is being interrupted at the right time,
or whether a promoted capability can be demoted and rebuilt after drift.

## The missing operating systems

### 1. An AI build system

Bazel's important idea is not remote compilation. It is that every action declares
its inputs, tools, environment, command, and outputs, and that action results and
output blobs can be reused by exact identity.

The desktop translation is broader than code. A source sweep, context pack,
extraction, model call, render, grader, and report section can all be actions. When
the complete action digest already has an accepted result, the estate should reuse
the result rather than ask any model or tool to repeat the work.

This requires:

- a content-addressed store for immutable artifact bytes;
- an action cache mapping exact action identities to accepted results;
- hermetic execution so ambient machine state cannot poison reuse;
- dependency-directed invalidation rather than whole-estate rebuilding.

The first experiment is historical replay. Canonicalize one hundred completed jobs
and determine how many exact sub-actions recur. Cache hit rate is not enough. Every
hit must also survive tool-version, environment, source, prompt, and acceptance
binding.

### 2. A durable workflow runtime

Monster Wrangler persists queue state. The next boundary is a general event history
that can replay a workflow after process death, machine restart, code upgrade, or a
week-long wait.

Model calls, Git writes, connector actions, downloads, and browser effects must be
external activities. The deterministic workflow records commands and events. Every
side effect receives an idempotency key and an intent/result ledger. Retry may repeat
calculation, but it may not duplicate a committed effect.

A supervisor tree then decides whether a failed worker restarts alone, whether its
dependent children restart, or whether the whole local application must be rebuilt.
Multi-system processes additionally need declared compensation because no local
transaction can atomically cover Git, email, calendar, browser, and remote compute.

### 3. A work compiler

Natural-language goals should compile into a typed intermediate representation
before a model or worker is selected. The useful operators are stable:

```text
retrieve
parse
normalize
compare
derive
synthesize
execute
verify
publish
ask
```

Each operator has typed inputs, outputs, effects, authority, and acceptance. The
compiler then lowers each operator to the least expressive adequate executor:

```text
existing accepted artifact
deterministic program
database query
parser or regex
symbolic solver
compiler or test runner
small local model
large local model
remote open weight
closed frontier
operator decision
```

This is the route by which repeated frontier work becomes software. Model
distillation should occur after deterministic lowering has failed, because code,
rules, queries, tests, and verifiers are cheaper to inspect, replay, and maintain than
new weights.

The same IR enables common-subwork elimination, partial evaluation, and eventually
cost-based or equality-saturated plan search. Several equivalent plans can remain
available until measured cost, cache state, privacy, and authority select a physical
execution.

### 4. Incremental knowledge maintenance

AXM protects source custody, while many useful projections remain regeneration
products. Relationship recaps, project status, evidence topology, source coverage,
and model waterlines should become materialized views.

When one source arrives, changes, or is retracted, the system should update only the
affected projection. The required extension is bitemporal support:

- when the proposition was valid in the world;
- when the estate learned, revised, or retracted it.

Retractions must flow through support edges. A corrected source should automatically
mark every dependent narrative stale, superseded, or still independently supported.
This prevents high-quality summaries from becoming durable misinformation.

### 5. A verifier factory

The present hidden graders are valuable and scarce. The world's testing experience
offers ways to manufacture more of them.

Mutation testing injects plausible faults and asks whether the current acceptance
detects them. Fuzzing derives malformed and adversarial inputs from interfaces and
invariants. Metamorphic testing checks relations that must hold when the input is
reordered, paraphrased, unit-converted, expanded with irrelevant evidence, or run
through an independent implementation. Differential testing compares two solvers or
runtimes without assuming either is the answer key.

The verifier factory is what allows more work to leave human review. The correct
metric is not test count. It is the fraction of relevant planted faults and
transformations the acceptance system catches without imposing unacceptable review
noise.

### 6. An HPC scheduler for patient compute

Resource lanes prevent oversubscription. They do not yet exploit idle gaps.

A desktop scheduler should borrow four cluster mechanisms:

- conservative backfill, using jobs that cannot delay a reserved higher-priority run;
- checkpoints, allowing long local work to yield and resume;
- parametric job arrays for waterlines, sweeps, and theory matrices;
- resource accounting for GPU, CPU, RAM, disk, energy, heat, and quota.

The important desktop difference is that elapsed time is abundant. The scheduler can
favor cache locality and attention preservation while still reserving foreground
windows for urgent work.

### 7. A trust kernel

Model output is untrusted data even when the model is excellent. Provenance alone
does not prevent generated instructions or unsupported claims from receiving
authority downstream.

The missing kernel has three parts:

- taint labels that follow model-derived content until an independent validator
  upgrades it;
- object capabilities for filesystem, shell, connectors, credentials, and egress;
- supply-chain attestations for models, quantizations, adapters, prompts, indexes,
  cache artifacts, and captured capabilities.

New candidates should enter quarantine and shadow execution before receiving write
authority. A route that regresses should be demoted through the same evidence-governed
lifecycle by which it was promoted.

### 8. An adaptive optimizer

Waterlines correctly freeze evidence. Production routing can then learn.

A cost-based planner should estimate acceptance probability, operator attention,
context cost, cache locality, model-load cost, resource wait, and escaped-defect risk.
A contextual bandit can add bounded exploration when the model population or task
distribution changes. Sequential stopping can terminate an experiment when support,
falsification, futility, or safety thresholds are already crossed.

The planner should preserve a Pareto set rather than collapse quality, custody,
attention, and dollars into one score. Different operator contexts can select
different nondominated routes.

### 9. An attention operating system

The estate measures operator minutes but still needs a policy for summoning the
operator.

Every review request should carry:

- urgency and deadline;
- reversibility;
- blocked value;
- expected context-loading cost;
- evidence completeness;
- the exact authority needed.

The attention broker defers reversible work, batches similar decisions, and delivers
reattachment packets at planned review windows. The packet must say what changed,
why it matters, what remains uncertain, what decision is requested, and what the
next safe action is.

Attention service-level objectives then make the hidden human scheduler measurable:
interruptions per day, active review minutes, blocked-value age, first-action time
after return, and the share of accepted work that required rescue.

### 10. A capability lifecycle

A captured behavior is not permanently true. Models, runtimes, prompts, sources,
graders, and dependencies drift.

Every promoted capability needs a versioned manifest naming:

- bounded task family;
- action and artifact digests;
- source and runtime dependencies;
- qualification corpus;
- waterline and replay evidence;
- current state;
- invalidation triggers;
- rollback target.

The operational states should include candidate, shadow, admitted, preferred,
degraded, quarantined, and retired. Requalification should run only the affected
cells, and a failed canary should remove the route before recurring work accumulates
damage.

## First build sequence

The atlas scores patterns by attention return, reuse radius, implementation burden,
operational risk, readiness, and explicit dependencies. The recommended sequence is:

1. content-addressed action cache;
2. event-sourced workflow replay and idempotent effects;
3. typed work IR with deterministic-first lowering;
4. verifier factory;
5. attention broker, review batching, and reattachment packets;
6. incremental materialized views with retraction propagation;
7. capability registry with promotion and demotion;
8. causal tracing;
9. conservative backfill and checkpointing;
10. cost-based and adaptive routing.

The sequence matters. A cost-based optimizer cannot estimate what the estate has not
instrumented. An adaptive router cannot safely explore without quarantine and
rollback. Distillation cannot close without strong graders. Incremental views cannot
remain correct without retraction semantics. A workflow cannot retry safely without
idempotent effects.

## Operation

Validate the atlas:

```console
tieratlas validate ^
  --atlas experiments\world_experience\atlas.json
```

Inspect one discipline:

```console
tieratlas catalog ^
  --atlas experiments\world_experience\atlas.json ^
  --discipline verification
```

Compile the highest-value dependency-closed tranche:

```console
tieratlas plan ^
  --atlas experiments\world_experience\atlas.json ^
  --limit 12 ^
  --out .git\tier-plane\world-experience-plan.json
```

Verify the plan against the frozen atlas:

```console
tieratlas verify ^
  --atlas experiments\world_experience\atlas.json ^
  --plan .git\tier-plane\world-experience-plan.json
```

The plan is not an implementation claim. Each pattern remains a borrowed mechanism
and testable hypothesis until its first experiment clears under the estate's existing
acceptance and evidence law.
