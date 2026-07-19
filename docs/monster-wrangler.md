# Monster Wrangler

Monster Wrangler is the repository-custodied operator application for controlled,
resumable agent work. It provides a local browser interface and a persistent
scheduler above the existing `tier run` referee. The application stores task
state, dependencies, approvals, route policy, quota observations, process state,
and a hash-chained event ledger. Every model invocation remains delegated to a
committed backend manifest, and every task verdict remains delegated to the
runner's receipt and verifier.

The browser is a client of that control plane. Closing the browser does not stop
the daemon or discard work. Stopping the daemon marks any unsettled run
`INTERRUPTED`, preserving the existing run directory and requiring an explicit
operator retry.

## Product boundary

Monster Wrangler owns the following local control semantics:

- durable task envelopes with frozen instructions, file scope, and acceptance;
- dependency readiness, scheduling, priority, approval gates, and atomic claims;
- ordered execution routes with explicit capability and quota evidence labels;
- quota tanks with freshness windows, operator caps, and reset observations;
- bounded concurrency, daily run, cost, and token limits;
- controlled retry or route escalation according to each task's frozen policy;
- process cancellation, global pause, emergency stop, and restart recovery;
- collection of logs, patches, receipts, token use, cost, and verification output;
- a hash-chained control-event ledger and an exportable state snapshot.

Monster Wrangler does not hold provider credentials, emulate vendor clients,
change a backend manifest, decide that a model's narration constitutes success,
apply a patch, merge a branch, or alter a grader. The executable cartridge is the
manifest-selected adapter invoked by `tier run`. The authoritative verdict is the
emitted `receipt.json` after `tier verify` reopens its bindings.

## Install and start

Install the repository in editable mode:

```console
python -m pip install -e .
```

Start the Desk for a target Git repository and leave it running after the shell
returns:

```console
tierdesk --repo C:\path\to\repository --daemon
```

The same application is available through the existing command surface:

```console
tier desk --repo C:\path\to\repository --daemon
```

The default address is `http://127.0.0.1:8765/`. The detached process writes its
PID, process lock, database, and server log under the repository's common Git
directory at `.git/tier-desk/`. The detached launcher returns only after the
child has bound its socket and published a PID record tied to the process
creation identity. Browser closure has no effect on that process.

Inspect or stop the detached process:

```console
tierdesk --repo C:\path\to\repository --status
tierdesk --repo C:\path\to\repository --stop
```

Run in the foreground without opening a browser:

```console
tierdesk --repo C:\path\to\repository --no-open
```

The server binds only to loopback unless `--unsafe-network` is supplied. Remote
binding exposes an operator-control surface and should be placed behind an
appropriate authenticated transport. The built-in request token and origin
checks protect the local browser session; they are not a substitute for a remote
identity layer.

## Storage and custody

Control state and run evidence use different roots:

```text
.git/tier-desk/monster-wrangler.sqlite3
.git/tier-desk/monster-wrangler.lock
.git/tier-desk/monster-wrangler.pid.json
.git/tier-desk/server.log
.git/tier-runs/monster-wrangler/<task>/<attempt>/
```

This separation is required by the existing runner. Arbitrary output beneath the
common Git directory is refused, while `.git/tier-runs/` is the registered
receipt root. Each task evidence folder contains immutable attempt directories and sibling
`*.desk.log` files. The control log stays outside the attempt directory so
`tier run` receives an empty authoritative output directory. The operator
checkout remains unchanged.

SQLite uses write-ahead logging and an immediate transaction for task claims.
Only one scheduler can hold the operating-system process lock for the configured
state directory. PID records include a process-start identity where the platform
exposes one, preventing a recycled process ID from becoming stop authority.
Tasks that were `RUNNING` when a new process opens the database become
`INTERRUPTED`; the application never pretends that an abandoned process settled
its referee.

## Define work

A task envelope contains:

- a stable ID and title;
- complete task instructions;
- one or more repository-relative file or directory scopes;
- an operator-supplied acceptance command;
- zero or more predecessor task IDs;
- priority and an optional timezone-qualified schedule;
- an approval requirement;
- an attempt ceiling and escalation rule;
- one or more ordered routes.

The application accepts only backend manifests that exist as committed blobs at
the target repository's current `HEAD`. It also confirms that the selected arm
exists in the committed manifest before the task can be stored. The runner later
performs its complete manifest, prompt-template, adapter, and Git-object
validation at dispatch time.

A task can be created in `DRAFT` or `QUEUED`. Approval-required work remains in
`DRAFT` until the operator approves it. A queued task becomes ready only when its
schedule has arrived, every dependency is `ACCEPTED`, an attempt remains, and at
least one remaining route is eligible.

## Routes and escalation

A route identifies a committed backend manifest and one of its `arm_a`, `arm_b`,
or `arm_c` entries. It also records:

- a human-readable label;
- an optional quota tank;
- `measured`, `hypothesis`, or `unmeasured` capability basis;
- `direct`, `derived`, `operator`, or `unknown` quota basis;
- an optional estimated maximum call cost.

