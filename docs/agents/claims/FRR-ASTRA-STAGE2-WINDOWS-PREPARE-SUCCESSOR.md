# FRR-ASTRA-STAGE2-WINDOWS-PREPARE-SUCCESSOR — convergence candidate

```yaml
id: FRR-ASTRA-STAGE2-WINDOWS-PREPARE-SUCCESSOR
state: SOURCE_SUCCESSOR_QUALIFICATION_PENDING
date: 2026-09-04
failed_checkpoint_head: e3367f9e5de48a099a585077a58ce9cff1051cab
failed_checkpoint_tree: 8e0aaaf84bd0487c25c531c768cf35c611469f42
defect: WINDOWS_POWERSHELL_5_1_NATIVE_ARGUMENT_TRANSPORT
qualified_binder_parent: dbb44b7efca1b04f2ed2d8c127af653b278909e4
qualified_binder_tree: 2671247337030d9c8e281393103104f7436d2800
qualified_portability_parent: 0e790fea09668e5f537bdd00fcb2bdb3364855c3
qualified_portability_tree: 5a95423cc5dee0fa7ffc893fb3f41634ef735b3f
qualified_portability_carrier: f558ab3ff48ff85d1358d57468ea359608e9f1d5
qualified_portability_run: 33899335376
law_head: c36c35bf9b70d879e1e1c9ee2f0296879442df3e
law_blob: 77abe4e177fc61e4f52f56ea64494b113f9662fc
source_successor_qualification: STILL_PENDING
test_denominator: 44
core_tests: 34
release_tests: 10
actual_executable_identities: UNBOUND
physical_prepare: NOT_RUN
model_calls: 0
provider_calls: 0
calibration: NOT_RUN
numeric_freeze: NOT_ISSUED
checkpoint_succession: NOT_ISSUED
merge_authority: NONE
```

## Classification and lineage

The `e3367f9e5de48a099a585077a58ce9cff1051cab` checkpoint is a convergence
candidate derived from two separately qualified
parents. `dbb44b7` is the qualified binder product and supplies the active
binder implementation, schemas, law binding, and complete 34-test core
witness. `0e790fea` is the qualified portability repair and supplies the
WinError-1314-only symlink behavior plus the retained release surfaces.

On that exact e336 checkpoint, the controller recorded a valid Preflight and a
valid hardware-probe file set. Physical Prepare then failed before its receipt
or configuration files were written. The defect classification is
`WINDOWS_POWERSHELL_5_1_NATIVE_ARGUMENT_TRANSPORT`: passing the embedded
canonical-JSON program through native `python -c` under Windows PowerShell 5.1
removed the Python string quotes and changed `separators=(",", ":")` into an
invalid expression. This is a source-transport defect, not a hardware,
checkpoint, identity, calibration, or provider observation.

The commit `f558ab3` is an audit-only hosted carrier for the portability
subject. It is evidence about `0e790fea`; it is not a parent, implementation,
or release candidate. The B353 execution record remains immutable historical
fail-closed evidence and is not evidence that this convergence tree has run a
physical Prepare.

The earlier native-Windows binder lineage is superseded history, not the
active implementation or active law of this candidate. The active coordinates
are the qualified binder and law coordinates in the ledger above.

## Candidate contract

The candidate preserves the qualified binder's typed platform and topology
evidence. A Windows probe is restricted to one selected device and records
`NOT_APPLICABLE_SINGLE_SELECTED_DEVICE` with
`PLATFORM_LIMITATION_SINGLE_DEVICE`, without claiming inter-device topology or
implicit pooling. A Linux probe records an observed `NVIDIA_SMI_TOPO_MATRIX`
and does not claim implicit pooling. The dormant Prepare source binds the
probe receipt, all three evidence-file digests, the topology-evidence digest,
the selected-device singleton, and the canonical payload digests.

The source successor carries only a launcher-function transport repair plus its
release test, workflow, and this record. The canonical program is written as
UTF-8 without BOM to an exclusively created unpredictable temporary `.py`,
invoked with `python -B`, and removed fail-closed. The canonical algorithm is
unchanged. The exact committed function is extracted by PowerShell parser AST
into a disposable `-File` harness; it is never tested by dot-sourcing the full
launcher.

The provider-free release workflow parses both PowerShell execution surfaces
and exercises 44 tests: 34 core plus 10 release. Symlink-capable Windows must
pass 44/44 with zero skips; a measured WinError 1314 permits only test_10 to
skip, producing 43 passes and one skip. Ubuntu must pass 44/44 with zero skips.
test_30 never skips. Its interpreter witness requires the native
`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe` at version 5.1,
records its full version, and separately exercises hosted-Windows `pwsh` and
Ubuntu `pwsh`. Every interpreter witness records its PowerShell edition and
actual `PSNativeCommandArgumentPassing` value when available, or explicit
`LEGACY_UNAVAILABLE`. The valid non-ASCII fixture exits zero. Each expected
production refusal emits its structured fixture result and exits 20, including
malformed/nonfinite inputs, missing input/interpreter, invalid output shapes,
cleanup refusal, and preference restoration. The e336 function's failure also
retains exit 20 and is required only on Windows PowerShell 5.1; no such mutant
result is required from `pwsh`.

The controller also pins the new fixture harness stdout and Python decoder to
UTF-8. Native Windows PowerShell defaults otherwise allow non-ASCII failure
paths to corrupt the structured fixture transport. The nine pre-existing
release tests and the production canonical algorithm are unchanged. Controller
subprocesses are launched with closed stdin; an interactive terminal input pipe
is not an admissible source of test input.

Each platform uploads its actual platform receipt, test log, and transport
fixture result. The index job downloads those bytes, recomputes their digests,
verifies the common head/tree and interpreter/test witnesses, and retains the
complete evidence beside the sealed index. Synthetic function fixtures are not
physical Prepare evidence. The workflow does not execute Preflight, Prepare,
Bind, Verify, checkpoint Retry, GPU/model/provider work, or benchmark calls.

## Pending gate and authority

Source-successor qualification is **STILL PENDING** until the eventual exact
release head and tree complete the hosted Windows, Ubuntu, and evidence-index
jobs. No
qualification, publication, checkpoint succession, physical Prepare,
calibration, numeric freeze, or executable identity follows from construction
of this local tree.

At this gate the actual executable identities remain **UNBOUND**, physical
Prepare is **NOT_RUN**, model calls are **0**, provider calls are **0**,
calibration is **NOT_RUN**, numeric freeze is **NOT_ISSUED**, checkpoint
succession is **NOT_ISSUED**, and merge authority is **NONE**.
