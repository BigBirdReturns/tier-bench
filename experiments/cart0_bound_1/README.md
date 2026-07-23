# CART0-BOUND-1 — B1 functional-equivalence pilot

This is the preregistered two-task comparison authorized by the committed
`CART0-BOUND-1` queue row. It changes no task, hidden grader, pass criterion,
ledger closure rule, or cost accounting.

The run is deliberately split across a commit boundary. Prepare generates the
two hidden-free packets, strict CART0 bundle, and four exact prompt files with
zero provider calls. Commit that directory before dispatch. Dispatch then makes
the four frozen fresh-session calls without printing response content. Grade
reruns each unchanged hidden grader twice only after all candidates are sealed.

```powershell
$py = 'C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$run = 'experiments/cart0_bound_1/run_20260714'

& $py scripts/cart0_bound1.py prepare --run $run
# Inspect hashes and commit $run before continuing.

& $py scripts/cart0_bound1.py dispatch --run $run
& $py scripts/cart0_bound1.py grade --run $run
& $py scripts/cart0_bound1.py compare --run $run
& $py scripts/cart0_bound1.py verify --run $run
```

`dispatch` refuses an uncommitted input manifest, any tracked drift, an existing
provider-output directory, prompt drift, or a retry. Provider-reported cache
reads, cache writes, uncached input, output, wall time, and cost metric remain
separate in every raw receipt. The cost basis is `subscription-derived`; the
provider cost metric is not asserted to be a bill.

The only preregistered operational label requires both arms to pass both
unchanged hidden graders and CART0 to reduce provider-reported total input by at
least 25% on each task. Even that earns only a two-task B1 result—not B2
causality, portability, production custody, billing savings, or a general
context-window claim.
