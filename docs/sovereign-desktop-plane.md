# Sovereign Desktop Execution Plane

The Sovereign Desktop Execution Plane translates the infrastructure techniques used by large inference providers into an attention-first system for one operator, one desktop, two GPUs, local storage, and replaceable frontier services.

The desktop objective differs from the data-center objective. A commercial inference fleet optimizes throughput, latency percentiles, utilization, and service-level objectives across many tenants. This plane optimizes verified work per unit of operator attention. A local model may remain busy for hours when the work is bounded, the resource is available, the acceptance authority is external to the model, and the operator does not need to supervise it.

## What the industrial systems are doing

A nominally million-token model is rarely asked to reread every source byte, tool result, and prior turn from a cold start for every request. The production system reduces the effective long-context tax through several independent mechanisms:

| Industrial mechanism | Effect |
|---|---|
| Context selection and retrieval | Admit only the records relevant to the current task. |
| Stable prompt prefixes | Put reusable instructions, tools, and source material before changing request content. |
| Prompt or KV caching | Reuse exact processed prefix state instead of computing prefill again. |
| Context editing and compaction | Remove stale tool output and replace old interaction history with a bounded checkpoint. |
| External memory and tools | Keep durable state, files, databases, and intermediate computation outside the active model window. |
| Cache-aware routing | Send a request to the worker that already holds the compatible prefix state. |
| Prefill/decode disaggregation | Allocate different hardware pools to prompt processing and token generation. |
| Tiered KV storage | Move compatible cache state between GPU memory, host RAM, SSD, and remote storage. |
| Distillation | Convert expensive frontier behavior into a smaller model, adapter, scaffold, policy, or verifier. |

These mechanisms solve different costs. Prompt caching reduces repeated prefill compute and, on commercial APIs, repeated input billing. Context selection reduces the number of admitted tokens and often improves focus. Compaction controls horizon. External tools prevent intermediate results from inflating the conversation. Distillation changes the future route. Treating them as one generic “long context” feature makes their authority and failure modes impossible to inspect.

## Desktop translation

The first target topology is:

```text
AXM / Git / local files
  authoritative source estate
          |
          v
CPU + 4060 semantic-prefill lane
  index, retrieve, rank, compact, extract, vision
          |
          v
content-addressed context pack
  stable prefix + dynamic suffix + source receipt
          |
          +-----------------------+
          |                       |
          v                       v
3090 resident generator       frontier teacher
large local model             only after measured wall
          |                       |
          +-----------+-----------+
                      v
external acceptance, receipts, residue capture
```

The 4060 is not presented as a data-center prefill GPU that produces KV tensors for the 3090. KV state is model-, tokenizer-, runtime-, quantization-, and prefix-specific. Moving it between unlike local models would be invalid, and moving large compatible KV state over ordinary consumer interconnects may cost more than recomputing it. The 4060 therefore performs **semantic prefill**: retrieval, reranking, extraction, compaction, vision, and draft work that produces a source-bound context artifact. The 3090 performs the main local generation and training work.

True KV reuse in the first desktop slice occurs within one compatible local runtime. The plane supports a persistent `llama.cpp` slot-cache contract. A saved slot is restorable only when the model, tokenizer, runtime version, quantization, source revision, and exact stable-prefix fingerprint match the save receipt.

## The five long-context taxes

The execution plane keeps five ledgers rather than reporting one token count.

1. **Estate size.** The source bytes that were available.
2. **Selected context.** The bounded source material admitted to the task.
3. **Prefill compute.** Selected tokens that the runtime must actually process.
4. **KV residency.** VRAM, RAM, and storage occupied by reusable processed state.
5. **Operator attention.** Time spent selecting context, rescuing runs, resolving drift, and reviewing output.

The planner currently accounts estate tokens, selected tokens, planned prefill tokens, planned cache reuse, output tokens, model load time, and operator-defined routing. It does not invent quality gains or claim that planned cache reuse occurred. Runtime telemetry and cache receipts are required after execution.

## Content-addressed context packs

A context pack contains ordered blocks with four stability classes:

```text
estate
campaign
job
ephemeral
```

`estate` and `campaign` blocks form the reusable prefix. `job` and `ephemeral` blocks form the dynamic suffix. The validator refuses a pack that places dynamic material before stable material because that layout would destroy prefix reuse.

Each block records:

- source identity and revision;
- byte hash;
- declared token count;
- stability class;
- semantic kind;
- optional repository-relative content path;
- optional compaction provenance.

A compaction block is not accepted as an ungrounded summary. It must bind the bytes it covers, the compaction method, a validator hash, and the loss policy. AXM or Git remains the source authority; the compacted block is a derived acceleration artifact.

Materialization writes:

```text
<out-root>/<pack-fingerprint>/
  prefix.txt
  dynamic.txt
  pack-receipt.json
```

The prefix and suffix bytes use deterministic block headers. Their hashes, source revision, token accounting, and individual source-file hashes are sealed in the receipt.

## Exact cache compatibility

A reusable prefix key is computed from:

```text
model id
tokenizer id
runtime id
runtime version
quantization
source identity
source revision
ordered stable block ids
ordered stable block hashes
stable block token declarations
compaction provenance
```

Semantic similarity does not create a KV-cache hit. A runtime update, tokenizer change, quantization change, source revision change, or one-byte prefix change produces a different key.

