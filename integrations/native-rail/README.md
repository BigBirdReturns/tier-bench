# Native private execution rail

Mission `BigBirdReturns/tier-bench#164`. First-repository canary
`BigBirdReturns/estate#78`. Controller and execution domain: `octo-n01`
(Ubuntu 26.04, 8 CPU, 31 GB RAM, 172 GB free).

Zero GitHub-hosted runner minutes. Zero provider calls. No S: path used for
runner, image, cache, workspace, or receipt.

## Two states in this directory — read this first

| | v1 canary (preserved) | v2 product candidate |
|---|---|---|
| controller | frozen at `ae7e12e` in git history | `tbrail.py` |
| envelopes | `envelopes/` | `envelopes-v2/` (generated) |
| harness | `run_proofs.sh` | `cold_qualify.py` |
| receipts | `receipts/canary-001-*`, `receipts/PROOFS.txt` | `receipts/cold-*` |
| status | **PASS, retained as evidence** | **28/28 cold properties PASS** |

The v1 canary is the historical proof that one private Estate qualification ran
natively on `octo-n01` with zero hosted minutes. It is preserved unmodified and
must not be regenerated. Its receipt digest
`cddad892af38bcdcadf2d149da96a61021ac23ee5858f3607597330cc34336bb` is anchored
by the Estate commit status on `fb47a4cc`.

v2 is the repair of the blocking second-desk review (`5262851689`). It is a
different controller with a different envelope schema; it does not invalidate
the v1 canary and does not inherit its proof state.

## What v2 changed, and why

| review finding | v2 answer |
|---|---|
| envelope not closed; derived paths uncontained | exact closed schemas top-level and per phase; safe identifier grammar; `resolve_under` on every derived path; `sanitize` refuses to delete outside `work/` |
| `SAFE_TOOLS` + literal argv is not a code boundary | **argv is no longer data.** A phase names an operation id and typed params; the controller builds the command. There is no path from envelope text to an interpreter argument. Repository scripts are bound by exact path *and* exact digest |
| `allowed_paths` declared but unenforced | enforced structurally by the bubblewrap mount set — only declared subtrees are writable, and the controller's home is never mounted |
| restart proof only covered settled replay | phase-level journal with an explicit idempotency law: completed phases are recovered, not re-executed; an interrupted `EFFECTFUL` phase yields `HOLD`, never a silent re-run |
| PID-only unfenced lease reclaim | `BEGIN IMMEDIATE` compare-and-swap, owner UUID, monotonic fencing token, boot id, PID + process-start ticks, heartbeat and bounded expiry |
| teardown covered the direct child only | every phase runs in a new session; teardown kills the process group and independently proves descendant absence by scanning `/proc` |
| receipt verification too narrow | the receipt binds envelope, per-phase log digests, source bundle, ops/runtime digests and the ledger; `verify` recomputes all of them and accepts an external anchor |
| 3.14 presented as equivalent to a 3.11 workflow | the subject workflow pins **3.11**, so 3.11 is the equivalence datum and 3.14 is an additional matrix point. Runtimes are pinned by absolute path, version and SHA-256 |
| "zero residency" overclaimed | renamed `ZERO_TRANSACTION_EXECUTION_RESIDUE`; retained source custody is reported separately with owner, digest, bytes, mode, quota, retention and purge law |

## Cold qualification

```bash
python3 make_envelopes.py                     # regenerate envelopes-v2/
python3 cold_qualify.py <FRESH_ROOT> <BUNDLE> # refuses a root that is not cold
```

The harness is parameterized by `TBRAIL_HOME` and refuses to start against a
root already holding a database, workspace or receipt, so it cannot reuse
settled proof state. Receipt: `receipts/cold-qualification-20260812.json`.

## What this is

`tbrail.py` is a single stdlib-only Python controller. One transaction is one
envelope, one lease, one disposable workspace, one receipt. Every phase runs
inside a single worker lifecycle — a phase never requires a fresh machine merely
to observe the previous phase.

```text
submit    validate a closed envelope, queue it durably
execute   lease -> materialize -> bind exact head+tree -> phases -> terminal
          gate -> receipt -> teardown
verify    reconstruct and re-verify a terminal receipt in a fresh process
residency prove no leases, no workspaces, no worker processes remain
list      the durable transaction ledger
```

### The envelope is closed data