These fields preserve evidence classification in the control record. They do not
convert a declaration into a measurement. The application does not infer a
capability waterline from a model name.

Routes are ordered. Attempt one begins at route one. A later explicit retry begins
at the next route. A task may authorize either of two unattended escalation laws:

- `next-route-on-error` advances only after an infrastructure or receipt error;
- `next-route-on-failure` advances after either `ERROR` or `REJECTED`.

The default is operator review. No task can exceed its frozen `max_attempts`.
Automatic escalation runs before the global `stop_on_failure` policy is applied.
When no authorized escalation remains, a rejected or errored task pauses the
scheduler if that global policy is enabled.

## Quota tanks

A tank represents a separately governed resource, such as a subscription window,
an API budget, a local runtime, or another manually observed capacity pool. A
non-local tank records headroom remaining, observation time, maximum snapshot
age, reset time, and a used-percentage cap.

For example, a tank with 26 percent headroom has 74 percent used. If its hard cap
is 80 percent, the route remains eligible until used capacity reaches 80 percent.
At or beyond the cap, the route parks. A missing snapshot, stale snapshot,
disabled tank, or reset that occurred after the observation also parks the route.
The scheduler never represents those conditions as current headroom.

Local tanks are eligible whenever they are enabled because no remote quota
observation is required. A route may also omit a tank gate, but that is an
explicit choice in the frozen task envelope rather than an inferred default.

## Budget policy

The Settings view controls:

- maximum concurrent workers, from one through eight;
- daily run ceiling;
- daily recorded cost ceiling;
- daily recorded token ceiling;
- the IANA timezone used to define the daily budget window;
- scheduler polling interval;
- pause-on-terminal-failure behavior.

A cost or token ceiling of zero disables that particular limit. The task ceiling
always remains active. These controls rely on posted run telemetry, so provider
limits and billing records remain authoritative. The application stops launching
new work once a local ceiling is reached; it does not terminate an already
running call merely because that call later crosses a recorded aggregate limit.

## Evidence and outcomes

A worker process is launched as an argument vector equivalent to:

```console
python -m tier_runner.cli run \
  --repo <repo> \
  --task-id <task-id> \
  --task-file <control-owned-task-file> \
  --files-file <control-owned-scope-file> \
  --acceptance-file <control-owned-acceptance-file> \
  --backend-manifest <committed-manifest> \
  --arm <selected-arm> \
  --output-dir <.git/tier-runs/monster-wrangler/...>
```

The temporary invocation files live beside, rather than inside, the attempt
folder and are deleted after process launch completes. This avoids command-line
length limits while preserving an empty authoritative run directory.

After the child exits, Monster Wrangler reads `receipt.json`, independently runs
`tier verify --run-dir <attempt>`, and records the run as `ACCEPTED`, `REJECTED`,
or `ERROR`. Missing receipts, unreadable receipts, invalid states, or failed
verification become `ERROR`. Process exit alone does not close work.

The Evidence view exposes the Desk log, receipt, and patch for each latest
attempt. Patch downloads are inspection artifacts only. Applying or merging an
accepted patch remains an explicit action outside this application.

Every task, settings, tank, claim, completion, escalation, cancellation, and
recovery transition appends an event whose hash binds its content and the
preceding event hash. `/healthz` returns an error if that chain no longer opens.
`/api/export` produces a JSON snapshot containing the current task graph, tank
state, registry summary, event ledger, and custody paths.

## Emergency behavior

Pause prevents new claims but leaves active processes running. Emergency stop
pauses scheduling, terminates every process currently owned by the application,
and marks those tasks `CANCELED`. Ordinary task cancellation applies the same
process-control path to one run.

A normal daemon stop also terminates owned child processes. On the next start,
any database row still marked `RUNNING` becomes `INTERRUPTED`. This conservative
recovery avoids adopting an orphaned model process or accepting evidence whose
process custody is uncertain.

## Full application path

This release establishes the operational spine rather than a throwaway demo. It
already performs durable graph scheduling, approval and budget governance,
manifest-based cartridge execution, quota-aware routing, restart recovery, and
receipt-backed adjudication through a usable local interface.

The remaining product layers are additive clients and adapters over these stored
contracts. They include authoritative provider-window collectors where vendors
expose suitable interfaces, Beads or Gas Town scheduling projections, desktop
packaging and notifications, multi-repository workspaces, reusable task-envelope
templates, and richer accepted-patch review. None of those layers should acquire
the authority to rewrite a frozen task, acceptance predicate, route history, or
terminal referee verdict.

## Deterministic test

The repository test performs no model calls:

```console
python tests/test_monster_wrangler.py
```

It covers control/evidence path separation, dependency and approval gates, tank
cap and staleness refusal, ordered escalation, pause-on-failure, restart recovery,
committed-manifest enforcement, event-chain tamper detection, HTTP token refusal,
manifest/model catalog discovery, file-backed process envelopes, failed-launch
cleanup, settled-state immutability, single-process locking, PID identity checks,
and detached start, readiness, status, and stop behavior.
