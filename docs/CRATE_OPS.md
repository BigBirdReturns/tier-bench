# CRATE OPS — the operating manual for making tokens last days

Status: doctrine distilled from measured receipts (lesson 18; CLAUDE-SENTINEL-1;
CLAUDE-CRATE-PILOT-1/-2). This is how sessions run now. The old pattern — one
long frontier session that reads everything, does everything, and pays rent on
its own history every turn — burned ~$700/day equivalent, 92% of it cache-read
rent. The pattern below does the same day of work for single-digit dollars.

## The inversion

**Work lives in files. A session is a visit.** No session is ever the custodian
of state; the repo is. Every session starts from pointers, ends with a receipt,
and dies without regret.

## Roles (measured, not aspirational)

| role | who | spends | does |
|---|---|---|---|
| driver | fable/opus, SHORT sessions | judgment tokens only | author crates + referees, adjudicate, route |
| hand | haiku (`claude -p`), spark/terra (`codex exec`), local ollama | bulk tokens, cheap or $0 | implement from crate pointers, one attempt |
| referee | deterministic scripts | nothing, forever | the only pass criterion |
| auditor | sol/luna (other lineage) | the OTHER quota | refute receipts before they're believed |
| operator | human | attention | GATED acts: caps, freezes, merges, admissions |

## The routing law (from pilots 1–2)

- **Small task (T0–T1, fits one prompt): payload-inline to a CHEAP tenant.**
  Crate overhead loses below S* — measured 13.9k tenant vs 18.5–21.9k crate at
  T1. Don't crate what a $0.07 haiku call solves inline.
- **Anything bigger, multi-phase, or resumable: crate it.** Cards + frozen
  referee, pointer-only hand dispatch, receipt.
- **Frontier models never do bulk.** Fable reads cards and receipts, not code
  dumps, not transcripts, not search results. Delegate every bulk read.
- **Cross-vendor arbitrage**: hands and audits on the ChatGPT quota, judgment
  on the Claude quota (or invert when one window is parked). Two tanks, one
  car. Local ollama = free third tank for T0/T1 bulk.

## The daily loop

1. **Morning driver visit (~$1–2, minutes):** open a session with the ENTRY
   PROMPT below. Read QUEUE rows + newest 700.100 receipts ONLY. Write or
   refresh crates and referees for the day's work. Dispatch hands headless in
   background. Close the session. Do not linger.
2. **Hands run unattended:** `claude -p --model haiku` / `codex exec -m
   gpt-5.3-codex-spark` per crate, logs captured, referees judge on completion.
3. **Evening driver visit (~$1–2):** fresh session, read receipts only.
   Failures escalate one tier (one attempt per tier, never retry the same
   tier). Write next crates. Leave a receipt. Close.
4. **The sentinel enforces the exit:** WARN tier = write the handoff crate NOW
   and end the session. Not advisory — the hard cap denies tools.

## ENTRY PROMPT (paste to start every driver session)

    You are a crate-resident driver session, not a tenant. Rules:
    read ONLY docs/CRATE_OPS.md, your rows in docs/agents/QUEUE.md, and the
    700.100.RECEIPT.md of crates you are continuing — never conversation
    history, never bulk files (delegate reads to subagents). Author crates and
    frozen referees, dispatch cheap hands headless, adjudicate receipts,
    escalate failures one tier. End at sentinel WARN with a receipt and the
    next crate written. Your session is disposable; the repo is not.

## INTERACTIVE DRIVER (the desk, not the workshop)

A long-lived chat session is allowed — talk accumulates at human speed and
rent on pure talk is pocket change. What is forbidden is bulk entering the
chat context: file dumps, logs, search results, tool sprawl. The chat is a
desk where decisions are made, not a workshop where work happens.

Paste to start an interactive driver session:

    Read docs/CRATE_OPS.md and operate as the INTERACTIVE driver: converse
    normally, but never pull bulk into this context. Any work beyond 2-3
    trivial tool calls: write a crate (scripts/crate_new.py), freeze a
    referee, dispatch a hand headless (scripts/dispatch.py or claude -p /
    codex exec in background), and report back from the receipt — never
    paste transcripts or file bodies here. Delegate all bulk reads to
    subagents that return conclusions. Adjudicate receipts, escalate
    failures one tier, commit deliverables with receipts. The sentinel
    meters this session; treat NOTICE as a design failure, not a warning.