Issue text, PR prose, comments, and model output never become shell input. Each
phase supplies `argv` as a list of literal strings, the first element must be in
`allowed_tools`, and `allowed_tools` is itself intersected with a hard-coded
`SAFE_TOOLS` set. `UNTRUSTED_FORK` is rejected outright — the trusted rail never
executes public fork code.

### The worker holds no credential

Source arrives as a pre-verified exact-SHA git bundle. The controller checks the
bundle digest before cloning, then asserts the checked-out `HEAD` and tree match
the envelope. The worker environment is rebuilt from an allowlist with `HOME`
redirected into the disposable workspace and `GIT_TERMINAL_PROMPT=0`.

This is why `octo-n01` needs no GitHub credential to run a private-repository
qualification, and it is proved rather than asserted — see property B below.

## Canary: `estate-organ-realignment-qualification`

Selected from the five accepted Estate workflows because it is provider-free,
Linux-compatible, `contents: read` only, and pure stdlib — no `pip install`, so
no network beyond source materialization.

```text
repository     BigBirdReturns/estate (private)
head           fb47a4cc50e74ac230efe1b063631933a5106a0a
tree           72ceba0bd0d695aa4d8eae953c3c0ebe5a438a4f
bundle sha256  f379b74463c181a829e7893add829fdfc0926cf2516328ef4a89f0858190a5db
receipt sha256 cddad892af38bcdcadf2d149da96a61021ac23ee5858f3607597330cc34336bb
terminal       PASS   5/5 phases   1.361 s
GitHub status  tier-bench/native-rail/organ-realignment-qualification = success
```

All five original steps were reproduced: compile candidate, authority and
cold-reconstruction witnesses, registry and alias digest verification, inert
organ-map render, and the no-source-mutation witness.

**Evidence is equal or stronger.** The workflow pins Python 3.11 via
`actions/setup-python`; the rail executed the same witnesses under the host's
Python 3.14.4 and they still pass. Nothing was weakened to make it green.

## Proved properties

```text
A  deliberate validation defect renders red      PASS  terminal=FAIL
B  worker credential isolation                    PASS  no banned env;
                                                        private clone rc=128
C  restart replay does not duplicate              PASS  replay=true;
                                                        phase rows stay 5, not 10
D  same-resource collision serializes or holds    PASS  contender -> COLLISION_HELD
E  receipt reconstructs in a fresh process        PASS  digest match
F  zero residency                                 PASS  0 leases, 0 workspaces,
                                                        0 worker processes
```

Full transcript in `receipts/PROOFS.txt`.

### One honest finding from property A

The injected defect appended a single space to `estate_organ_registry.json`.
`estate_authority_resolver.py verify` returned **0** — it did not detect the
tamper. The transaction still went red, but only because the
`git diff --exit-code` witness caught it.

That means the Estate's registry digest check is whitespace-insensitive. The rail
behaved correctly; the finding belongs to the Estate qualification, not to the
rail, and is worth a separate issue. It is the same class as the constant-length
semantic tamper lesson: a verifier that passes on modified bytes is not a
tamper-evidence witness.

## What is deliberately not here

The JIT GitHub Actions adapter is **not implemented**. The equivalence inventory
(`ESTATE-WORKFLOW-INVENTORY.json`) found no accepted property in the canary that
depends on Actions semantics. Availability is not justification. One adapter
dependency does exist elsewhere and is recorded rather than built:
`estate-closure-conductor-qualification.yml` uses `actions/upload-artifact@v4`,
which is a durable-custody need the rail already satisfies with local receipts.

Concurrency is deliberately one transaction at a time. Parallelism waits on
measured collision, disk, cache, and recovery behavior.

## Known limitation, stated plainly

`octo-n01` holds no GitHub credential, so the exact-head commit status was posted
by the credentialed `octo-w01` seat from the native result. The evidence is
native; the publication hop is not yet. Closing this requires provisioning a
narrow credential on the controller — `contents: read` plus `repo:status`, scoped
to `estate` and `tier-bench` — which is a credential act outside this mission's
authority. Until then the rail is fully native for execution and settlement, and
adapter-assisted for publication only.

Note also that GitHub check *runs* require a GitHub App; a PAT or OAuth token can
only write commit *statuses*. Issue #164 permits either.

## Running it

```bash
python3 tbrail.py submit envelopes/envelope-canary.json
python3 tbrail.py execute estate-organ-realignment-canary-001
python3 tbrail.py verify ~/.tbrail/receipts/<txn>/RECEIPT.json
python3 tbrail.py residency
bash run_proofs.sh          # the full adversarial suite
```
