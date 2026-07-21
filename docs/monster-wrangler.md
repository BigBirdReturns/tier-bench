# Tier Desk

Tier Desk is the local-first estate dashboard and control desk for `tier run`.
Its dashboard reads Claude and Codex subscription windows directly from their
installed CLIs, inventories local Git projects and open queue work, and makes
source freshness or collector failure visible. Its work view starts with
ordinary-language intent. The desk proposes a bounded project scope, an
existing repository proof command, and its normal worker lane in human-readable
terms; the operator then starts the work or keeps it as a draft. Technical
wiring remains inspectable and editable under progressive disclosure. The
browser may close while the desk retains durable run logs, patches,
verification results, and receipts.

It is intentionally a thin control plane over the existing referee contract. It
does not hold provider credentials, call provider APIs directly, apply patches,
merge branches, or treat model narration as completion. Every model invocation
remains inside the backend adapter named by the repository's committed
`pilot_backends.json`.

## Institutional model: the newsroom

`docs/newsroom.md` and `newsroom.json` classify the system as a publisher-gated
newsroom staffed by durable Octopode roles. The metaphor is an authority model,
not a persona layer. An Octopode persists through a repository-custodied role
charter, beat, source policy, authority ceiling, decision history, and receipts.
Its model or tool lanes are disposable.

The newsroom separates observation, analysis, validation, execution, and
publication. Tier Desk currently implements the local action plane. Its task
states remain `DRAFT`, `QUEUED`, `RUNNING`, and the terminal receipt states. The
human operator, acting as publisher, is the only actor who may move a Draft into
the queue. The production desk may execute only previously authorized work, and
the referee alone supplies acceptance or rejection.

External Chair returns, dashboard observations, future security scanners, and
other standing beats belong to observation or analysis. They may create an
observation or approval-gated Draft through trusted local admission. They may
not queue, execute, validate, merge, or publish. The newsroom manifest is
`REVIEW_ONLY`; no production module imports it, and the standing editions and
correction dependency graph are not yet implemented.

## Start it

Install the repository in editable mode, then start a detached desk for the
repository you want it to manage:

```console
python -m pip install -e .
tierdesk --repo C:\path\to\repo --daemon
```

The same command is available under the main CLI:

```console
tier desk --repo C:\path\to\repo --daemon
```

The command prints the local URL and server log path only after the detached
process returns a matching instance health receipt. The default bind is
`127.0.0.1:8765`; the browser may close without stopping the scheduler.

Inspect or stop the detached process:

```console
tierdesk --repo C:\path\to\repo --status
tierdesk --repo C:\path\to\repo --stop
```

Foreground mode is useful during setup:

```console
tierdesk --repo C:\path\to\repo
```

## What one work item contains

A normal operator does not author this packet field by field.
`POST /api/intake/plan` derives a reviewable proposal from the stated outcome,
the committed top-level project structure, and an existing project test entry
point. It fails closed when it cannot find a trustworthy proof command. The UI
explains why each boundary was selected and exposes the raw fields only under
**Change technical details**.

A work item freezes the following operator-controlled envelope before any model
call:

- a task statement and human-readable title;
- one or more allowed repository file or directory scopes;
- the acceptance command that judges the candidate outside the model;
- the backend manifest path and an arm proven to exist in that manifest's
  committed `HEAD` blob;
- priority, optional dependencies, and an optional approval gate.

A queued item is claimable only when every dependency has an `ACCEPTED` receipt.
Each attempt writes a bounded JSON run envelope, launches a fresh supervised
`tier run --envelope` subprocess with an explicit output directory, and keeps
task and acceptance text out of the operating-system command line. Monster
Wrangler then invokes `tier verify` over that directory before adopting the
terminal state. Late success cannot overwrite an operator cancellation because
both the run and task transition only from `RUNNING`.

The desk stores its scheduler database, event ledger, logs, and run directories
under the repository's common Git directory:

```text
.git/tier-desk/
  desk.sqlite3
  desk.pid.json
  server.log
  logs/<task-id>/attempt-###.log
  logs/<task-id>/attempt-###.envelope.json

.git/tier-runs/monster-wrangler/
  <task-id>/attempt-###/
```

The operator checkout is not used as a state database and is not modified by the
desk.

## Unattended-work controls

The defaults are intentionally conservative:

- one concurrent worker;
- no more than eight attempted runs per UTC day;
- pause after any `REJECTED` or `ERROR` result;
- an observed-cost stop at USD 10 per UTC day;
- loopback-only HTTP binding;
- an emergency stop that pauses scheduling and terminates active child
  processes.

