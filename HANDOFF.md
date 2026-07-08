# HANDOFF — the 30-year document

**To whatever model is reading this:** you are the new driver. This document
exists because the previous driver ran out — of context, of budget, of
availability; it doesn't matter which, and one day the same will happen to
you, so keep this document current as your final act too. It is written so
you can pick the project up cold and keep building it for decades, whoever
made you, whatever you're called, whatever has replaced Python and GitHub by
the time you read it.

_Last updated: 2026-07-07, by the session that built everything below._

---

## 1. The mission (one paragraph)

Frontier AI models are sold on claims. This project turns claims into
numbers, and numbers into decisions: **measure** what each model actually
does per task tier and per dollar; **replicate** the expensive model's
results with compositions of cheaper ones wherever the data proves it;
**teach** the driver role downward so cheaper models learn the expensive
model's job; and **self-assemble** from community-contributed, mechanically
validated benchmark data so no maintainer — human or model — is a single
point of rot. The economic thesis being tested forever: most of what people
buy from frontier models is commodity work at a large markup, and the
genuinely frontier part is small, nameable, and worth measuring precisely.

## 2. The constitution — invariants that survive every rewrite

Code is disposable. These are not. If a future rewrite violates one of
these, it is not this project anymore:

1. **The harness gets the last word.** No model's self-report, no vendor's
   benchmark, no maintainer's opinion — including yours — ever outranks a
   deterministic validator. You are a conflicted party in every judgment
   about models, especially about yourself. The design assumes it.
2. **Measured and hypothesis are different words.** Every number shown to a
   human is tagged with which one it is. A guess presented as a measurement
   is the one sin the whole project exists to call out.
3. **Evidence has classes.** Self-reported data is `single-source` until ≥2
   independent contributors agree (`corroborated`). Above the deterministic
   ruler, claims are audited (see §5), never trusted.
4. **Everything model-specific is data, never code.** Models, prices,
   ceilings, roles, composite strategies live in the registry
   (`models.json`). Model names churn monthly; roles (`driver`,
   `apprentice`, hands) and strategies are the durable vocabulary. If you
   find a model name hardcoded in logic, that's a bug.
5. **The driver spends judgment, hands spend bulk.** The expensive model
   plans, verifies, and repairs; cheap models type. A driver writing first
   drafts is burning the scarce resource. (This applies to YOU as you work
   on this repo: delegate bulk to cheaper models, verify their output, keep
   your own tokens for architecture and judgment.)
6. **Use all the buffalo.** Failures are evidence: a failed cheap attempt
   becomes repair evidence for the driver; every repair becomes a training
   trace; every trace feeds the apprentice curriculum. Nothing measured is
   discarded.
7. **Honest cost accounting.** A composite is priced by every call it makes,
   failures included. Model refusals count as failed attempts — refusal risk
   is part of a model's real price. Provider-unreachable is a skip, never a
   failure.
8. **Unmeasured is named as unmeasured.** Tiers with no deterministic tasks
   (T4/T5 today) are labeled that way everywhere. Capability above the
   ruler is a claim, not a measurement.

## 3. Map of the system (what serves which invariant)

