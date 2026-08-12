# Native private execution rail

A controller that executes private repository work on hardware we own, instead of
on a per-job GitHub-hosted runner. GitHub stays the canonical surface for source,
review and status. The rail owns queue, claims, execution, recovery and
settlement.

**The operative contract is v5.** v1 and v2 live under `historical/` and are not
invocable; v3 and v4 are retained as valid predecessor evidence, not as
contracts. Nothing outside the paths below should be reasoned from. See
[Superseded contracts](#superseded-contracts).

```text
controller   integrations/native-rail/tbrail.py           (v5)
envelopes    integrations/native-rail/envelopes-v3/       (envelope schema @3)
operations   integrations/native-rail/ops/ (rail scripts, digest-pinned)
             integrations/native-rail/repo-ops/ (accepted repository manifests)
profile      RUNNER-PROFILE.<host>.json   emitted per deployment, held PRIVATELY
             RUNNER-PROFILE.example.json  synthetic shape, public
qualifier    integrations/native-rail/cold_qualify.py
reproduction integrations/native-rail/run_proofs.sh
historical   integrations/native-rail/historical/          NOT CURRENT
```

A deployment's own runner profile and its path-bearing receipts name a host, an
account home and absolute controller paths. Those are private deployment
identity, so the public product carries their **exact digests** in
`EVIDENCE-INDEX.json` files and the bodies live in private holder custody. The
example profile is synthetic: it shows the shape, and every path and digest in
it is a placeholder.

## The layer law

The envelope is **closed data**. Issue text, PR prose, review comments and model
output never become argv. A phase names an operation id and typed parameters; the
controller builds the command.

This is enforced in three places, not asserted:

1. **A closed envelope schema.** Unknown top-level or phase fields are refused at
   submit. Identifiers, paths, resource keys, digests and timeouts all have
   grammars. Every derived path is resolved and proved to stay under its root.
2. **A typed operation registry.** `OPS` maps an operation id to a builder. The
   builder reads typed params and returns argv. There is no operation that takes
   a command, a script body, an interpreter switch or a shell string.
3. **An accepted repository-operation manifest.** Repository scripts are reached
   only through `repo.operation`, whose manifest fixes script path, script
   digest, argv template and a closed per-parameter grammar. The envelope may
   choose an operation id and typed values; it cannot name a script, a digest or
   a switch, and a value that looks like a switch is refused.

## What the sandbox enforces

Each phase runs under `bwrap --unshare-all --die-with-parent --new-session`:

- **Declared paths are the writable set.** Only the subtrees named in
  `allowed_paths` are bound writable. A nested subtree (`pkg/sub`) binds exactly
  that subtree; nothing above it is present.
- **Bind sources are resolved under the repository.** Each path component is
  checked; a symlink, reparse point or out-of-tree resolution is refused before
  bubblewrap is invoked, so source-controlled links cannot redirect a mount.
- **The workspace is mounted at a neutral guest path** (`/w`), never at its host
  path, so the controller's home does not exist inside the worker even as an
  empty parent stub.
- **No network.** `--unshare-all` includes the network namespace.
- **No credential.** The worker holds no GitHub token; source arrives as a
  digest-verified exact-SHA git bundle from an admitted custody root.

## Enforced ceilings

Ceilings are applied by the kernel or by an independent monitor. A phase may
lower any of them; it may never raise one.

Ceilings are applied by the kernel, by the cgroup, or by an independent monitor.
Each one is named by **the boundary that actually enforces it** — the distinction
between a per-process rlimit and an aggregate budget is load-bearing, and earlier
prose in this lane called per-process rlimits "phase" ceilings, which overstated
them.

| Ceiling | Scope | Enforced by | Default |
|---|---|---|---|
| processes | **aggregate** | cgroup `pids.max` | 512 |
| memory | **aggregate** | cgroup `memory.max` (+ `memory.swap.max=0`) | 4 GiB |
| CPU seconds | **aggregate** | monitor sampling cgroup `cpu.stat`, then `cgroup.kill` | 900 |
| workspace bytes | **aggregate** | monitor thread, then `cgroup.kill` | 8 GiB |
| output bytes | **aggregate** | streaming pump; the child is torn down, not merely truncated | 4 MiB |
| address space | per-process | `RLIMIT_AS` via `prlimit(1)` | 4 GiB |
| CPU seconds | per-process | `RLIMIT_CPU` via `prlimit(1)` | 900 |
| file size | per-process **only** | `RLIMIT_FSIZE` via `prlimit(1)` | 1 GiB |
| open files | per-process **only** | `RLIMIT_NOFILE` via `prlimit(1)` | 1024 |
| wall clock | phase | `timeout_seconds`, then teardown | 900 (max 1800) |

No aggregate file-size or descriptor budget is claimed. `resource_semantics` in
every receipt states this split verbatim.

### The launch chain

```
systemd-run --user --scope   aggregate cgroup ceilings
  -> supervisor (sh)         records the scope it landed in, then execs
    -> prlimit(1)            per-process rlimits
      -> bwrap               namespace isolation
        -> the operation
```

**The environment is constructed at both ends of that chain, never inherited.**
`systemd-run` executes in the *controller's* environment — it is the caller's own
process that talks to the user manager — so the whole chain used to inherit
whatever the controller held. It is now given an explicit minimum (`PATH`,
`LANG`, `HOME`, `USER`, and the runtime/bus address the user manager needs), and
`bwrap --clearenv` unsets everything again before the declared worker set is
applied. The operation's environment is therefore exactly the declared set, and
the qualification proves it by loading the controller with credential-shaped
sentinel variables and showing they are absent from the worker's environment and
from its raw `/proc/self/environ` bytes. v4 passed that witness only because the
controller happened to hold no tokens that day.

Nothing in this chain runs Python in the forked child of the controller.
`preexec_fn` is **not used**: its fork-time callback is unsafe in a multithreaded
process — and the controller is multithreaded, because the lease heartbeat runs
for the whole duration of a phase — so it could deadlock before `exec`. Every
ceiling it used to apply is now applied by an exec'd program instead.

The supervisor exists for one reason: it writes the scope's cgroup path **before
it execs**, so "aggregate enforcement actually started" is a durable artifact
rather than something the controller infers by winning a polling race. A phase
that never entered its scope is refused outright, because a score earned outside
the boundary the receipt claims is not evidence. A green cold root is not a
correct witness: v3 root 002 returned 47/47 while its process-ceiling witness
passed only because bubblewrap never started.

`RLIMIT_NPROC` is gone. It is charged against the **whole account**, not a
process tree, so it could never express a per-phase ceiling: set below the
account's ambient task count it makes bubblewrap's own namespace creation fail —
a startup failure that masquerades as containment — and set above it, the real
headroom is whatever ambient happens to leave that second. The cgroup's
`pids.max` is the aggregate ceiling the rlimit was pretending to be. The
descendant-count monitor is kept as an independent second witness, and
`pids.events.max` in the receipt is the kernel's own record of refused forks.

That record is now **read from the live cgroup**, not reconstructed afterwards.
A phase is PID 1 of its own namespace, so the instant it exits the kernel reaps
the namespace, the scope loses its last task and the cgroup — with the counter
that just fired — is gone. The fork-burst operation therefore holds the scope
open for a bounded window after the refusal, and the controller captures
`pids.max`, `pids.current` and `pids.events[.local] max >= 1` from the exact
cgroup that refused the fork. v4 retained `max = 0` and inferred the cause from
a limit and an errno; a witness the kernel did not sign is not a witness.

A phase runs in its own PID namespace, so a host-side `killpg` cannot enumerate
its children. Teardown therefore goes through `cgroup.kill`, which terminates
every task in the scope including those inside that namespace; signals remain as
the fallback once the scope is released.

Controller memory is bounded: child output is streamed to disk in 64 KiB chunks
and never accumulated before truncation.

### Disk

Source custody and checkpoint bytes are **enforced budgets, not declarations**:

| Budget | Limit | Enforced at |
|---|---|---|
| retained source custody | 5 GiB | `materialize_source`, before the clone |
| checkpoint custody | 2 GiB, latest checkpoint only | `write_checkpoint`, before install |

## Leases

A lease is fenced, atomic (`BEGIN IMMEDIATE`) and carries a monotonic fencing
token. Two properties matter and both are witnessed:

- **Liveness is decided by process identity, not by a timer.** On the granting
  host the holder's boot id, pid and `/proc/<pid>/stat` start-ticks are checked
  directly, so a phase that runs longer than the TTL cannot be reclaimed while
  the holder is alive. A heartbeat thread beats for the whole duration of a
  phase. The TTL decides only a holder whose identity this host cannot observe.
- **The lease is held through settlement.** It covers workspace sanitation,
  receipt and sidecar publication, the atomic transition to `SETTLED`, and the
  read-back that verifies it. A contender attempting to acquire inside that
  window is refused.

## Settlement is crash-recoverable

Settlement is a transaction of its own, and its order is chosen so that nothing
is destroyed before the evidence that would let it be reconstructed exists:

```
publish SETTLEMENT.json  ->  state = SETTLING     (intent, durable, fsynced)
sanitize workspace
write RECEIPT.json -> write RECEIPT.sha256
state = SETTLED, read back and verified          <- the commit point
purge checkpoints -> clear the journal            (idempotent tail)
```

v3 sanitized the workspace and purged every checkpoint *first*. A crash in that
window left a `RUNNING` transaction whose PASSed phases had lost the restore
points recovery required, and the next invocation could only return
`RECOVERY_REFUSED`. Now a crash anywhere before the commit point resumes from the
journal without re-executing a phase, and a crash after it completes the tail on
replay.

Two things settlement refuses to commit around:

- **A workspace that survived sanitation.** The receipt claims zero execution
  residue, and v4 deleted with errors ignored and then described the result, so
  a failed cleanup could produce a terminal row whose own verifier would reject
  its residue claim. Sanitation now reports its failures, a surviving workspace
  blocks the transition to `SETTLED`, the journal and restore points are kept,
  and the next invocation retries. Replaying an already-settled transaction
  retries sanitation too, since no other path revisits it.
- **A receipt that is not this settlement's receipt.** A receipt an earlier
  attempt published is **adopted** rather than rewritten, because it may already
  have been externally anchored — but only after it is proved to match the
  settlement journal: envelope, terminal, phases, source, runner profile and
  ledger intent. v4 checked only that the receipt agreed with its own sidecar,
  which says nothing about *which* settlement produced it. A self-consistent
  foreign receipt is now neither adopted nor overwritten: the transaction stays
  `SETTLING` and a human decides.

Each boundary is an admitted crash point (`TBRAIL_SETTLEMENT_CRASH_AT`, and
`TBRAIL_CHECKPOINT_CRASH_AT` for the checkpoint-install window) that SIGKILLs the
controller — no unwinding, no flush, no lease release — so the qualification
enters the windows for real rather than simulating them. **Reaching a crash
window requires qualification mode in the externally anchored runner profile.**
An unset, unknown or stale variable refuses the run before the transaction is
touched; it can never abort a production transaction mid-settlement.

### Durability, stated exactly

Every settlement record — journal, receipt, sidecar, custody manifest — is
written, `fsync`ed, atomically renamed, and its parent directory `fsync`ed; the
ledger runs SQLite WAL with `synchronous=FULL`, so a committed `SETTLED`
transition is on disk before the commit returns.

- **Witnessed:** controller-process crash. SIGKILL at six admitted settlement
  boundaries and two checkpoint boundaries, each recovered from a cold root.
- **Implemented but NOT witnessed:** sudden power loss and storage-layer
  failure. No test here cuts power. The protocol above is what the product
  implements for it; the claim stops there deliberately.

## Cross-phase state law

`CHECKPOINT_AND_RESTORE`. Each phase that PASSes checkpoints its workspace to a
digest-bound tar. On recovery the controller restores the last checkpoint rather
than recloning pristine source, so a phase that builds, transforms or
materialises something a later phase inspects survives a crash. A completed phase
is recovered from the journal and never re-executed; an interrupted `EFFECTFUL`
phase is refused with `HOLD` rather than silently re-run. A `PASS` phase whose
checkpoint is missing or has drifted refuses recovery.

Two bounds apply, because the archive is built from a workspace the phase
controls:

- **Closed extraction, agreeing with creation.** Every member is validated before
  a byte is written: hardlinks, devices, FIFOs, absolute paths, `..` traversal,
  any member resolving outside the new workspace, and any member that would land
  under a symlinked ancestor are refused. v3 used
  `extractall(filter="fully_trusted")`, which trusted worker-authored metadata.
  v4 refused links at extraction while `tarfile` happily *wrote* them at
  creation, so a repository containing a symlink produced an installed
  checkpoint that recovery could never restore. In v5 the two laws are the same
  law: creation refuses exactly what extraction refuses, and every installed
  checkpoint is validated under the extraction law at install time.
- **Symbolic links are captured, not refused.** A real repository contains them,
  including links that point outside the tree, and a restore point that cannot
  round-trip its own source is not a restore point. They are safe by *ordering*:
  restoration writes every directory and file first and creates links last, so
  nothing is ever written *through* a link, and bind sources are separately
  resolved under the repository with symlinked sources refused. Hard links are
  refused at creation, because extraction cannot reproduce them safely.
- **Bounded custody, enforced while writing.** One checkpoint may not exceed the
  checkpoint quota, and the bound is enforced *as the archive streams* — v4
  wrote the whole archive and checked its size afterwards, so an oversized
  workspace was already in custody by the time it was refused. Only the latest
  checkpoint is retained, because it is the only one recovery can use. v3 kept
  one full workspace tar per PASSed phase, outside the workspace budget.
- **The prior restore point outlives the new one's commit.** The superseded
  checkpoint is retired only after the new checkpoint *and its phase row* are
  durably committed. v4 installed the new checkpoint and deleted the old one
  before committing the row, so a crash in that window could leave the last
  committed PASS phase pointing at a checkpoint that no longer existed. Custody
  therefore holds two restore points inside that window and the declared ceiling
  says so.

## Receipts

A receipt binds the envelope, per-phase log digests, source bundle, rail scripts,
runtimes, repository manifests, the launch chain, the runner profile and the
ledger rows. `tbrail verify` recomputes every one of them in a fresh process.

**Identity is established before any path inside the receipt is followed.** When
an anchor is supplied it is checked first, and a mismatch returns immediately
without reading a single embedded path. Local artifacts are then *derived* from
the validated transaction id and the controller's own roots; a path recorded in
the receipt is only ever compared against those derivations, and one that
resolves outside the admitted roots, or onto something that is not a regular
file, is refused rather than opened. v3 hashed receipt-supplied absolute paths
before it had established that the receipt was trustworthy at all.

**Evidence validity is independent of outcome.** A valid `PASS`, `FAIL` or `HOLD`
receipt all verify. What must hold is that the recorded terminal is the one the
phase states imply, and that it agrees with the database terminal and the stored
envelope digest.

## Private custody

The controller root, database (and its WAL/SHM siblings), work root, receipts,
checkpoints and retained source are created under `umask 077` and forced to
owner-only modes on every start. Retained source custody is reported separately
from execution residue and is **not** zero: the exact-SHA bundle stays resident
between transactions.

It is owner-only on a single-tenant account; it is **not encrypted at rest**.
That is the current honest boundary, stated rather than implied.

Retained source is transferred — not garbage-collected — with the operation the
custody report names:

```bash
python3 tbrail.py purge-source            # dry run: what would move, and why
python3 tbrail.py purge-source --apply --successor-custody SOURCE-CUSTODY.json
```

The receipt verifier rehashes the source bundle, so deleting bytes a retained
receipt still names does not free space: it silently converts verifiable receipts
into unverifiable ones. `purge-source` is therefore a **custody transition** with
three refusals:

1. any transaction in an unresolved state protects its bundle — `QUEUED`,
   `RUNNING`, `SETTLING`, `HELD`, `FENCED_OUT`, or any other non-`SETTLED` state.
   v4 protected only the first four, so a fenced-out transaction's source could
   be purged out from under it;
2. any retained receipt protects the bytes it needs;
3. that second protection lifts only for a successor-custody entry that is
   *independently verified* — the named object must exist, live outside the hot
   custody root, and rehash to the digest the receipts name.

After the transition every retained receipt is re-verified and the report states
that no receipt which verified before it fails after it. Verification then finds
the bytes through the recorded successor route.

v3's custody report advertised this command while the CLI had no such subcommand.

## Runner profile

`tbrail execute` refuses to run without an accepted runner profile **and an
externally supplied digest for it**. The profile pins the controller path and
digest, **the interpreter that executes it** (absolute path, version and
digest), the bubblewrap binary, the launch chain (`systemd-run`, `prlimit`,
`sh`), every pinned runtime, every rail script, every repository-operation
manifest, the guest root, the ceilings and the aggregate-enforcement mechanism.

Pinning the interpreter closes a real gap: identical controller bytes under a
different Python are a different runner, and until v5 that substitution produced
no drift at all. A profile that names a different interpreter — or names none —
refuses the run, and the qualification runs under the pinned interpreter itself.

`--runner-profile-sha256` (or `TBRAIL_RUNNER_PROFILE_SHA256`) is **mandatory**,
for `execute` and `profile-check` alike, and the refusal happens before any lease
is acquired. Without it the controller would only be comparing the adjacent
profile file against its own observed bytes — so the controller and its profile
could be changed together and still self-admit. A locally self-consistent profile
is not an authority. v3 accepted that anchor as optional and reported
`externally_pinned: false` while still executing.

The controller also refuses to execute where the delegated cgroup subtree cannot
provide aggregate `cpu`, `memory` and `pids` enforcement, rather than silently
falling back to weaker per-process approximations.

The profile pins absolute paths, so it is bound to one controller at one install
location. Re-emit the profile if that location changes, and re-accept it as a
reviewed artifact. The concrete paths live in the committed
`RUNNER-PROFILE.<host>.json`, where they are load-bearing typed evidence; this
document does not restate them, because prose is not evidence and this
repository is public.

```bash
# emit (once, at admission), then commit and review the result
TBRAIL_HOME=/tmp/emit python3 tbrail.py profile-emit RUNNER-PROFILE.$(hostname).json
python3 tbrail.py profile-check --runner-profile RUNNER-PROFILE.$(hostname).json \
    --runner-profile-sha256 <accepted digest>
```

## Cold qualification

```bash
python3 cold_qualify.py <fresh-root> <source-bundle> <accepted-profile-sha256>
```

It refuses a root that already holds a database, lease, workspace, receipt or
checkpoint. The accepted profile digest is an **external input**: it is read from
the deployment's accepted profile, quoted in the review packet, and enforced
during the run. Receipts and `COLD-QUALIFICATION.json` land under the fresh root.

The qualification builds its own fixture repository (a nested package tree plus a
symlink pointing out of the tree) so nested-subtree and symlink-escape behaviour
are proved on real source through the real clone-and-bind path.

Two profiles are in play, and the difference is the point:

- the **accepted** profile is the production admission and does not admit the
  crash hooks;
- the **qualification** profile is derived from it by adding exactly one key,
  `_qualification_mode`, has its own digest, and is what admits the deliberate
  crash windows. The derivation is itself a property: the two files must differ
  by that one key and nothing else.

So no production anchor can carry the permission to kill a transaction, and the
qualification still exercises the same controller bytes under the same profile
in every other respect. The qualifier also runs under the pinned interpreter and
proves it, and it loads every controller it starts with credential-shaped
sentinel variables so environment closure is proved rather than assumed.

## Runtime pinning, stated exactly

The datum is **Python 3.11.15** at `/opt/tbrail/py311/bin/python3.11`, pinned by
absolute path and digest, obtained by copying `/usr/local` out of a
`python:3.11-slim` image; there is no container in the execution path. Ubuntu
26.04 ships no 3.11.

`python3.14` is a **second matrix point, not stronger evidence**. Running the
canary on both proves phase-for-phase agreement across two admitted runtimes.
It does not supersede the 3.11 datum and it is not a newer-is-better claim;
earlier prose in this lane that read that way was wrong.

## Scope of the claim

What the rail is qualified for is stated in the cold qualification, and nothing
beyond it. In particular this lane does **not** claim, and does not implement:

- a JIT Actions adapter, or migration of any further private workflow;
- publication credentials on the worker (the controller host holds no GitHub
  credential; the publication hop is still adapter-assisted from a credentialed
  seat);
- check-runs (a PAT can only write commit statuses; check-runs need a GitHub App);
- encryption at rest for retained source custody;
- anything about repository or organisation level settings;
- durability against sudden power loss or storage-layer failure. The write
  protocol for it is implemented and stated; no test here cuts power, so the
  witnessed claim is controller-process-crash recovery.

`ESTATE-WORKFLOW-INVENTORY.json` is generated by `inventory_workflows.py` from a
checkout of the bound revision. It resolves `runs-on: ${{ matrix.os }}` against
each job's own matrix; all five accepted workflows **do** run on GitHub-hosted
images. Its `provider_calls: false` is a textual-hint result about the YAML, not
proof that no invoked script reaches a provider, and it states what it does not
claim.

## Superseded contracts

**The v1 and v2 surface lives under `historical/` and is NOT CURRENT.** It is not
a route, a starting point or a contract; see `historical/README.md`.

- **v1** (`historical/envelopes/`, `historical/receipts/canary-001`,
  `defect-001`): literal-argv controller with a `SAFE_TOOLS` allow-list.
  Withdrawn: `python3 -c` and `sh -c` are general interpreters, so an allow-list
  of executables was never a boundary.
- **v2** (`historical/envelopes-v2/`, `historical/receipts/cold-canary-py311`,
  `cold-qualification-20260812.json`): typed operations and bubblewrap, but the
  lease could be reclaimed during a phase longer than its TTL, was released
  before settlement, recovery discarded phase-produced state,
  `python.repo_script` still let an envelope choose a script and its own
  `allowed_switches`, bind sources were not symlink-safe, the verifier refused
  valid red and HOLD receipts, custody was mode `0644`, identities were
  self-observed, and ceilings were descriptive.
- **v3** (`receipts/cold-qualification-v3-20260812.json`, `cold-v3-*`, head
  `ad36bf604166b3f867f017470a3b68c872a7ab48`): the accepted 47/47 cold
  qualification. It is **valid predecessor evidence and is retained as such**,
  not a current contract. Settlement had an unrecoverable crash window,
  checkpoint extraction was `fully_trusted` and checkpoint custody was unbounded,
  the runner-profile anchor was optional, the verifier followed receipt-supplied
  paths before establishing receipt identity, `preexec_fn` ran in the forked
  child of a threaded controller, and per-process rlimits were described as phase
  ceilings.

- **v4** (`receipts/EVIDENCE-INDEX.json` → `cold-qualification-v4-20260812.json`,
  `cold-v4-*`, head `6c47e076f7cae0c6dd3099e1fa1375d5bf654e59`): the accepted
  61/61 cold qualification. It is **valid predecessor evidence and is retained
  as such**, not a current contract. Its bounded admission defects are the ones
  v5 closes: the launch chain inherited the controller's environment and the
  sandbox set variables without clearing them; the checkpoint quota was checked
  only after a larger archive existed; checkpoint creation wrote link members
  that its own extraction law refused; the superseded restore point was deleted
  before the phase row was committed; settlement could commit around a failed
  sanitation or adopt a self-consistent foreign receipt; `purge-source` could
  delete bytes retained receipts still needed and did not protect `FENCED_OUT`;
  the interpreter executing the controller was unpinned; the process-ceiling
  proof was inferential; durability and crash-hook scope were unbounded; and the
  public tree carried the deployment's own coordinates.

All are kept as evidence — bodies in private holder custody, exact digests in
the `EVIDENCE-INDEX.json` beside each retired location. `python.repo_script` is
gone from the registry, and an envelope naming it is refused at submit.
