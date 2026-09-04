# FRR-ASTRA-STAGE2-B353-EXECUTION-RECORD - superseded local Prepare

```yaml
id: FRR-ASTRA-STAGE2-B353-EXECUTION-RECORD
state: SUPERSEDED_FAIL_CLOSED_EXECUTION_RECORD
date: 2026-09-03
release_head: b3534c9703723ac35343af0209edc34c7587173c
release_tree: 15f64f02f5dfc6b1e5e59634205dc7d157d9c125
checkpoint: checkpoint/astra-stage2-control-identity-b3534c9-20260903
package_bytes: 79536
package_sha256: 006ab8a794e916497766a85c755d7f9e7859c86668171771a49b386f32a6183a
preflight_receipt_sha256: df4841277f70d44d306c7739b2fc625a0f0afe4aaea6d60c98d1fbd5b15797ea
prepare_receipt: ABSENT
model_calls: 0
provider_calls: 0
binding: NOT_RUN
empirical_calibration: NOT_RUN
numeric_stage2_freeze: NOT_ISSUED
authority: NONE
```

## Disposition

B353 is frozen as a superseded, fail-closed native-Windows execution record.
It is not a completed Prepare and is not a qualification result for any
successor. Its live Preflight receipt must remain historical B353 evidence and
must not be promoted into a successor transaction.

The independently qualified release construction remains useful evidence for
its exact head and tree, source and checkpoint custody, clean detached
worktree, deliberately non-repository binder import, and provider-free
Preflight. The local proven chain ends at:

```text
archive -> checkpoint -> preserved assets -> pinned binder import -> PREFLIGHT_PASS
```

The blocked chain begins at:

```text
native Windows hardware probe -> PREPARE-RECEIPT -> private inventory
```

## Retained observations

- The handoff archive was 79,536 bytes, CRC-clean, and contained eight files.
  Its SHA-256 is recorded above.
- The checkpoint resolved exactly to the recorded B353 head and tree.
- The detached B353 worktree was clean. The separate conventional checkout was
  observed dirty, preserved, and left untouched.
- The package expected launcher SHA-256
  `3ff10be5f30971c14139b13320d9758da2ea54839152b14fa2e8ac558d509fbb`.
  Under ambient `core.autocrlf=true`, the committed LF blob initially
  materialized as different CRLF execution bytes. A temporary worktree-local
  diagnostic setting reproduced the expected LF digest and was removed.
- The packaged retry carrier contains
  `if (Get-Sha256 $launcher -ne $ExpectedLauncherSha256)`. PowerShell parses
  the comparison as arguments to the function. The in-memory correction
  `if ((Get-Sha256 $launcher) -ne $ExpectedLauncherSha256)` was diagnostic
  only and does not revise the package.
- That diagnostic continuation emitted a B353
  `tier-bench/astra-stage2-control-identity-preflight@2` receipt with the
  SHA-256 recorded above.
- Native `nvidia-smi topo -m` exited `255` and reported
  `Option -m is missing its value`. Native NVIDIA inventory remained
  available; WSL was absent.
- At final audit, `PREPARE-RECEIPT.json`, both private configuration files,
  and bound output were absent. The hardware evidence directory was empty.
- Temporary Git configuration used by the diagnostic was removed, and the
  B353 worktree returned to its clean exact head/tree state.

## Authority ledger

B353 authorizes no Bind, Verify, runtime or effort mapping, model execution,
provider call, empirical calibration, or numeric Stage 2 freeze. Its three
release defects are:

1. malformed PowerShell digest comparison;
2. ambient line-ending-dependent execution bytes; and
3. a Linux-only topology command required on native Windows.

A successor requires its own law coordinate, binder coordinate, release head
and tree, launcher digest, Preflight receipt, and Prepare receipt. The
successor Prepare receipt must bind the SHA-256 of that successor's Preflight
receipt and stop at
`ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND`.