The run-count limit is the reliable pre-dispatch bound. The cost limit uses
telemetry already written to receipts and cannot predict undisclosed
subscription-window headroom. A zero cost limit disables only the observed-cost
stop, not the daily run limit. On Windows, Desk-launched workers, tier-run
children, provider adapters, CLI probes, and planner calls run with
`CREATE_NO_WINDOW`; supervised processes combine that flag with
`CREATE_NEW_PROCESS_GROUP` so tree cancellation does not punch a console window
through the operator's focus layer.

## Security boundary

Tier Desk serves one self-contained page and has no third-party JavaScript or
remote assets. The dashboard is the default route; the work graph remains a
separate view. Theme preference is device-local under `tier-desk-theme`, applies
before first paint, and falls back to the operating-system color scheme.
Mutating HTTP requests require an unpredictable per-process token embedded in
the locally served page. Security headers deny framing, caching, cross-origin
connections, and MIME sniffing. Requests with an unexpected `Host` header are
rejected to close the usual loopback DNS-rebinding path.

The dashboard's Claude gauge runs the built-in `/usage` command in print mode
with a near-zero budget and verifies the response contains usage windows; the
observed path uses zero model tokens. The Codex gauge speaks JSON-RPC to
`codex app-server` and reads `account/rateLimits/read`, including separately
named buckets such as Spark. Both adapters cache readings, retain their exact
source labels and observation times, and return a visible failure instead of
substituting local estimates. The estate view discovers repositories below
`TIER_DESK_ESTATE_ROOTS` (an `os.pathsep`-separated override) or the enclosing
`Projects` directory, then reads branch, dirty paths, worktrees, last commit,
and active `docs/agents/QUEUE.md` rows by the table's named `state` column. Its
per-command `safe.directory` trust is scoped to the exact repository and never
changes global Git configuration. Observer commands are sequential and use
`CREATE_NO_WINDOW` on Windows. Estate data is cached for fifteen minutes,
concurrent forced refreshes coalesce into one collection, and no scheduler or
dashboard timer refreshes it. The explicit dashboard button is the only forced
refresh. The work-state poll caches cartridge identity for sixty seconds, so it
does not spawn Git on every request. Stopping the desk cancels discovery between
repositories and waits for an active observer collection to finish or time out
and reap its child.

The Chair Inbox is intake only. A valid return consumes one preregistered request
and creates an approval-gated Draft with the immutable custody tuple and complete
changed-file set. It cannot wake scheduling, invoke a model, execute acceptance,
checkout the pull request, or claim that the pull request was validated. The
Draft must be reviewed as an external submission, and it should not be armed as
if it were an acquired immutable subject.

Binding to a non-loopback address is refused unless `--unsafe-network` is
supplied. That flag only permits the bind; it does not add user authentication
or TLS. The supported unattended configuration is a loopback-bound process used
from the same machine.

The acceptance command is trusted operator input and is executed by `tier run`
in the disposable candidate worktree. It should be a deterministic verifier,
not an author or deployment command.

## Failure behavior

A task is never marked accepted because a child process exited successfully or
because a model claimed success. Missing receipts, unreadable receipts, failed
`tier verify`, missing telemetry, scope violations, rejected acceptance, and
backend errors remain visible as terminal evidence states. With the default
guardrail, any rejection or error pauses new dispatches until the operator
reviews and resumes the scheduler.

A desk process that restarts while a task is marked `RUNNING` records the
attempt and task as `INTERRUPTED`. It does not silently retry. Every live
dispatch is supervised by a heartbeat worker bound to the exact desk instance;
if the desk stops updating its heartbeat, or a replacement desk takes ownership,
the old worker terminates the `tier run` process tree instead of allowing a
detached model call to continue consuming quota. The operator can inspect the
preserved run directory and explicitly retry the work item.

The verified-yield display uses only adjudicated `ACCEPTED` and `REJECTED`
attempts. Transport and infrastructure `ERROR` rows remain visible and count
against run and observed-cost controls, but they do not contaminate the
capability denominator.

## Current boundary

The Monster Wrangler execution plane still manages one selected repository and
uses the arms already frozen in `pilot_backends.json`. Tier Desk now observes
the wider local estate and live subscription tank state, but it does not yet use
those readings for automatic admission or cartridge selection, synchronize with
Beads or Gas Town, or apply accepted patches. Those integrations can consume the
desk's task, gauge, estate, and receipt state without changing the referee
semantics.

The newsroom role registry, epistemic state machine, three standing editions,
correction dependency tracing, read-only security beats, portable attestations,
and evidence browser remain review or prototype work. Their first acceptable
form must be a deterministic read-only projection. No observer or external
submission may acquire execution or publication authority through that work.
