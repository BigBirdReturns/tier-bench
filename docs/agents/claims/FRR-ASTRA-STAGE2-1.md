# FRR-ASTRA-STAGE2-1 — Sol Stage 2 calibration law

```yaml
id: FRR-ASTRA-STAGE2-1
owner: sol
lane: driver
state: LAW_WINDOWS_TOPOLOGY_AMENDMENT_CANDIDATE
claim_id: FRR-ASTRA-STAGE2-2-LAW
claim_comment: 5516294861
branch: sol/astra-stage2-law-20260902
law_parent_head: 60bca963d63edca267106bc5c7725c2cc1df8dd7
law_parent_tree: 1ffaf5b1edc7a1a6ae63ffd8ecd2b43b1a87ff8a
qualified_scaffold_head: 9babad4631ef517485c56ea4906aab123e30fad7
qualified_scaffold_tree: 720cbf3f26f2e251613acedc52cff08ef33892dc
stage1_join_head: 60bca963d63edca267106bc5c7725c2cc1df8dd7
owned_path: docs/agents/claims/FRR-ASTRA-STAGE2-1.md
provider_calls: 0
model_calls: 0
spend_usd: 0
empirical_calibration: NOT_RUN
numeric_stage2_freeze: NOT_ISSUED
callable_astra_identity: UNBOUND
live_provider_dispatch: PROHIBITED
optional_24_call_block: DISABLED
merge_authority: NONE
```

## 1. Disposition and authority

This document is the Stage 2 law required by the two-stage freeze in
`experiments/astra_kxr/PREREGISTRATION.md`. It freezes the calibration sources,
the deterministic generator and reconstruction identities, the normalized
feature and separation rules, the evidence contract, and the implementation
mandate for the successor Spark runtime.

It does **not** contain an empirical calibration atlas, numeric thresholds, an
Astra model binding, provider credentials, or permission to dispatch any model.
The exact-head qualification of the admitted scaffold is provider-free and is
not empirical evidence. A future local calibration may produce an
`EMPIRICAL_CALIBRATION_CANDIDATE`; neither that candidate nor this law may
self-freeze numeric thresholds. Freeze authority remains separate and absent.

Stage 1 remains controlling. This law may fill only the fields marked
`stage_2_numeric: pending` and freeze generator implementations. It may not
alter Stage 1 hypotheses, terminals, admission gates, endpoints, the
waterline-before-geometry order, or the two-stage-freeze rule. Any such change
requires a new preregistration identifier.

## 2. Exact calibration-source identities

The following public coordinates identify the intended calibration classes.
They do not by themselves establish the bytes executed by a local runtime.

| control role | class | public source repository and commit | public checkpoint and revision | present evidence class |
|---|---|---|---|---|
| `lotus_3b_recurrent` | recurrent-latent positive control | `yingfan-bot/lotus@eb77e2f7909c5006f58ff0ad7cd6629b942caa9e` | `yingfanbot/gsm-lotus-llama3b@b392d2cb7aaa73475b93028221523c47f49f66a2` | `PUBLIC_SOURCE_IDENTITY_ONLY` |
| `loopcoder_v2_7b_parallel` | parallel-latent positive control | `CSJianYang/LoopCoder@ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c` | `Multilingual-Multimodal-NLP/LoopCoder-V2@b87cf3aa2186937b0d0362a684d7d30f234543e3` | `PUBLIC_SOURCE_IDENTITY_ONLY` |
| `conventional_transformer_negative` | matched conventional-transformer negative control | `yingfan-bot/lotus@eb77e2f7909c5006f58ff0ad7cd6629b942caa9e` | `yingfanbot/gsm-cot-llama3b@63de1ec1902ed143fe62250b6ddb14cb65f06e1a` | `PUBLIC_SOURCE_IDENTITY_ONLY` |

The source basis is LOTUS, arXiv `2606.31779`, and LoopCoder-v2, arXiv
`2606.18023`, plus the immutable repositories and checkpoint revisions above.
The conventional control is the LOTUS project's plain chain-of-thought Llama
3B checkpoint so that the recurrent and conventional roles share the closest
available public project lineage and scale.

LoopCoder-v2's released checkpoint has its own fixed architecture. Published
loop-count behavior is calibration-class background; it must not be
misrepresented as an observed sweep unless the exact executed checkpoint and
runtime actually expose and bind that intervention. Likewise, task-level `R`
below is dependent transformation depth in the frozen stimulus, not an
unverified claim about any control's internal loop count.

