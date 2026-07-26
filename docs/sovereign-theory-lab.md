# Sovereign Theory Lab

The Sovereign Theory Lab converts architectural intuition into prospective,
falsifiable desktop experiments. It sits beside the Sovereign Desktop Execution
Plane, Model Waterline Observatory, Frontier Residue Refinery, and Desktop
Distillation Lab.

Its job is not to prove that a technique is good. Its job is to freeze the
mechanism, control arm, treatment arms, task families, metrics, evidence floor,
confounds, support predicates, and falsifier before the machine produces results.

## Why this exists

Large inference providers reduce the effective long-context and frontier-model tax
with several distinct mechanisms:

- retrieval and context selection;
- stable prompt prefixes;
- automatic prefix or KV caching;
- cache-aware routing;
- model residency and continuous batching;
- prefill/decode disaggregation;
- RAM, disk, and distributed KV tiers;
- speculative decoding;
- frontier-to-student distillation.

The desktop has different economics. It lacks NVLink, RDMA, large HBM pools, and
large concurrent tenant traffic. It does have patient local compute, a 24 GiB
3090, an 8 GiB 4060, host RAM, NVMe, local source custody, external graders, and
one operator whose attention is more scarce than elapsed time.

The correct translation is therefore empirical. Each industrial mechanism becomes
a desktop theory. Some should survive directly. Some should survive only after a
change in mechanism. Some should be rejected because their data-center transport
assumptions do not exist on consumer hardware.

## Evidence law

A theory begins as a hypothesis. It can become supported or falsified only through
sealed observations.

A decisive observation requires:

1. a frozen task and external acceptance authority;
2. a declared arm and replicate;
3. requested and observed runtime identity that match;
4. runtime attestation and complete telemetry;
5. a pass or fail outcome;
6. a hash-bound receipt;
7. the metrics required by the lab.

Provider errors, transport failures, missing telemetry, fallback models, and
partial runs remain visible but do not count as pass or fail evidence.

A treatment is `SUPPORTED` only when every predeclared support predicate clears
and no falsifier clears. It is `FALSIFIED` when a predeclared falsifier clears
after the task and replicate floor is met. Missing evidence yields `PARTIAL` or
`UNMEASURED`.

## Registered theories

The v1 registry contains 22 theories.

### Context and cache

| ID | Question |
|---|---|
| H01 | Can semantic prefill preserve accepted work while eliminating most full-estate prefill? |
| H02 | Does stable-prefix ordering create the expected reusable processed context? |
| H03 | At what prefix length does persistent llama.cpp slot restore beat cold prefill? |
| H07 | When does pinned RAM beat recomputation as an evicted-KV hot tier? |
| H08 | Is NVMe useful only for very large, predictable, prefetched prefixes? |
| H09 | Can longest-common-prefix invalidation preserve early blocks across small source revisions? |
| H10 | What compaction ratio crosses each task family’s fidelity boundary? |
| H12 | Can uncertainty and evidence burden allocate context more efficiently than a fixed budget? |

### Scheduling and hardware roles

| ID | Question |
|---|---|
| H04 | Does cache-sticky scheduling reduce loads, prefills, and operator returns? |
| H05 | Does 4060 semantic prefill increase accepted output per 3090 second? |
| H06 | Can a 4060 draft model accelerate a compatible 3090 target through speculative decoding? |
| H18 | Where does WSL2 vLLM plus LMCache justify its added maintenance over llama.cpp slots? |
| H19 | Is true 4060-prefill/3090-decode tensor disaggregation uneconomic on consumer PCIe? |
| H20 | Can unattended local retries replace immediate frontier calls on bounded work? |

### Retrieval and evidence

| ID | Question |
|---|---|
| H11 | Do claim-lineage constraints improve embedding retrieval on evidentiary tasks? |
| H22 | Does context compiler quality explain more recurring-work variance than one model-size rung? |

### Composition and distillation

| ID | Question |
|---|---|
| H13 | Can local best-of-N plus an external grader replace one frontier attempt? |
| H14 | Does local attempt plus frontier repair beat direct frontier execution? |
| H15 | Do failure-and-repair traces teach more than final answers alone? |
| H16 | Can closed-teacher residue become teacher-independent local source machinery? |
| H17 | Do open weights or runtime source reduce capture burden versus behavioral artifacts? |
| H21 | Do disagreement-selected teacher calls beat random distillation examples? |

Each registry row contains the exact claim, proposed mechanism, quantitative
prediction, arms, task families, support predicates, falsifiers, confounds, and
failure default.

## Counterbalancing

The planner rotates arm order across tasks and replicates, then reverses alternating
neighbor relations. This balances first-position exposure without relying on
randomness or allowing post-result ordering changes.

Only tasks marked `ready` at plan compilation enter a run matrix. Prospective
operator tasks remain visible as missing evidence. A plan may produce calibration
runs while refusing a family-level settlement claim.

## Observation format

Observations are JSONL:

