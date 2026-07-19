# Monster Wrangler

Monster Wrangler is the local-first control desk for `tier run`. It lets an operator define bounded repository work, freeze acceptance before dispatch, express dependencies, leave the browser, and return to durable run logs, patches, verification results, and receipts.

It is intentionally a thin control plane over the existing referee contract. It does not hold provider credentials, call provider APIs directly, apply patches, merge branches, or treat model narration as completion. Every model invocation remains inside the backend adapter named by the repository's committed `pilot_backends.json`.

## Start it

Install the repository in editable mode, then start a detached desk for the repository you want it to manage:

```console
python -m pip install -e .
tierdesk --repo C:\path\to\repo --daemon
```

The same command is available under the main CLI:

```console
tier desk --repo C:\path\to\repo --daemon
```

The command prints the local URL and server log path. The default bind is `127.0.0.1:8765`; the browser may close without stopping the scheduler.

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

A work item freezes the following operator-controlled envelope before any model call:

- a task statement and human-readable title;
- one or more allowed repository file or directory scopes;
- the acceptance command that judges the candidate outside the model;
- the committed backend manifest and selected arm;
- priority, optional dependencies, and an optional approval gate.

A queued item is claimable only when every dependency has an `ACCEPTED` receipt. Each attempt writes a bounded JSON run envelope, launches a fresh supervised `tier run --envelope` subprocess with an explicit output directory, and keeps task and acceptance text out of the operating-system command line. Monster Wrangler then invokes `tier verify` over that directory before adopting the terminal state.

The desk stores its scheduler database, event ledger, logs, and run directories under the repository's common Git directory:

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

The operator checkout is not used as a state database and is not modified by the desk.

## Unattended-work controls

The defaults are intentionally conservative:

- one concurrent worker;
- no more than eight attempted runs per UTC day;
- pause after any `REJECTED` or `ERROR` result;
- an observed-cost stop at USD 10 per UTC day;
- loopback-only HTTP binding;
- an emergency stop that pauses scheduling and terminates active child processes.

The run-count limit is the reliable pre-dispatch bound. The cost limit uses telemetry already written to receipts and cannot predict undisclosed subscription-window headroom. A zero cost limit disables only the observed-cost stop, not the daily run limit.

## Security boundary

Monster Wrangler serves one self-contained page and has no third-party JavaScript or remote assets. Mutating HTTP requests require an unpredictable per-process token embedded in the locally served page. Security headers deny framing, caching, cross-origin connections, and MIME sniffing.

Binding to a non-loopback address is refused unless `--unsafe-network` is supplied. That flag only permits the bind; it does not add user authentication or TLS. The supported unattended configuration is a loopback-bound process used from the same machine.

The acceptance command is trusted operator input and is executed by `tier run` in the disposable candidate worktree. It should be a deterministic verifier, not an author or deployment command.

## Failure behavior

A task is never marked accepted because a child process exited successfully or because a model claimed success. Missing receipts, unreadable receipts, failed `tier verify`, missing telemetry, scope violations, rejected acceptance, and backend errors remain visible as terminal evidence states. With the default guardrail, any rejection or error pauses new dispatches until the operator reviews and resumes the scheduler.

A desk process that restarts while a task is marked `RUNNING` records the attempt and task as `INTERRUPTED`. It does not silently retry. Every live dispatch is supervised by a heartbeat worker; if the desk stops updating its heartbeat, the worker terminates the `tier run` process tree instead of allowing a detached model call to continue consuming quota. The operator can inspect the preserved run directory and explicitly retry the work item.

## Current boundary

This first vertical slice manages one repository and uses the arms already frozen in `pilot_backends.json`. It does not yet discover live subscription tank state, perform evidence-backed automatic cartridge selection, synchronize with Beads or Gas Town, or apply accepted patches. Those integrations can consume the desk's task and receipt state without changing the referee semantics.
