# Benchmarks

The multi-task, three-replicate result is in `benchmarks/ROBUST_BASELINE.md`. The measurements below retain the earlier route-discovery sequence that led to that baseline.

Workload: the same `net_by_account` task from commit `7f253b184405eb40d1cd7aebe21ca4fa7db1c25c`. Every accepted route started with two `NotImplementedError` failures, changed only `ledger.py`, and independently passed 2/2 tests.

| Route | Model tokens | Cloud tokens | Observed wall | Gain vs direct |
| --- | ---: | ---: | ---: | ---: |
| Direct standard Terra agent | 106,030 | 106,030 | ~46.9 s | baseline |
| Cloud planner + standard Terra agent | 181,692 | 181,692 | not combined | 71.36% worse |
| Local planner + standard Terra agent | 99,290 | 98,675 | not combined | 6.36% |
| Lean Terra agent | 50,692 | 50,692 | 30.96 s | 52.19% |
| Bounded Terra candidate, manual controller | 8,791 | 8,791 | 5.90 s generation | 91.71% |
| Bounded Terra candidate, integrated controller | 9,151 | 9,151 | 7.6 s end to end | 91.37% |
| Bounded Spark 5.3 candidate | 6,926 | separate Spark timer | 5.20 s end to end | 93.47% |
| Default Spark refinement controller | 7,238 | separate Spark timer | 3.91 s end to end | 93.17% |
| Qwen 2.5 integrated controller | 955 | 0 | 16.3 s end to end | 99.10% |

The GPU-free production route is `--skip-local --cloud-candidate`. Spark 5.3 is the default and is charged to this account's separate Spark timer. The model gets no write authority and tool use is rejected; the controller applies the returned target file and the real validator decides. A failed candidate and its exact validator output feed the next fresh Spark attempt, up to three attempts. If none passes, the original bytes are restored and the full-agent Terra crate is written.

These measurements compare execution routes on one deliberately small real task. They prove the mechanism and its cost on this workload; they do not establish general coding quality across repositories or task sizes.

## Bounded hog-wild race

Two isolated clones started from the same failing commit.

| Arm | Sol timer | Spark timer | Wall to pass | Result |
| --- | ---: | ---: | ---: | --- |
| Sol bounded candidate | 9,147 | 0 | 6.916 s | 2/2 pass |
| Sol plan -> Spark candidate | 8,886 | 7,565 | 15.131 s | 2/2 pass |

The sequential handoff saved only 261 Sol tokens (2.85%) and added 8.215 seconds (118.78%), so it is rejected for this task class.

A second run launched Sol and Spark as true concurrent bounded candidates on isolated clones. Spark validated first at 5.605 seconds; Sol validated at 8.090 seconds. Time to first valid result improved 30.72% over Sol in the same race. Spark used 7,377 tokens on its separate timer and Sol used 9,153 tokens. Because the current probe did not cancel the losing process, concurrent racing is an explicit high-uncertainty mode rather than the cheap default.