The plan distinguishes three states:

| State | Meaning |
|---|---|
| `miss` | No compatible prior state is known. |
| `planned_after_prior_job` | An earlier job in the same deterministic plan is expected to warm the exact prefix. |
| `observed_inventory` | A prior save receipt is present in the manifest and matches the exact binding. |

All three remain planning evidence until execution telemetry confirms what the runtime reused.

## Attention-first scheduling

The scheduler observes the job DAG, privacy policy, required capabilities, context limits, resource capacities, and operator-declared runtime order. For `sovereign_preferred`, eligible local routes are considered before remote routes. For `local_only`, remote routes are inadmissible.

Within those constraints, the scheduler keeps work sharing one runtime and prefix adjacent. This deliberately trades elapsed time for:

- fewer model loads;
- fewer cold prefills;
- longer cache residency;
- less repeated context preparation;
- fewer operator returns.

Independent resources appear in parallel waves. A 3090 coding job and a 4060 extraction job can occupy the same wave. Two jobs contending for one GPU remain serialized unless the resource declares additional capacity.

## Frontier Residue Refinery handoff

A desktop job can be compiled into a draft Frontier Residue Refinery campaign when its runtimes have committed backend bindings. The local route runs first. A frontier route is permitted only after the lower route produces the campaign’s required decisive failure window, unless the operator deliberately selected survey mode.

The campaign carries the context-pack fingerprint and source revision. It still uses the existing `tier run` contract for isolated execution, external acceptance, patch custody, and receipts. Campaign compilation never starts a model.

## Persistent llama.cpp slot cache

The plane provides loopback-only slot save and restore controls around `llama-server`.

```console
tierplane cache-save ^
  --manifest experiments\sovereign_desktop\desktop_3090_4060.json ^
  --runtime qwen-local-3090 ^
  --pack tier-bench-example ^
  --server http://127.0.0.1:8080 ^
  --slot 0 ^
  --filename tier-bench-example.bin ^
  --state-dir .git\tier-plane

tierplane cache-restore ^
  --manifest experiments\sovereign_desktop\desktop_3090_4060.json ^
  --runtime qwen-local-3090 ^
  --pack tier-bench-example ^
  --server http://127.0.0.1:8080 ^
  --slot 0 ^
  --filename tier-bench-example.bin ^
  --state-dir .git\tier-plane
```

The controller records a save receipt under:

```text
.git/tier-plane/kv-cache-registry.jsonl
```

Restore refuses to proceed unless an observed save receipt matches the complete runtime and prefix binding. The cache file itself remains under the `llama-server --slot-save-path` directory. Non-loopback cache control is refused unless the operator explicitly enables `--unsafe-network`.

`--dry-run` emits the exact request and binding without contacting the server.

## Operation

Validate the example plane:

```console
tierplane validate ^
  --manifest experiments\sovereign_desktop\desktop_3090_4060.json
```

Compile and verify a deterministic plan:

```console
tierplane plan ^
  --manifest experiments\sovereign_desktop\desktop_3090_4060.json ^
  --out .git\tier-plane\plan.json

tierplane verify ^
  --manifest experiments\sovereign_desktop\desktop_3090_4060.json ^
  --plan .git\tier-plane\plan.json
```

Materialize one context pack:

```console
tierplane materialize ^
  --manifest experiments\sovereign_desktop\desktop_3090_4060.json ^
  --pack tier-bench-example ^
  --repo . ^
  --out-root .git\tier-plane\context

tierplane verify-context ^
  --directory .git\tier-plane\context\<pack-fingerprint>
```

Compile draft campaign files:

```console
tierplane campaigns ^
  --manifest experiments\sovereign_desktop\desktop_3090_4060.json ^
  --out-dir .git\tier-plane\campaigns
```

A job is emitted only when at least one eligible runtime has a committed backend binding. Nothing is queued automatically.

## What is implemented

The current slice implements:

- strict manifest validation;
- stable-prefix ordering;
- source-bound context materialization;
- exact runtime-prefix fingerprints;
- deterministic cache-aware batches;
- parallel resource waves;
- dependency-block propagation;
- privacy and capability routing;
- planned long-context tax accounting;
- draft Frontier Residue campaign compilation;
- loopback-only llama.cpp slot save and restore;
- persistent cache receipts;
- cache inventory export;
- zero-model-call tests.

## What remains

The next execution layers are concrete:

1. Bind the actual 3090 and 4060 model files, tokenizers, runtime builds, ports, and backend manifests on the Windows machine.
2. Record observed prefill, cache-read, generation, VRAM, RAM, disk, and wall-time telemetry.
3. Add a 4060 retrieval and compaction worker that emits these exact context-pack receipts.
4. Add a local OpenAI-compatible execution adapter that consumes the materialized prefix and dynamic suffix.
5. Evaluate `llama.cpp` slot checkpoints on the chosen Qwen model and context length.
6. Add a WSL2 `vLLM + LMCache` lane only if measured local KV offload and reuse beat the simpler `llama.cpp` route.
7. Feed every persistent frontier separation into the Desktop Distillation Lab.

The control question for each added optimization is whether it reduces accepted-work cost or operator attention on fresh tasks after its own complexity, cache invalidations, storage use, and failure modes are counted.
