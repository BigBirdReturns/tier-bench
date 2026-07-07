# tier-bench persona A/B — an MCP server

Expose every model **and** every driver-composite as a swappable **persona**,
then A/B them — including a cheap composite *impersonating* a frontier model —
from any MCP client, in your real workflow. It answers the question this whole
repo exists to ask, live instead of in a benchmark run: **can the $0.03
composite pass for the $0.50 model on my actual work?**

Standard library only — no `pip install`, in keeping with the repo's zero-dep tools.

## What a persona is

| kind | is | `complete(prompt)` does |
|---|---|---|
| **model** | one entry in `models.json` | one API call |
| **driver** | one `driver_repair` composite (e.g. `driver:fable+haiku`) | cheap **hands** model drafts → frontier **driver** model **reviews** (replies `PASS`, or the fix) |

The driver persona is the point. When the cheap draft is good, the frontier
model only **reads** it — a short `PASS` — instead of regenerating the whole
answer. Judgment tokens are cheaper than generation tokens, so the composite
can undercut the frontier **on substantial outputs**. Be honest about the flip
side: on a trivial one-liner the draft+review overhead can cost *more* than the
frontier just answering once. Which wins is a per-task question — that's what
the `ab` tool and `ab_log.jsonl` are for. (`cascade`/`best_of_n` composites are
validator-bound and stay benchmark-only; a raw chat prompt has no validator.)

## Tools

- **`list_personas`** — every model + live driver-composite, with backing and availability.
- **`complete(persona, prompt, [max_tokens])`** — run one. Returns `content`, `cost`, `final_model`, and a step `trace` (which model produced the answer, what each call cost).
- **`ab(prompt, a, b, [blind=true], [judge])`** — run two on the same prompt. Returned **blind** as `left`/`right` with names withheld (content-hash order, so position doesn't leak identity); pass `blind:false` to reveal the `mapping`. An optional `judge` persona picks `LEFT`/`RIGHT`. **Every duel is appended to `ab_log.jsonl`** — and the winner is recorded there even when the caller is kept blind. The log is the durable record.
- **`impersonate(alias, backing)`** — register an alias so one persona answers under another name. Register `driver:fable+haiku` as `frontier-x`, then `ab` it blind against the real frontier.

## The A/B → data loop

`ab_log.jsonl` is a running record of head-to-head duels from real use. It
promotes straight into the benchmark: a judged `ab` outcome is a
`(model, pass, cost)` observation for `data/results/`, and a control-set duel is
a disposition row for `data/control-results/`. So every A/B someone runs in
their own workflow becomes a data point the aggregators pool and the pages
render — the site stops *describing* the thesis and starts *scoring it live*.
(The promotion script is a deliberate next step, not yet wired — see the repo's
`HANDOFF.md`.)

## Keyless testing

No API keys? `TIER_BENCH_MOCK=1` swaps in a deterministic fake backend
(frontier personas cost more; the driver review deterministically hits both the
accept-the-draft and repair paths), so the whole protocol + persona logic + A/B
+ logging is provable offline. Mock costs are **illustrative, not a
measurement** — the real cost delta needs real keys.

```
TIER_BENCH_MOCK=1 python3 mcp/test_offline.py     # 22 checks
```

## Add it to an MCP client

`claude_desktop_config.json` (or any MCP client's config):

```json
{
  "mcpServers": {
    "tier-bench-personas": {
      "command": "python3",
      "args": ["/absolute/path/to/tier-bench/mcp/server.py"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

Set whichever provider keys your personas need (`OPENAI_API_KEY`,
`GEMINI_API_KEY`, …), or `TIER_BENCH_MOCK=1` to try the wiring with none. Then,
in the client: "list personas", "complete with `driver:fable+haiku`: <task>",
or "ab `claude-fable-5` vs `frontier-x`, judged by `claude-sonnet-4-5`."