```json
{
  "schema": "tier-bench/sovereign-theory-observation@1",
  "theory_id": "H03-slot-restore-break-even",
  "run_id": "st-...",
  "task_id": "sd-slot-cache-replay",
  "arm_id": "slot-restore",
  "replicate": 1,
  "outcome": "pass",
  "runtime": {
    "requested": "qwen-local-3090",
    "observed": "qwen-local-3090",
    "attested": true,
    "telemetry_complete": true
  },
  "metrics": {
    "operator_minutes": 0.0,
    "wall_seconds": 18.4,
    "escaped_defects": 0,
    "restore_seconds": 6.2,
    "cold_prefill_seconds": 14.8,
    "prefill_compute_tokens": 0,
    "cache_read_tokens": 24000
  },
  "receipt_sha256": "<64 lowercase hex>",
  "notes": "Exact slot receipt matched."
}
```

The analyzer excludes a row from decisive evidence when a fallback runtime
actually handled the request.

## Operation

Validate the registry:

```console
tiertheory validate ^
  --lab experiments\sovereign_desktop\theories.json
```

Inspect the catalog:

```console
tiertheory catalog ^
  --lab experiments\sovereign_desktop\theories.json

tiertheory catalog ^
  --lab experiments\sovereign_desktop\theories.json ^
  --family cache-reuse
```

Compile the complete deterministic plan:

```console
tiertheory plan ^
  --lab experiments\sovereign_desktop\theories.json ^
  --out .git\tier-plane\theory-plan.json
```

Compile only selected theories:

```console
tiertheory plan ^
  --lab experiments\sovereign_desktop\theories.json ^
  --theory H03-slot-restore-break-even ^
  --theory H06-4060-speculative-draft ^
  --out .git\tier-plane\cache-and-speculation-plan.json
```

Verify that a plan still matches the frozen registry:

```console
tiertheory verify ^
  --lab experiments\sovereign_desktop\theories.json ^
  --plan .git\tier-plane\theory-plan.json
```

Emit non-evidentiary observation templates:

```console
tiertheory templates ^
  --lab experiments\sovereign_desktop\theories.json ^
  --plan .git\tier-plane\theory-plan.json ^
  --out .git\tier-plane\theory-observations.jsonl
```

Templates are deliberately marked `partial`, unattested, and unreceipted. They
cannot be mistaken for measurements.

Analyze sealed observations:

```console
tiertheory analyze ^
  --lab experiments\sovereign_desktop\theories.json ^
  --observations .git\tier-plane\theory-observations.sealed.jsonl ^
  --out .git\tier-plane\theory-report.json
```

## Initial execution order

The first experiments should minimize platform construction while producing
useful threshold data.

1. **H03 slot restore.** The current plane already has an exact llama.cpp slot
   contract. Sweep stable-prefix length and compare cold prefill with restore.
2. **H02 stable prefix.** Confirm that real runtime telemetry agrees with the
   planner’s prefix-accounting model.
3. **H04 cache-sticky scheduling.** Use the same jobs and resources under strict
   priority and cache-sticky ordering.
4. **H05 4060 semantic prefill.** Move retrieval, reranking, and compaction to the
   4060 while keeping the 3090 generator unchanged.
5. **H06 speculative draft.** Attempt only after a same-tokenizer draft and target
   pair fits the two cards with stable runtime support.
6. **H18 serving stack.** Install vLLM plus LMCache only after the simpler path has
   a measured cache pressure or concurrency wall.
7. **H19 tensor P/D disaggregation.** Treat this as a controlled attempt to reject
   an industrial mechanism whose transfer assumptions likely do not survive the
   desktop topology.

## Relationship to the existing estate

```text
Sovereign Theory Lab
  freezes the mechanism, arms, metrics, and falsifier
          |
          v
Sovereign Desktop Execution Plane
  binds hardware, runtime, context, cache, and jobs
          |
          v
Monster Wrangler / Frontier Residue Refinery
  execute bounded work and preserve receipts
          |
          v
Theory analyzer
  supports, falsifies, or preserves the open question
          |
          v
Desktop Distillation Lab
  acquires persistent frontier residue
          |
          v
Capture ledger
  closes only after reusable artifact bytes and distinct replays
```

## Industrial references

The registered theories are derived from mechanisms documented by the systems
they test against:

- NVIDIA Dynamo disaggregated serving and KV-aware routing:
  `https://docs.nvidia.com/dynamo/latest/user-guides/disaggregated-serving`
- vLLM automatic prefix caching:
  `https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/`
- LMCache CPU and local-disk KV tiers:
  `https://docs.lmcache.ai/`
- llama.cpp server and speculative decoding:
  `https://github.com/ggml-org/llama.cpp/tree/master/tools/server`
  and `https://github.com/ggml-org/llama.cpp/tree/master/examples/speculative`

Those systems establish that the mechanisms exist. They do not establish that the
mechanisms are beneficial on this desktop. That is the theory lab’s job.