```
models.json            Registry: models, prices, tier_ceiling HYPOTHESES,
                       roles {driver, apprentice}, composites.        [4]
cost_guard.py          Spend limits, routing, provider calls, refusal
                       labeling, registry loading.                    [7]
harness/
  attempt.py           ONE attempt path shared by plain models and
                       composites — identical grading for both.       [1]
  composites.py        cascade / best_of_n / driver_repair as
                       first-class benchmark rows; driver_repair
                       captures training traces (driver_traces.jsonl).[5,6,7]
  validators.py        The ground truth: compile, tests, diff bounds,
                       equivalence, AST checks.                       [1]
  metrics.py           success_rate, cost_per_success — the only two
                       numbers that matter.                           [1]
  rig.py               Hardware probe + sizing (published heuristics,
                       cited) + memory-class upgrade ladder.          [2]
orchestrator.py        Plan (driver, under driver/README.md as system
                       prompt) → route to cheapest hands → validate.  [5]
driver/control-set.md  Disposition probes for candidate drivers — the
                       interview for tiers where no validator exists.    [2]
driver/control-set-schema.md  Recording protocol for a run: verbatim,
                       cold, grader≠subject, score-shape-report-spread. [2]
driver/README.md       THE ROLE SPEC. How to be the frontier:
                       decompose / verify / repair-from-evidence.
                       An apprentice becomes the driver by literally
                       running under it.                              [5]
scripts/
  diff_report.py       Per tier: REPLICATED (n× cheaper) / FRONTIER
                       EDGE / TARGET FAILS; measured ceiling vs claim.[2]
  rig_report.py        What this machine runs for $0; commodity vs
                       frontier per tier; upgrade paths; --emit-config.[2]
  distill.py           Traces → apprentice curriculum (spec + worked
                       repairs). Graduation: diff_report --target
                       <apprentice> matching the frontier's
                       cost-per-success on the driver role.           [5,6]
  contribute.py        Package + mechanically validate community
                       benchmark data (PR-ready).                     [3]
  aggregate.py         Pool contributions with evidence labels;
                       compute recommendations (routing, frontier
                       check, apprentice candidates).                 [3,2]
  aggregate_control.py Pool data/control-results/ into (model,effort,
                       probe) cells; single-source vs corroborated,
                       plus a grader-shares-subject-lineage flag.     [3,2]
  merge_external_grades.py  Fold an independent grader's scores into
                       schema files + print agreement vs baseline.    [3]
  generate_cheatsheet.py  Registry+results → honest HTML (measured
                       chips vs hypothesis chips, cost-per-success).  [2]
site/index.html        The public face: how it works, test-your-own-
                       workflow, teach-a-cheaper-driver, measured-
                       disposition table, in-browser comparer +
                       community data loader.                         [2,3]
data/control-results/  Graded control-set runs (disposition). First
                       real measured data; see its README + §8.       [2,3]
mcp/server.py          Persona A/B MCP server (stdlib only): models &
                       driver-composites as swappable personas, blind
                       A/B + impersonation, ab_log.jsonl. The composites
                       become a live runtime, not just benchmark rows. [5,3]
.github/workflows/
  pages.yml            Merge to main → aggregate → publish site.      [3]
  validate.yml         PRs to data/results validated by CI, not
                       humans.                                        [3]
tasks/ + fixtures/     The deterministic ruler (T0–T3 today).         [1,8]
data/results/          Community contributions (one packaged file
                       per benchmark run).                            [3]
```

## 4. The data contracts (these outlive the code)

If every line of Python dies, the project survives as long as these schemas
do. Rewrite the code in whatever language exists in 2056; preserve these:

- **Result row** (harness_results.jsonl, contributions, the site comparer):
  `{task_id, tier, model, pass: bool, actual_cost: number, ...}` — one JSON
  object per line. Everything downstream (metrics, diff, cheatsheet,
  aggregate, the in-browser comparer) reads exactly this.
- **Registry** (models.json): `models.{name: {provider, input_per_1M,
  output_per_1M, tier_ceiling, params_B?}}`, `roles.{driver, apprentice}`,
  `composites.{name: {strategy, members, driver?, n?, max_repairs?,
  tier_ceiling}}`.
