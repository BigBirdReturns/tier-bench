# Frontier Residue Refinery resource lanes

Monster Wrangler's worker limit controls total concurrency. Residue resource lanes add a second, narrower admission rule for scarce hardware and provider allotments.

A route may declare:

```json
{
  "resource_key": "gpu:3090",
  "max_concurrency": 1
}
```

Campaigns that share `gpu:3090` will not run that route concurrently, even when the Desk has several free workers. A route using `gpu:4060` remains independently eligible. The same mechanism can protect subscription and API lanes:

```text
gpu:3090

gpu:4060

subscription:kimi-code

subscription:claude-code

api:moonshot-payg
```

The key is an operator-declared physical or commercial resource identity. It is not inferred from company branding. Several cartridges that contend for the same card should use the same key. Distinct hosts or provider accounts may use distinct keys when they are genuinely independent.

`max_concurrency` defaults to one. When several route declarations share a key but disagree about its capacity, the lane uses the smallest declared limit. This fails toward serialization rather than accidental oversubscription.

Local routes without an explicit key receive a conservative default derived from their committed model binding. Explicit physical keys are preferred on multi-GPU systems because two models may still contend for the same card.

Resource-lane state is persisted beside the campaign in the Desk database. The controller counts `DRAFT`, `QUEUED`, and `RUNNING` trial tasks as occupying the lane. When capacity is unavailable, the campaign remains active and waits for a later scheduler tick. Waiting does not consume a trial, create a failure, or buy escalation.

Resource declarations travel into campaign and residue-candidate projections. They therefore remain visible when a later frontier success is evaluated for capture. A result cannot silently omit that the local path was serialized on one 3090 while the remote path used a separate subscription window.

The lane is an admission guard, not a provider quota oracle. Rolling token windows, rate-limit resets, and account-specific usage still require backend telemetry or an explicit quota gauge. A subscription route can nevertheless be capped at one concurrent trial and bounded by campaign-level remote-trial and dollar limits.
