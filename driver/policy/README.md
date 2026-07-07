# driver/policy/ — frozen orchestration snapshots

**What happens when the driver disappears?** Fable is happy to orchestrate its
plans — decompose the work, choose what to verify, decide when to escalate — but
that judgment lives only in its weights, and your access to it is temporary. This
directory is where that judgment is **captured as an immutable snapshot** so it
survives: a cheaper model loads a frozen policy and executes *under* it. The cheap
model is the hands; the snapshot is the driver's frozen brain.

This is different from `scripts/distill.py`. Distill captures what the driver
**answered** (repair examples — task-specific, brute-force). This captures how it
**decided** (the plan for a task *class* — generalizes, and it's the part that
does **not** yield to brute force: disposition is flat on effort, see
`data/control-results/`). Freezing the orchestration policy is how you get a
mythos-tier *decision* out of a lesser model without mythos-tier weights.

## The three moves

```
capture   run the benchmark with a real driver and policy capture on:
            TIER_BENCH_DRIVER=claude-fable-5 TIER_BENCH_CAPTURE_POLICY=1 \
              python orchestrator.py --benchmark all
          every driver_repair run appends one DecisionRecord to
          driver_decisions.jsonl (the driver's judgment, not its output).

freeze    python scripts/freeze_policy.py v1
          aggregates the log into an IMMUTABLE snapshot driver/policy/v1/
          (only plans that PASSED become policy; support counts how many
          passing runs back each entry). Do this while the driver is still
          reachable — the window closes when its access lapses.

resolve   from harness.driver_policy import FrozenPolicy
          plan = FrozenPolicy("v1").resolve({"tier": "T3", "strategy": "driver_repair"})
          returns the plan the driver would have used, for a cheaper model to
          follow. No match -> None: no snapshot, no guess.
```

Prove the loop offline (no keys): `python harness/driver_policy.py --selftest`.

## The law (same as identity/scg/releases/)

A frozen snapshot is **immutable**. `freeze()` refuses to overwrite an existing
version; a change is a **new version**, never an edit in place. Each `vN/` holds
`policy.json` plus a `manifest.json` with the source counts, the drivers it came
from, and a `policy_sha256`. That provenance is what lets a snapshot be trusted a
year later: you can see exactly which decisions, from which driver, produced it.

## What a policy entry is

```json
"{\"strategy\":\"driver_repair\",\"tier\":\"T3\"}": {
  "signature": {"tier": "T3", "strategy": "driver_repair"},
  "plan": ["draft with hands (claude-haiku-4-5)", "verify against the task's validators",
           "on failure, repair with driver (claude-fable-5)"],
  "verify": ["task validators"],
  "escalate_when": "hands attempt fails validation",
  "support": 6,
  "from_drivers": ["claude-fable-5"]
}
```

The signature is deliberately coarse to start (tier + strategy). Enrich it — add
the validator set, the file kinds, the size bucket — to make the policy
discriminate finer between task classes as you gather more decisions. The
signature's lists are treated as **sets** (order-independent), so the same class
always resolves to the same entry.

## Honesty seam

`resolve()` returns `None` for a task class the policy has never seen — the
caller falls back to a live driver (if one is reachable) rather than fabricating a
plan. A snapshot never pretends to cover work it wasn't trained on, and only
plans that actually passed ever enter it. A failed cheap attempt is evidence, but
it is not judgment worth replaying.