### 2.1 Executable identity gate

Before a control may produce an empirical observation, its private control
manifest must bind all of the following with canonical, content-addressed
values:

- control role and architecture class;
- source repository and exact commit;
- checkpoint repository and exact immutable revision;
- model configuration SHA-256;
- tokenizer corpus/configuration SHA-256;
- weight-index SHA-256 and the ordered SHA-256 of every weight shard;
- runtime name, version, build, configuration, and immutable digest;
- adapter/patch identity and SHA-256, or an explicit `NONE`;
- quantization identity and parameters, or an explicit `NONE`;
- hardware class, device count, memory class, driver, and execution topology;
- local artifact-set digest computed over the ordered content manifest; and
- the exact law blob, Stage 1 head, scaffold head, generator manifest, and
  calibration-plan identities used by the run.

Environment variables, a model display name, a mutable branch/tag, a path, a
download timestamp, or an internally consistent self-hash is not an executable
identity. A null, omitted, mutable, mismatched, or role-substituted field makes
the control `UNBOUND` and its observations inadmissible. Private paths and raw
model bodies remain private; public evidence carries immutable digests,
evidence classes, and bounded conclusions only.

At this release boundary all three controls are executable-identity `UNBOUND`.
No local empirical atlas receipt has been supplied or admitted.

### 2.2 Platform-dispatched hardware evidence

Hardware evidence must describe the platform that actually executes the
control. A collector may not require a command supplied only by another
platform, reshape unrelated native output into that command's format, infer
that an accelerator is absent from an unsupported subcommand, or change the
execution venue to obtain a preferred evidence shape.

On Linux, the NVIDIA evidence contract continues to require a successful
device inventory query and the exact successful output of `nvidia-smi topo
-m`. A failed or unavailable topology matrix is a hard refusal on Linux.

On native Windows, the evidence bundle must contain all of the following:

- a successful NVIDIA inventory query binding index, product name, UUID, PCI
  bus identity, memory, and driver;
- a successful NVIDIA PCI link query binding index, PCI bus identity,
  negotiated link generation, and negotiated link width;
- the attempted `nvidia-smi topo -m` command, exit status, stdout, and stderr;
- present Windows display-class PnP devices with instance identity, class,
  product name, status, bus number, address, location information, location
  paths, and a bounded parent chain; and
- present Thunderbolt or USB4 candidates and their observable PnP identities
  and parent relationships.

The primary NVIDIA inventory and PCI link query must resolve the same selected
indices and PCI bus identities exactly. Each selected device must resolve to
one present, healthy Windows display-class PnP device whose bus number and
address agree with its NVIDIA PCI coordinate. A failed supported NVIDIA query,
missing required native evidence, ambiguous resolution, or contradictory
device identity is a hard refusal.

Native Windows may record `NVIDIA_TOPO_MATRIX=UNSUPPORTED_ON_PLATFORM` only
when the attempted topology command returns the recognized native-Windows
unsupported-command response. The raw failure remains evidence. Collection
then continues from the mandatory native bundle. If that bundle proves an
admitted complete root-path or transport relationship, the receipt may record
that proved class. Otherwise it must record `TOPOLOGY_CLASS=UNKNOWN`. An
honest `UNKNOWN` is sufficient for provider-free Prepare, but it is not a
positive topology claim and does not by itself bind an executable identity for
empirical calibration.

Hardware probing, including the Windows fallback, performs zero model calls,
zero provider calls, zero binding, and no empirical calibration. Prepare must
preserve those stop walls.

## 3. Frozen generator and reconstruction identity

The generator is frozen to the admitted, exact-head scaffold at
`9babad4631ef517485c56ea4906aab123e30fad7`, tree
`720cbf3f26f2e251613acedc52cff08ef33892dc`. The implementation identities are:

| component | Git blob |
|---|---|
| `astra_stage2/generator.py` | `45f23fe0c2f7062dccfa9de8b267036a59f53726` |
| `astra_stage2/canonical.py` | `96f1e61bfe01daba44507a66d5ed231f4c45b9fb` |
| `astra_stage2/contracts.py` | `ba7516b293d7c16230f8170a9e7932c65892876c` |
| `astra_stage2/calibration.py` | `fcbdb8bcf3199bde33dea9342c3feff79f464d3d` |
| `experiments/astra_kxr/stage2/generator-manifest.index.json` | `a7b79543c1c03d43aeaa53471d4f865a809aa4fd` |
| `experiments/astra_kxr/stage2/calibration-plan.fixture.index.json` | `782f3cb888eb99626575c2c7d82e793fe7c6b21f` |

