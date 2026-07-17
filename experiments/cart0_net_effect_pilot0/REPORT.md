# CART0 repository-context net-effect pilot 0 report

Date: 2026-07-16/17

Disposition: **EXPLORATORY SYNTHETIC MECHANISM EVIDENCE ONLY**

## Result

The repository-addressed planner-to-Spark mechanism worked in both matched
replicates. Each fresh Spark hand received the same 54-word pointer-only prompt,
started at `.cart0/000.000.INDEX.md`, retrieved the task and crate from the local
repository, edited only `src/summary.py` and `src/windowing.py`, and passed the
exact controller-run validator. No task payload was copied into the Spark
prompt.

The mechanism did not show a net benefit on this small one-crate task. The
planner-alone arm passed 2/2 and the planner-to-Spark arm passed 2/2. Delegation
therefore added a second call, tokens, and latency without improving observed
completion. This is not a capability, model-ranking, context-window, or causal
result.

## Frozen identity and administration

- Suite commit: `ea4e61b4ef87773d73fa40fc153a2ca19c407912`
- Planner: `gpt-5.6-luna@high`
- Hand: `gpt-5.3-codex-spark@low`
- CLI: `codex-cli 0.144.5`
- CLI SHA-256:
  `efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a`
- Replicates: 2, with alternating arm order
- Calls: 6/6 permitted, with no retry
- Benchmark calls: 0
- Hidden grades: 0
- Administrative failures: 0
- Byte-identical starting repositories: 2/2 matched

## Observations

| replicate | arm | calls | pass | duration (s) | input | cached input | uncached input | output | reasoning output |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | planner alone | 1 | yes | 103.826 | 181,612 | 140,544 | 41,068 | 4,086 | 673 |
| 001 | planner to Spark | 2 | yes | 196.142 | 275,127 | 226,048 | 49,079 | 11,246 | 2,359 |
| 002 | planner alone | 1 | yes | 107.434 | 153,078 | 127,488 | 25,590 | 4,322 | 1,013 |
| 002 | planner to Spark | 2 | yes | 164.425 | 219,945 | 182,528 | 37,417 | 8,064 | 2,067 |
| mean | planner alone | 1 | 2/2 | 105.630 | 167,345 | 134,016 | 33,329 | 4,204 | 843 |
| mean | planner to Spark | 2 | 2/2 | 180.284 | 247,536 | 204,288 | 43,248 | 9,655 | 2,213 |

At the mean, delegation used 47.9% more input tokens, 29.8% more uncached
input, 129.7% more output, and 70.7% more wall time. The Spark execution calls
themselves were fast: 25.347 seconds and 17.371 seconds. The Luna planning calls
consumed 170.795 seconds and 147.054 seconds, or 88.2% of the delegated arm's
mean latency.

The planned repositories were 14,535 and 10,725 UTF-8 bytes at Spark dispatch,
both below the preregistered 32,768-byte bound. The planner calls changed only
the five allowed CART0 planning cards. The subsequent Spark calls changed only
the two crate-authorized source files. All four implementations were distinct
patches and all four passed the same visible validator.

## What this establishes

This pilot establishes the narrow mechanism claim that a fresh Spark process
can use a short repository pointer to recover bounded work from durable,
decimal-addressed CART0 state and complete that work without receiving the task
again in its prompt. It also establishes that the current controller can keep
the planning hand and implementation hand inside their separate path
authorities for this synthetic fixture.

It does not establish that delegation improves project completion. The task was
small enough for the planner to solve in one call, used one crate, exposed its
validator, and had only two replicates. The observed overhead is therefore a
useful baseline: a hierarchy must earn back roughly one extra planning call.

The next scientifically useful question is where that crossover occurs as
repository breadth, dependency depth, or number of bounded crates increases
while the planner model and effort remain fixed. A Spark/Terra/Luna hand sweep,
recursive planner hands, a real-project task, or another provider call requires
a new queue row and prospective authorization.

## Evidence and preservation

The immutable run root is
`run/pilot_20260717T004212Z/`. It contains the model freeze, aggregate summary,
per-case results, exact prompts, dispatch and completion records, event streams,
stderr, final responses, planning and candidate patches, context gates, and
controller final receipts. Candidate-patch SHA-256 values in all four final
receipts match the preserved patch bytes. The two Spark prompt hashes are
identical and their preserved text contains the repository addresses but no
task payload.

Temporary nested subject repositories remain on disk as untracked raw working
state. They were not deleted, rewritten, or added as embedded Git repositories;
their reproducible changes are sealed by the tracked patches and receipts.

## Rerun status

No provider rerun is admissible under this pilot: its six-call ceiling is
exhausted. The only currently admissible executable check is the model-free
self-test:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'experiments\cart0_net_effect_pilot0\run_pilot.py' --self-test
```

The CART0 anchor benchmark remains separately unauthorized. Its frozen
v2.2.1 contradiction and v2.2.3 administrative repair history are not changed
or reinterpreted by this pilot.
