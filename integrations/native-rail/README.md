# Native private execution rail

A controller that executes private repository work on hardware we own, instead of
on a per-job GitHub-hosted runner. GitHub stays the canonical surface for source,
review and status. The rail owns queue, claims, execution, recovery and
settlement.

**The operative contract is v4.** v1 and v2 live under `historical/` and are not
invocable; v3 is retained as valid predecessor evidence, not as a contract.
Nothing outside the paths below should be reasoned from. See
[Superseded contracts](#superseded-contracts).

```text
controller   integrations/native-rail/tbrail.py           (v4)
envelopes    integrations/native-rail/envelopes-v3/
operations   integrations/native-rail/ops/ (rail scripts, digest-pinned)
             integrations/native-rail/repo-ops/ (accepted repository manifests)
profile      integrations/native-rail/RUNNER-PROFILE.<host>.json
qualifier    integrations/native-rail/cold_qualify.py
reproduction integrations/native-rail/run_proofs.sh
historical   integrations/native-rail/historical/          NOT CURRENT
```

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
replay. A receipt an earlier attempt already published is **adopted**, not
rewritten, because it may already have been externally anchored.

Each boundary is an admitted crash point (`TBRAIL_SETTLEMENT_CRASH_AT`) that
SIGKILLs the controller — no unwinding, no flush, no lease release — so the
qualification enters the windows for real rather than simulating them.

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

- **Closed extraction.** Every member is validated before a byte is written:
  symlinks, hardlinks, devices, FIFOs, absolute paths and `..` traversal are
  refused, and any member resolving outside the new workspace is refused. v3 used
  `extractall(filter="fully_trusted")`, which trusted worker-authored metadata.
- **Bounded custody.** Only the **latest** checkpoint is retained — it is the
  only one recovery can use — and it may not exceed the checkpoint quota. v3 kept
  one full workspace tar per PASSed phase, outside the workspace budget, so 32
  phases could multiply the transaction's real footprint far past its declared
  ceiling.

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

Retained source is purged with the operation the custody report names:

```bash
python3 tbrail.py purge-source            # dry run: what would be purged, and why
python3 tbrail.py purge-source --apply    # delete
```

An item is purgeable exactly when no `QUEUED`, `RUNNING`, `SETTLING` or `HELD`
transaction references its digest. v3's custody report advertised this command
while the CLI had no such subcommand.

## Runner profile

`tbrail execute` refuses to run without an accepted runner profile **and an
externally supplied digest for it**. The profile pins the controller path and
digest, the bubblewrap binary, the launch chain (`systemd-run`, `prlimit`, `sh`),
every pinned runtime, every rail script, every repository-operation manifest, the
guest root, the ceilings and the aggregate-enforcement mechanism.

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
the committed profile, quoted in the review packet, and enforced during the run.
Receipts and `COLD-QUALIFICATION.json` land under the fresh root.

The qualification builds its own fixture repository (a nested package tree plus a
symlink pointing out of the tree) so nested-subtree and symlink-escape behaviour
are proved on real source through the real clone-and-bind path.

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
- anything about repository or organisation level settings.

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

All are kept as evidence. `python.repo_script` is gone from the registry, and an
envelope naming it is refused at submit.