The frozen generator coordinate is:

```text
schema                    tier-bench/astra-stage2-generator-manifest@1
generator_version         astra-stage2-generator-v1
payload_sha256            2050de80cb4688b182cf9e006a97959da422dce24138c6451774f03320517328
families                  pointer_chase, coupled_ring, branch_reconcile
K                         1, 8, 32
R                         1, 4, 16
effort                    low, high
replicates                0, 1, 2, 3
lane_count                32
table_size                16
cases                     108
control roles             3
planned observations      648
feature samples           36
```

The verifier must regenerate every task and expected checksum from the frozen
implementation and compare the complete 108-case manifest. It must reconstruct
every observation identifier from the frozen case, control, effort,
generator-manifest, and control-manifest coordinates. Derivation and result
validation require the complete generator, control, plan, observation, and
Stage 1 graph. An observation subset, widened denominator, alternate generator,
changed manifest, replayed observation set, fabricated nested result, or result
validated without the complete input graph is refused.

## 4. Empirical transaction and atlas receipt

An empirical calibration transaction is admissible only when one control
manifest binds all three executable identities under §2.1 and one complete
plan binds the frozen generator under §3. The transaction is exactly:

```text
3 families × 3 K levels × 3 R levels × 4 replicates = 108 cases
108 cases × 3 controls × 2 effort labels             = 648 observations
3 controls × 3 families × 4 replicates                = 36 feature samples
```

The two effort labels are the frozen labels `low` and `high`. A runtime must
predeclare the concrete control-specific mapping for both labels. The mapping
must be nonzero, supported, stable within a control, and recorded in its
executable identity. If a control cannot expose two truthful and comparable
effort settings, the atlas is `CALIBRATION_INCONCLUSIVE`; silently substituting
sampling, prompt length, task depth, or a different checkpoint is prohibited.

Execution is concurrency one, without retries inside measurement cells, with
identical sampling parameters and fixed output length across matched cells.
Provider-reported input tokens must be identical across matched cells; byte
equality alone is insufficient. Response model and backend fingerprint must be
stable within a block. Violating cells are invalidated before analysis and
listed; they may not be patched, imputed, or replaced in-place.

Every observation binds the exact request bytes/hash, task/case identity,
control identity, effort mapping, block and order, request start, first response
header, first SSE event, first visible token, final token, inter-event times,
total latency, deterministic correctness, input/cached/output/reasoning token
counts, stop state, response-side model, backend fingerprint when present,
selected processing/rate-limit headers, and authenticated request identifiers.
Local transports may encode equivalent events differently, but the receipt must
state the mapping and preserve the raw local evidence in private custody.

The future atlas receipt must bind:

- this law's exact Git blob;
- Stage 1 join head `60bca963d63edca267106bc5c7725c2cc1df8dd7`;
- qualified scaffold head/tree `9babad4631ef517485c56ea4906aab123e30fad7` /
  `720cbf3f26f2e251613acedc52cff08ef33892dc`;
- generator, control-manifest, plan, ordered observation-set, feature-sample,
  result, invalidated-cell-ledger, and private evidence-root digests;
- all executable control identities; and
- the verifier version, command, exit status, timestamp, and custodian.

There is no atlas receipt at this boundary. The only lawful current state is
`EMPIRICAL_CALIBRATION_NOT_RUN`.

## 5. Frozen normalized feature law

Absolute timings are never transferable from local serving to a provider
fleet. Features are computed separately for each `(control, family, replicate)`
from its complete 3×3×2 `K×R×effort` lattice. Latency and TTFT must be positive.
Token vectors must satisfy the scaffold's matched-cell contracts.

For positive values `high`, `low`, and level ratio `q`, define:

```text
log_ratio(high, low, q) = ln(high / low) / ln(q)
```

For each effort and fixed K:

```text
r_elasticity sample        = log_ratio(L[K,16], L[K,1], 16)
r_monotonic step           = 1 if L[K,4] > L[K,1], and 1 if L[K,16] > L[K,4]
r_nonmonotonic peak        = 1 if L[K,4] > L[K,1] and L[K,4] > L[K,16]
token residual R contrast  = (L[K,16] - L[K,1]) / median latency of the effort block
```

For each effort and fixed R:

