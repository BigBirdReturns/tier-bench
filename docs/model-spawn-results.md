# Driver Takeover Notes

Date: 2026-07-07

This replaces the earlier "model spawn results" note. That note treated spawned sub-agent self-reports as meaningful evidence, which conflicts with Tier Bench's core rule: model self-report is not measurement. The repository's docs define the job differently.

## What the docs say the job is

Tier Bench is an empirical routing and replication system for LLMs. Its job is to turn model claims into deterministic measurements: run tiered tasks, validate them objectively, compute success and cost, and route work based on measured cost-per-success rather than reputation.

The driver role is also explicit: the driver should decompose work, verify validator output, and repair from evidence. It should not spend scarce judgment tokens typing first drafts when cheaper hands can do the bulk work.

## Corrections to the earlier result

| Earlier claim | Correction |
| --- | --- |
| Spawning sub-agents and recording their descriptions was a useful result. | It was only a session-level smoke test. It is not benchmark evidence and should not be treated as a model comparison. |
| A sub-agent identifying as a model name proves the requested override. | It does not. The docs warn that no model self-report outranks deterministic validators. |
| Unsupported spawn failures are enough to characterize model availability. | They are only local runtime failures for this Codex account/session, not Tier Bench registry or provider measurements. |

## Actual evidence standard to use next

1. Read the driver role and repo mission before making model claims.
2. Treat model names, prices, tier ceilings, roles, and composites as registry data in `models.json`.
3. Use the harness and validators for any pass/fail or cost-per-success claim.
4. Label unmeasured claims as hypotheses, never as results.
5. Use failed attempts as evidence for repair or future distillation instead of discarding them.

## Docs read for this correction

I inventoried and read the repository Markdown docs, including the top-level README, CLAUDE guide, HANDOFF, CONTRIBUTING guide, driver docs, MCP docs, memory docs, capability harness docs, data/result docs, and experiment docs. The correction above is grounded in the repeated repository doctrine: measured below the deterministic ruler, audited or labeled above it, and never replaced by model self-report.
