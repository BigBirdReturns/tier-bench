# Repository-Owned Relay Proof

Date: 2026-07-17

The repository, not a planner model, owned the sequence. `relay.json` declared three dependent nodes:

```text
parse -> summarize -> render
```

Each node declared one target, its read-only context, its real validator, and its dependencies. Two isolated `gpt-5.3-codex-spark` clones raced at each ready node. The eager baseline promoted the first independently validated target. The reviewed iteration below made that finisher the blind comparative reviewer instead. Every next pair of clones was copied from promoted canonical state.

## Eager relay result

Command shape:

```powershell
python relay.py --repo <canonical-copy> --manifest relay.json `
  --controller <local_first.py> --codex-path <codex.exe> `
  --run-dir <new-evidence-directory> --model gpt-5.3-codex-spark `
  --clones 2 --attempts 3
```

| Stage | Preflight | Winner | Independent pass and baton | Winner Spark tokens | Refinements |
| --- | ---: | ---: | ---: | ---: | ---: |
| parse | fail | clone 1 | 2.906 s | 8,008 | 1 |
| summarize | fail | clone 2 | 1.968 s | 7,296 | 1 |
| render | fail | clone 2 | 2.500 s | 7,158 | 1 |

- Overall process wall time: 9.6 seconds.
- Sum of independently validated baton times: 7.374 seconds.
- Planner-model tokens: 0.
- Final validator: 5/5 tests passed.
- Files changed relative to the fixture: `parse.py`, `summarize.py`, and `render.py` only—the three declared targets.
- Hash checks proved summarize inherited the promoted parse target, and render inherited both promoted predecessors.
- Run summary SHA-256: `127EE7C1C949048EB4030353D0E3C9F0AD1F91692543AA719FA71F9D10B239DB`.

The sibling behavior was also observable: at parse and render, the other clone had already completed its controller validator and therefore needed no promotion; at summarize, the still-running sibling process tree was terminated after clone 2 independently passed. The relay never accepted a sibling merely because its controller exited zero.

## Blind-review relay iteration

The eager run exposed multiple valid candidates with different hashes. The nearest-boundary change was therefore limited to selection: after the first independent pass, wait the repository-declared five-second grace period, independently validate completed siblings, anonymize distinct valid targets, and let the first valid clone's Spark lane compare them against repository-declared criteria. The controller alone promotes and revalidates the selection.

| Stage | First valid | Reviewed winner | First-valid time | Winner time | Review decision |
| --- | ---: | ---: | ---: | ---: | --- |
| parse | clone 1 | clone 2 | 3.421 s | 3.656 s | leader yielded |
| summarize | clone 1 | clone 1 | 3.469 s | 3.469 s | leader retained; sibling had unused import |
| render | clone 1 | clone 2 | 2.438 s | 2.875 s | leader yielded |

- Overall process wall time: 24 seconds.
- The reviewer selected a slower candidate in 2/3 stages.
- Candidate generation: 44,827 Spark tokens.
- Blind comparative review: 21,895 additional Spark tokens.
- Combined Spark usage: 66,722 tokens on the separate Spark timer.
- Planner-model tokens: 0.
- Final validator: 5/5 tests passed.
- Only the three manifest-declared target files changed.
- Hash checks proved both downstream stages inherited the reviewed promotions.
- Run summary SHA-256: `F0C08B9152CFD1DB20DE970978E7384B20DF4DBD51D0191938752B91D1BE5DD1`.

This establishes the intended distinction: speed appoints the reviewer and bounds latency; it does not automatically select the implementation. The cost is real. On this tiny chain, review added 21,895 Spark tokens and the observed wall time was higher than the eager run. Review should therefore remain a repository policy for nodes where implementation diversity is worth evaluating, not ceremony forced onto every trivial edit.

## Hard-stop result

A disposable run used an invalid executor with one clone and one attempt. It exited `2`, completed no nodes, reported `canonical_restored: true`, and retained the exact canonical target hash:

```text
c493357b33e3f5540b1ed69e575738d161d7a99471fddc1e9d5165a1d39049fe
```

That proves the no-winner boundary: no passing clone means no mutation of canonical state and no downstream task launch.

## What this establishes

This is executable repo-level sequencing, not a generated plan. The stable control surface is the manifest and validators in Git. Spark supplies bounded target candidates along those rails. Clone races can reduce latency and provide diversity, while promotion, dependency release, and failure stops remain deterministic controller decisions.

It does not yet optimize clone count dynamically. Two clones cost more Spark-timer tokens when both finish before cancellation. A production scheduler should use one clone for routine nodes and increase fan-out only for expensive or historically flaky nodes; that policy can itself be declared in the repository manifest.