```text
first K slope              = log_ratio(L[8,R], L[1,R], 8)
second K slope             = log_ratio(L[32,R], L[8,R], 4)
k_elasticity sample        = log_ratio(L[32,R], L[1,R], 32)
k_curvature sample         = second K slope - first K slope
```

For each K×R coordinate:

```text
effort_ttft sample         = (TTFT[high] - TTFT[low]) / TTFT[low]
```

The eight feature values for a feature sample are exactly:

- median of the six R-elasticity samples;
- median of the six K-elasticity samples;
- median of the six K-curvature samples;
- mean of the twelve R-monotonic-step indicators;
- mean of the six R-nonmonotonic-peak indicators;
- median of the six token-residual-R contrasts;
- median of the nine effort-to-TTFT samples; and
- minimum exact-acceptance indicator over all 18 observations.

Each control contributes exactly twelve feature samples: three families by
four replicates. For every control and feature, the envelope contains minimum,
linearly interpolated q10, median, linearly interpolated q90, maximum, and
sample count 12.

## 6. Separation and threshold law

Candidate numeric thresholds may be derived only from complete empirical-local
evidence. For a directed comparison `(higher, lower, feature)`, separation is:

```text
higher.lower_q10 > lower.upper_q90
margin           = higher.lower_q10 - lower.upper_q90
threshold        = (higher.lower_q10 + lower.upper_q90) / 2
```

The complete required separation set is:

| feature | higher class | lower class |
|---|---|---|
| `r_elasticity` | `lotus_3b_recurrent` | `conventional_transformer_negative` |
| `token_residual_r_contrast` | `lotus_3b_recurrent` | `conventional_transformer_negative` |
| `r_nonmonotonicity` | `loopcoder_v2_7b_parallel` | `conventional_transformer_negative` |
| `k_curvature` | `loopcoder_v2_7b_parallel` | `lotus_3b_recurrent` |

The accuracy gate requires the minimum `accuracy_floor` across all three
controls and all samples to equal `1.0`. All four directed comparisons and the
accuracy gate must pass. Otherwise the empirical result is
`CALIBRATION_INCONCLUSIVE` with an empty threshold map. Synthetic fixture data
always returns `FIXTURE_CONFORMANCE_ONLY` with an empty threshold map, even if
its envelopes separate.

A complete passing local run may return only
`EMPIRICAL_CALIBRATION_CANDIDATE`. It carries the four midpoint thresholds and
all envelopes, checks, bindings, and payload digests, but
`stage2_frozen: false`. No candidate may self-freeze. A separate authority must
admit the atlas receipt, bind the exact law/runtime blobs, and publish the
numeric freeze before an Astra subject call becomes lawful.

## 7. Waterline, roles, and budgets

The campaign order is waterline before geometry. H1, H3, H6, and the measured
lesson that settled work belongs at the floor govern routing. Geometry captured
on a justified subject call may explain a measured residue; it is never an
excuse to call a frontier subject on a cell already cleared below.

Role bindings are semantic roles, not identities:

| role | boundary |
|---|---|
| LOTUS 3B | local recurrent calibration control; exact source coordinates in §2; executable identity unbound |
| LoopCoder-v2 7B | local parallel-latent calibration control; exact source coordinates in §2; executable identity unbound |
| conventional transformer | local negative calibration control; exact source coordinates in §2; executable identity unbound |
| Fable current | waterline comparison role; must bind an exact callable identifier in a private manifest |
| Fable 5.1 | successor comparison role; must bind an exact callable identifier in a private manifest |
| Sol current | waterline comparison role; must bind an exact callable identifier in a private manifest |
| Kimi K3 | open-weight observatory role; local presence or a name does not prove complete executable custody |
| deterministic control | frozen generator/checksum oracle; never a model subject and never self-grading |
| Astra placeholder | unbound subject role; no callable identifier exists in this law |

The waterline trial quorum is governed by the active model-waterline protocol,
not by task width `K`; implementations must name these separately. One attempt
is made per justified rung, effort is walked before access, a single miss is
noise rather than a wall, settled cells are never rerun, and no engine awards
itself a verdict. The deterministic verifier supplies correctness.

At law release the resource ceiling is zero provider/model calls and USD 0.
Local empirical calibration remains prohibited until all three controls bind.
The Stage 1 Astra launch sentinel, if later authorized after numeric freeze, has
72 subject calls plus eight reserved controls under an 80-request ceiling.
The separate optional 24-call block is disabled and cannot be inferred from
unused capacity. One lawful campaign does not authorize another.

## 8. Subject analysis and refusal law