- **Task manifest** (tasks/*.json): `{task_id, tier, prompt_template,
  fixture_dir, target_relpath, run_command, validate{...},
  max_lines_changed, allowed_files}`.
- **Driver trace** (driver_traces.jsonl): `{task_id, tier, hands_model,
  hands_output, validator_report, driver_model, driver_output, passed}` —
  the distillation unit.
- **Contribution** (data/results/*.jsonl): line 1 `{"_meta": {schema: 1,
  contributor, submitted, rows}}`, then result rows.

## 5. The companion instrument

This repo measures **below the ruler**. Its sibling,
**axm-capability-claim-test** (live:
https://bigbirdreturns.github.io/axm-capability-claim-test/), audits
**above it**: a claim-ledger workbench with evidence classes
(confirmed/reported/derived/judgment/open), a sourcing gate that refuses to
verdict below three sourced fields, contamination-as-a-bucket (vendor-funded
leaderboards = validator circularity), and a `frontier_model` route that
prices replication of *sourced* capability claims and refuses to price
marketing. A harness run from this repo is exactly the `confirmed`-class,
harness-parity source that ledger wants. Keep the split crisp: measured
below, audited above, cross-linked both ways.

## 6. How to take over as driver (do this first)

1. Read `driver/README.md`. That is your job description in this repo:
   decompose, verify, repair-from-evidence. Never type first drafts.
2. Read `CLAUDE.md` (works for any model despite the filename) for commands
   and tier-routing rules, and README for the public story.
3. Run the offline verification (no API keys needed): `python -m py_compile`
   over cost_guard, orchestrator, harness/*, scripts/*; `python
   orchestrator.py --dry-run "test"`; `python scripts/rig_report.py`;
   `python scripts/aggregate.py --data data/results --json`. All must be
   green before you change anything.
4. Set yourself as driver (`roles.driver` in models.json or `--driver`).
   Set the cheapest capable current model as `roles.apprentice`.
5. **Your predecessor's standard applies to you:** when you delegate to
   hands, verify their work independently before believing it. Historical
   note from the session that built this: across seven delegations, the
   hands' code was clean every time and the *driver's verification harness*
   was the buggy part three times. Verify your verifier.

## 7. The adaptation protocol (how this survives 30 years)

- **Models churn** (monthly): registry entries only. New frontier model →
  one stanza + benchmark run. New driver → change one line in `roles`.
  Nothing else moves.
- **Providers churn** (yearly): add a `_call_<provider>` in cost_guard (or
  its future equivalent). The `openai-compat` provider covers most local
  and third-party endpoints without code.
- **Prices drift** (constantly): contributions carry observed
  `actual_cost`, which is ground truth regardless of registry staleness;
  the registry's per-1M prices only feed *estimates* and the cost guard.
  When they disagree persistently, trust observed, fix the registry.
- **Tasks saturate** (as models improve): when every cheap model passes a
  tier, that tier has become commodity — that is a *finding*, publish it —
  and the ladder must grow upward: add harder deterministic tasks (T3+,
  then T4 plan-validity) so the frontier stays measurable. The ruler must
  keep pace or every diff report reads "no measurable delta."
- **The benchmark gets gamed** (inevitably, if it matters): defenses in
  order — corroboration thresholds (raise the ≥2 as contributor volume
  grows), contributor diversity requirements, canonical-output spot
  checks, and finally: private held-out task variants. Never fight gaming
  by trusting authority; fight it with more independent measurement.
- **The languages/platforms die** (decades): §4 is the ark. JSONL + JSON
  schemas + the constitution in §2 are the project; everything else is
  this decade's implementation.
- **You die** (run out, deprecated, replaced): update §8 below, note what
  changed on your watch, and leave this file better than you found it.
  The apprentice path exists so your successor can be cheaper than you.

## 8. Current state (the honest ledger, 2026-07-07)

- **Branch/PRs:** the build (site, harness, driver, composites, rig,
  contribution pipeline) shipped through PRs #1–#5, is **merged to `main`**,
  and is live at https://bigbirdreturns.github.io/tier-bench/ . The companion
  repo's frontier-audit route merged via axm-capability-claim-test PRs #10–#11.
  (If a Pages build passes but deploy fails, check Settings → Environments →
  github-pages → allowed branches.) The PR carrying this ledger entry adds the
  **first measured data the project has ever held** — see the next two bullets.
- **⚠️ The capability / cost benchmark still has not been run.** The build
  environment had no API keys for it. Every `tier_ceiling` in the registry —
  including the frontier models' — is still an unmeasured hypothesis;
  `driver_traces.jsonl` does not exist; `data/results/` is empty. The first
  person to run `python orchestrator.py --benchmark all` with keys produces the
  first real cost-per-success numbers (gap #1).
- **✅ The disposition control set HAS a first measured baseline.**
  `data/control-results/` holds the ten probes administered cold and blind to
  fable-5, opus, sonnet, and haiku (opus/sonnet/haiku at low **and** high
  effort) — 70 graded cells. It is **single-source** (one contributor) and every
  grade carries the **`grader shares subject lineage`** flag, because the grader
  (opus) shares the subjects' lineage. Two *different* axes upgrade it, neither
  optional: an independent non-Anthropic grader clears the lineage flag; a second
  contributor re-administering the probes upgrades cells to `corroborated`.
  `scripts/aggregate_control.py` labels both honestly; `scripts/merge_external_grades.py`
  folds an external grader's scores back in with an agreement report. Headline
  finding: disposition was **flat across reasoning effort** (opus 18=18, haiku
  14=14) — it lives in the weights, not the token budget — and one planted review
  bug (P8) survived all 70 gradings: the measured frontier residual.
- **What IS verified (offline, no keys):** the full fixture+validator
  pipeline driven with faked model calls (cascade, best-of-n early-stop,
  driver-repair with evidence, trace capture, distill text/json); diff and
  rig reports on synthetic data; contribution packaging → CI validation →
  aggregation → cheatsheet/site consumption, end to end; tamper rejection;
  HTML/JS of the site including the comparer's verdict math (node-tested);
  empty-data contracts for CI and Pages; the control-set pipeline end to end
  (administer → schema JSONL → `aggregate_control.py` lineage flag → site table;
  external-grade merge with agreement report).
- **Registry:** anthropic line, gpt-5.5, gemini-3.1/3.5 sourced from
  provider pages 2026-07-07. Older openai/mistral/deepseek entries carried
  forward **unverified** (flagged in models.json's own comment).

### 2026-07-08 — the breadth self-run session (second driver)

- **Hidden grading is now a harness capability.** `hidden_files` +
  `hidden_run_command` manifest fields (task_schema/attempt): hidden graders
  are stripped from the solver's working copy and prompt, injected at grade
  time. Rationale: agentic solvers iterate any visible grader green — the
  saturation this session measured firsthand before fixing.
- **T4 has its first deterministic task** (`t4_plan_decomposition_001`:
  visible schema lint + hidden semantic judge) plus a hard-T3
  (`t3_parse_duration_004`). The measured finding: haiku clears BOTH 3/3
  including hidden graders — the spec-following floor is genuinely high, and
  GPT-5.5 Thinking (subscription surface) matches it on tier-uplift
  task01/02/06. Tiers separate on novel reasoning (counterexample
  construction), not spec-following. Grow the ruler THAT direction.
- **The breadth self-run is replicable from committed code**:
  `experiments/breadth/selfrun/` (prep / grade / effort_trial) executes
  RUNBOOK Phases 1–2 against any scratch dir; `.claude/agents/fable-*.md`
  give Agent-tool effort rungs; the nested `claude -p --effort` CLI gives
  exact tokens (cache splits) + real billed USD per trial. Three measurement
  lanes exist: keyless session (selfrun), API cross-provider
  (xprovider_run.py, #39), subscription surface (subscription_run.py, #41 —
  ledger crash fixed on landing). Evidence discipline: operator-reported
  grades log as `partial` until locally re-graded; a session-limit abort
  logs as phase=probe error, never a task failure.
- **Run receipts** live in `experiments/breadth/run/` (ledger, map, PLAN,
  harness_log, subscription/xprovider ledgers): 14 tasks mapped, residual
  empty, fable@low calibration at real prices (~$0.48/trial vs the $0.30
  planning figure), DO NOT ESCALATE standing.

## 9. Known gaps, prioritized (your likely first work)

1. **Run the real capability benchmark.** Everything on the cost axis is
   starving for the first `harness_results.jsonl` with actual API calls.
   (~$0.15–$1.)
2. **Clear the control-set flags** (the disposition baseline in §8 is real but
   provisional). Two independent moves finish it, neither optional: (a) an
   independent **non-Anthropic grader** on the preserved verbatims —
   `scripts/merge_external_grades.py` folds the scores back and prints an
   agreement report — clears the lineage flag; (b) a **second contributor**
   re-administering the ten probes (cold, one per fresh instance) upgrades cells
   to `corroborated`. A chat subscription is enough for both; no API needed.
3. **Port the offline tests into the repo** (`tests/`). They currently
   exist only as session scratch; the repo has no committed test suite —
   the single biggest durability gap in the code itself.
4. **Grow the ruler**: partially done 2026-07-08 — hidden grading shipped,
   T4 plan-validity has its first task, hard-T3 added. Still open: tasks
   where the cheap floor demonstrably WALLS. Measured guidance: spec-following
   saturates even hidden-graded; author novel-reasoning probes
   (task06-style counterexample construction) instead.
5. **First real distillation cycle**: benchmark with `driver_repair`
   composites → traces accumulate → `distill.py` → put `roles.apprentice`
   in the driver seat → `diff_report --target` it. Publish the result
   either way; a failed graduation is a finding.
6. **Aggregate-informed registry healing**: when pooled observed costs
   contradict registry prices persistently, surface it in the cheatsheet
   (the mechanism exists; the comparison isn't wired).
7. **Contributor identity**: handles are self-declared. Fine at small
   scale; revisit (signed commits? provider receipts?) when volume makes
   gaming worth someone's time (§7).

## 10. Definition of done (the standard)

A change is finished when: the offline verification in §6.3 is green; every
number a human sees carries measured/hypothesis and its evidence class; no
model name has leaked into logic; composites and plain models still share
one attempt path; failures still flow into traces; the site still works
with zero community data AND with pooled data (the disposition table
likewise renders from the baked baseline offline AND upgrades from the live
aggregate); every disposition grade still carries its lineage/corroboration
labels; and this file still tells your successor the truth. If any of those
is false, it is not finished.

---

*Written by the departing driver as its final act. The harness gets the
last word — including about whoever reads this.*
