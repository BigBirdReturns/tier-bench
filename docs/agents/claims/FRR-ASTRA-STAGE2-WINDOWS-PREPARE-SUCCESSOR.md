# FRR-ASTRA-STAGE2-WINDOWS-PREPARE-SUCCESSOR - local candidate

```yaml
id: FRR-ASTRA-STAGE2-WINDOWS-PREPARE-SUCCESSOR
state: IMPLEMENTATION_CANDIDATE
date: 2026-09-03
law_head: 66699d317be4146847485828819f8ffb76277eb7
law_tree: 1ef85cd5829a73dabda071d7812ebc12507770f6
law_blob: a7dc64135af76ca5e081d30737d0ba08a38a57b1
binder_head: c8f914073cb11da29925ccd5d2167f661816e1fd
binder_tree: e0f5e6e72e5ba3666957d9d5ad1a7a230839f6a5
release_construction_commit: fbc8f57fb94b10fef8d5d9d331ac81857a1fec1d
release_construction_tree: c83cc16b410819cac0d990266251dd8c88d56c19
checkpoint: NOT_ISSUED
independent_audit: NOT_RUN
real_host_preflight: NOT_RUN
real_host_prepare: NOT_RUN
model_calls: 0
provider_calls: 0
binding: NOT_RUN
empirical_calibration: NOT_RUN
numeric_stage2_freeze: NOT_ISSUED
```

## Candidate contents

The local candidate implements the coordinated B353 successor changes:

- repository-owned checkpoint retry with an executable digest-only mode and a
  parenthesized SHA-256 comparison;
- LF checkout rules for every Astra Stage 2 PowerShell execution surface;
- schema-v2, platform-dispatched hardware evidence;
- continued hard enforcement of `nvidia-smi topo -m` on Linux;
- a native-Windows evidence bundle containing NVIDIA identity, negotiated PCIe
  link generation and width, display-class PnP bus/address/location/ancestry,
  and Thunderbolt or USB4 candidates;
- recognized preservation of the native-Windows unsupported topology command;
- `TOPOLOGY_CLASS=UNKNOWN` when native evidence cannot prove the complete
  transport relationship;
- hard refusal for missing mandatory evidence or contradictory NVIDIA/link/PnP
  identities;
- allowance for provider-free Prepare with honest `UNKNOWN`, paired with a
  hard refusal to bind an executable identity while topology remains
  `UNKNOWN`; and
- Prepare receipt binding of the exact hardware-probe receipt and its platform
  statuses.

B353 remains unchanged and is recorded separately in
`FRR-ASTRA-STAGE2-B353-EXECUTION-RECORD.md`.

## Local qualification

On the native Windows custody host, the combined unit and release suite ran 36
tests: 35 passed and one privilege-dependent symlink test was skipped. The
matrix exercised:

- digest match and digest mismatch;
- Windows unsupported-command handling and raw failure preservation;
- honest Windows `UNKNOWN`;
- NVIDIA-to-PCI-link contradiction refusal;
- NVIDIA-to-PnP product contradiction refusal;
- missing mandatory native display evidence refusal;
- Linux topology-matrix failure refusal and success preservation;
- refusal to bind `UNKNOWN` topology;
- Preflight/Prepare zero-call and unbound stop-wall construction; and
- clean checkout under both `core.autocrlf=true` and
  `core.autocrlf=false`.

Two disposable clean Windows clones of the release-construction commit were
clean at the exact recorded head/tree. Both settings produced identical,
LF-only execution bytes:

| payload | SHA-256 under both Git settings |
|---|---|
| `scripts/Invoke-AstraStage2ControlIdentityBinding.ps1` | `f13aacaa75c5fba4c03b737502f61b5e4e5e8b5a701f06c2275c511c2943db19` |
| `scripts/Invoke-AstraStage2CheckpointRetry.ps1` | `e31380420a30b8c7b16319fd47bf4c15c651eae43da78643df650febec199be8` |
| `scripts/astra_stage2_bind_controls.ps1` | `8fb8bf02c13348e6d078aa0e55e5042feba53adbdd470c662f1950e60dad467a` |

The canonical generated Preflight template SHA-256 is
`44651e71409e53239e343d0656ed047270005a57279eafdcb2d226da9db403ba`.

A disposable native-Windows hardware-probe diagnostic selected NVIDIA device
index 1 and produced schema v2 with topology command exit `255`,
`NVIDIA_TOPO_MATRIX=UNSUPPORTED_ON_PLATFORM`,
`TOPOLOGY_CLASS=UNKNOWN`, zero model calls, zero provider calls, and
`binding=NOT_RUN`. It preserved the unsupported-command text. Its exact temp
directory was removed after verification and is not successor evidence.

## Remaining gates

This candidate is not qualified, published, or checkpointed. It still requires:

1. qualification on a clean Linux checkout;
2. an independent named-wrapper and platform-contract audit;
3. a new immutable checkpoint bound to the audited exact head and tree; and
4. a new real-host Preflight followed by `Prepare -SkipDownloads`.

Only the fourth gate may create the current four-artifact terminal. It must
reuse the exact assets, bind the successor Preflight SHA-256, stop at
`ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND`, and preserve zero calls,
zero binding, no calibration, and no numeric freeze.