After a lawful numeric freeze and exact callable Astra binding, the four Stage
1 analyses remain the only analyses: the K×R lattice, effort staircase,
token-compute residual, and continuation-reuse probe. The continuation probe's
primary endpoint is accuracy at matched cached-token counts and byte-identical
reconstructed transcript; latency is secondary.

Reported reasoning tokens are a condition, not ground truth. A
`RECURRENT_DEPTH_CONSISTENT` terminal requires R-sensitive residual growth at
approximately constant truthful reported reasoning tokens. If the field is
absent, quantized, summarized, or internally inconsistent, the strongest
admissible R-sensitive terminal is
`HIDDEN_SERIAL_OR_RECURRENT_INDISTINGUISHABLE`.

Exactly one Stage 1 terminal is returned per campaign:

```text
TOKEN_SERIAL_CONSISTENT
RECURRENT_DEPTH_CONSISTENT
PARALLEL_WIDTH_CONSISTENT
ROUTED_OR_ENSEMBLE_CONSISTENT
HIDDEN_SERIAL_OR_RECURRENT_INDISTINGUISHABLE
INCONCLUSIVE
```

No single latency curve carries an architecture claim. Non-`INCONCLUSIVE`
promotion requires a confirmatory campaign with additional seeds, task
families, and time blocks; at least two task families must reproduce. Parallel
promotion additionally requires an R-sensitive residual surface, K-flat
behavior below an estimated knee, stable route identity, and preserved
accuracy below the knee. An out-of-distribution shape returns `INCONCLUSIVE`;
forcing it into a known class is prohibited.

The implementation must refuse, without minting PASS or FAIL, on any of:

- missing or mutable control identity;
- incomplete, widened, duplicated, replayed, or reordered denominator;
- task, expected-answer, plan, observation, manifest, Stage 1, law, or runtime
  binding mismatch;
- absent complete input graph during derivation or result validation;
- fabricated nested result or acceptance of a self-hash as custody;
- retry, route drift, concurrency, token-parity, output-length, or sampling-gate
  violation not recorded as an invalidated cell;
- fixture data presented as empirical evidence;
- private raw body/path disclosure in public evidence;
- an empirical candidate presented as a numeric freeze;
- an unbound Astra alias presented as a callable identity; or
- provider dispatch before every preceding authority gate is satisfied.

Null and inconclusive results publish through the same release and readback
path as positive results.

## 9. Spark implementation mandate

The successor runtime branch is `spark/astra-stage2-runtime-20260902`. It may
implement only under its own active claim and owned paths. It must:

1. bind this document's exact Git blob, not a path or paraphrase;
2. bind the Stage 1 join and qualified scaffold head/tree in §§1 and 3;
3. preserve or explicitly verify the six frozen implementation blobs in §3;
4. require the complete executable control manifest in §2.1;
5. reconstruct the complete 108/648/36 graph and enforce all semantic-custody
   refusals already qualified at the parent head;
6. implement the exact feature, envelope, separation, and accuracy rules in
   §§5–6 without a second numeric interpretation;
7. emit separate private custody and public bounded receipts;
8. keep fixture, empirical-candidate, numeric-freeze, and subject-execution
   authorities mechanically distinct;
9. qualify provider-free first, then run local calibration only after identity
   binding and separate authorization; and
10. prohibit provider/model dispatch, Astra calls, the optional 24-call block,
    and numeric freeze until their own explicit gates and authorities exist.

If any source identity, generator blob, law blob, manifest coordinate, or
receipt graph differs, Spark must refuse and request a new versioned law or
claim. It may not repair the discrepancy by accepting semantic equivalence.

## 10. Closure packet

```text
requested outcome          freeze and publish the Sol Stage 2 calibration law
authority                  operator continuation of issue #172 claim 5516294861
burden holder              Sol driver
evidence                   this one-path Git blob plus exact release/readback
verifier                   Git object identity and remote readback
gap                        empirical executable identities and atlas are absent
closure decision           LAW COMPLETE; EMPIRICAL CALIBRATION NOT STARTED
failure default            UNBOUND / CALIBRATION_INCONCLUSIVE / INCONCLUSIVE
```

The control question is answered narrowly: private local calibration evidence
may become public law only through immutable source identities, complete
content-addressed execution identities, normalized shape features, bounded
receipts, and fail-closed reconstruction. No private path/body, absolute local
timing, unbound model name, fixture pass, or internally consistent self-hash is
allowed to substitute for that custody.