**Spend the savings on thinking.** Drivers run at HIGH reasoning effort —
thinking tokens are stripped from later turns, so they never become rent;
bulk does. A deep think costs once; a pasted file body bills again on every
subsequent turn for the life of the session. So the trade is asymmetric: buy
judgment, not residency. The desk guard (in `session_sentinel.py`) enforces
the residency half mechanically — big or accumulating tool results inject a
delegate-it warning — while the effort dial is where the freed budget goes.

Measurement: the session's sidecar in `experiments/breadth/run/.sentinel_state/`
is the growth curve (`cost_usd`, `offset` = transcript bytes); read it with
`python scripts/burn_report.py`. Control arm for comparison: the 2026-07-18
driver session that authored this file — $32+ / ~1.6 MB / ~$0.30 per message,
dominated by cache-read rent on its own tool output. Success: cost per message
stays flat and total stays ~$1-2 across a comparable day of shipped, receipted
work. Failure is equally informative — commit the curve either way.

## Tooling backlog (each item = one crate, built by hands, NOT by a driver)

- [x] `scripts/crate_new.py` (built by spark hand via dispatch.py, 2026-07-18) — scaffold index/task/acceptance/receipt from
      template (templates: `experiments/breadth/crates/*_v1/`)
- [x] `scripts/dispatch.py` (built by haiku hand, $0.088, 2026-07-18) — run hand M on crate C headless, capture log,
      meter (sidecar/`--output-format json`/`tokens used`), run referee,
      append receipt row; `--escalate` for the tier ladder
- [x] dispatch.py: fix Windows cp1252 log-capture decode (fixed by haiku hand via dispatch_fix_v1 crate, $0.090, 2026-07-18; capture now encoding='utf-8', errors='replace' — pre-fix the decode error killed the reader thread, stdout came back None, and dispatch crashed with no receipt row at all)
- [x] desk guard (built by hand via desk_guard_v1 crate, 2026-07-18) — sentinel
      extension metering tool-result BULK in the chat context: single results
      > `TIER_SENTINEL_BULK_SINGLE` (2000 proxy tokens) and each multiple of
      `TIER_SENTINEL_BULK_TOTAL` (20000) inject a delegate-per-CRATE_OPS
      warning on PostToolUse; sidecar tracks `bulk_tokens` / `bulk_biggest_single`
- [x] sentinel lifted to user-level settings (staged + 17/17 referee via
      sentinel_userlevel_v1 haiku hand, 2026-07-18; APPLY is a gated operator
      copy — see the crate's staged/APPLY.md)
- [x] `burn_report` fed from both vendors' logs (burn_two_vendors_v1,
      2026-07-18: haiku built the parser but priced openai at $1.0M — missing
      per-1M divisor, caught at desk, sonnet repaired; anthropic $25/26
      sessions, openai $188/40 sessions)
- [~] S* crossover experiment — first bracket measured (amortization_v1 +
      LESSONS 19: above three-T1-per-visit on dollars at fable rates; the
      cheap-hand arm and larger-N remain unmeasured; CRATE-CROSSOVER-1 full
      form still open)
- [x] dispatch.py: referee timeout flag (`--referee-timeout`, default 600s,
      TIMEOUT sentinel in receipts; payload-inline haiku, $0.057, 2026-07-18 —
      closed the false FAIL the 120s hard-cap put on admin_question_test_v1)

## The arithmetic (why this stretches days into weeks)

Old: driver-tenant, ~$700/day equivalent, window gone in hours.
New: 2–3 driver visits (~$5) + 20 hand dispatches (~$1–2, half on the other
vendor's quota, T0/T1 locally at $0) + free referees ≈ **$6–8/day equivalent,
with the Claude window touched only for judgment.** That is a 100x stretch on
the binding quota — the difference between a window lasting an afternoon and
lasting its full cycle.
