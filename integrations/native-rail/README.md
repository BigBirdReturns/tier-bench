# Native private execution rail

A controller that executes private repository work on hardware we own, instead of
on a per-job GitHub-hosted runner. GitHub stays the canonical surface for source,
review and status. The rail owns queue, claims, execution, recovery and
settlement.

**The operative contract is v3.** v1 and v2 are retained only as historical
evidence of how the contract got here; neither is invocable and neither should be
reasoned from. See [Superseded contracts](#superseded-contracts).

```text
controller   integrations/native-rail/tbrail.py
envelopes    integrations/native-rail/envelopes-v3/
operations   integrations/native-rail/ops/ (rail scripts, digest-pinned)
             integrations/native-rail/repo-ops/ (accepted repository manifests)
profile      integrations/native-rail/RUNNER-PROFILE.<host>.json
qualifier    integrations/native-rail/cold_qualify.py
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

| Ceiling | Enforced by | Default |
|---|---|---|
| output bytes | streaming pump; the child is torn down, not merely truncated | 4 MiB |
| CPU seconds | `RLIMIT_CPU` | 900 |
| address space | `RLIMIT_AS` | 4 GiB |
| file size | `RLIMIT_FSIZE` | 1 GiB |
| open files | `RLIMIT_NOFILE` | 1024 |
| processes | `RLIMIT_NPROC` + process-group monitor | 512 |
| workspace bytes | monitor thread | 8 GiB |
| wall clock | `timeout_seconds`, then process-group teardown | 900 (max 1800) |

Controller memory is bounded: child output is streamed to disk in 64 KiB chunks
and never accumulated before truncation.

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

## Cross-phase state law

`CHECKPOINT_AND_RESTORE`. Each phase that PASSes checkpoints its workspace to a
digest-bound tar. On recovery the controller restores the last checkpoint rather
than recloning pristine source, so a phase that builds, transforms or
materialises something a later phase inspects survives a crash. A completed phase
is recovered from the journal and never re-executed; an interrupted `EFFECTFUL`
phase is refused with `HOLD` rather than silently re-run. A `PASS` phase whose
checkpoint is missing or has drifted refuses recovery.

## Receipts

A receipt binds the envelope, per-phase log digests, source bundle, rail scripts,
runtimes, repository manifests, the runner profile and the ledger rows.
`tbrail verify` recomputes every one of them in a fresh process and consults an
external anchor when supplied, so a self-consistent forged receipt+sidecar pair
does not pass.

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

## Runner profile

`tbrail execute` refuses to run without an accepted runner profile. The profile
pins the controller path and digest, the bubblewrap binary and digest, every
pinned runtime, every rail script, every repository-operation manifest, the guest
root and the ceilings. Supplying `--runner-profile-sha256` (or
`TBRAIL_RUNNER_PROFILE_SHA256`) additionally pins the profile file itself to an
externally quoted digest, so the run cannot accept a locally rewritten profile.

The profile pins absolute paths. The accepted `octo-n01` profile is bound to the
controller at `/home/octo/tbrail-v3`; re-emit the profile if the install location
changes, and re-accept it as a reviewed artifact.

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
- publication credentials on the worker (octo-n01 holds no GitHub credential;
  the publication hop is still adapter-assisted from a credentialed seat);
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

- **v1** (`envelopes/`, receipts `canary-001`, `defect-001`): literal-argv
  controller with a `SAFE_TOOLS` allow-list. Withdrawn: `python3 -c` and `sh -c`
  are general interpreters, so an allow-list of executables was never a boundary.
- **v2** (`envelopes-v2/`, receipts `cold-canary-py311`,
  `cold-qualification-20260812.json`): typed operations and bubblewrap, but the
  lease could be reclaimed during a phase longer than its TTL, was released
  before settlement, recovery discarded phase-produced state,
  `python.repo_script` still let an envelope choose a script and its own
  `allowed_switches`, bind sources were not symlink-safe, the verifier refused
  valid red and HOLD receipts, custody was mode `0644`, identities were
  self-observed, and ceilings were descriptive.

Both are kept as evidence. `python.repo_script` is gone from the registry, and an
envelope naming it is refused at submit.
