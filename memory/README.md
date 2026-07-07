# memory/ — rent the horizon you can't hold

**Horizon is the frontier residual, and it is a memory problem.** The ten
disposition probes (`data/control-results/`) all test *local* judgment — is there
a trap in the frame you're already looking at — and that is flat on effort. The
edge they *don't* catch is **horizon**: holding the global frame while a long run
of local work drags attention off it. An invariant stated 80k tokens ago has left
the window; even a frontier model starts chasing the rolling context instead of
the plan. You do not fix that with a bigger model — you lose the race
asymptotically. You fix it by putting the frame **outside** the model, in memory
it *queries*.

This directory is that memory. It is the industrial version of what
`driver/policy/` does by hand.

## The upgrade

| | `driver/policy/` (the toy) | `memory/` (industrial) |
|---|---|---|
| what it captures | the driver's plan for a task class | every decision of a whole session |
| form | ad-hoc `policy.json` | a signed **decision shard** (AXM Genesis v1) |
| provenance | a `support` count | every claim bound to **exact source bytes** |
| trust after a year | "trust me" | Merkle root + post-quantum signature, verify offline |
| tamper-evidence | none | flip one byte → verification **fails** |
| retrieval | exact-match dict lookup | deterministic SQL over the whole corpus |

Both answer the same question — *what happens when the frontier model
disappears?* — but the shard is the version you can still trust when the platform
that made it, the vendor that hosted it, and the company that built the tooling
are all gone. That is the whole point of the AXM kernel this rides on
(`axm-genesis` / `axm-core` / `axm-chat`).

**Why it has to be *this* memory, not a vector-DB blob:** naive RAG retrieves a
paraphrase and the model trusts it — it hallucinates the frame back *wrong*, which
is the exact failure horizon was supposed to fix. Here, retrieval is deterministic
SQL and every returned claim carries its exact source bytes and a verify path. The
memory **cannot drift, because provenance is cryptographic.**

## The loop

```
convert   memory/transcript_to_export.py SESSION.jsonl -o export.json   (stdlib, no deps)
import    axm-chat import export.json        → signed conversation shard (the literal utterances)
distill   axm-chat distill --model <tier3>   → decision shard (the decisions, each citing source bytes)
verify    axm-chat verify                    → Merkle + Ed25519‖ML-DSA-44, PASS/FAIL
query     axm-chat query "what was rejected"  → deterministic SQL, no model in the loop
```

`memory/seal_session.py` orchestrates it. Prereqs: the AXM toolchain on PATH
(`axm-genesis` + `axm-core` + `axm-chat`, plus `dilithium-py` for the ML-DSA-44
backend); distillation additionally needs a local Tier-3 model (Ollama). Import
and verify run without a model — distill is the one step that reads the
conversation to extract decisions.

## Proven, not hypothetical

This mechanism was dogfooded on the session that built it. The raw Claude Code
transcript — **106 verbatim utterances, ~348k tokens** — was sealed into a
conversation shard, then distilled into a decision shard of **11 decisions**,
each bound to exact bytes of the transcript. Both shards verify:

```
$ axm-chat verify
  ✓ PASS  tier-bench session (raw transcript): capability, disposition, horizon = memory
  ✓ PASS  decisions: … (11 decisions)

$ axm-chat query "what was rejected"
  project/design_tokens        rejected   hand_rolled_axm_tokens
  project/theme                rejected   light_only_ship
  project/capability_numbers   rejected   fabricating_without_a_run
```

Those three were real horizon failures in the session — the model lost the frame
(the design system, the theme convention, the honesty doctrine) and had to be
corrected. Now they are a **lookup, not a re-derivation**: the next model mounts
the shard, queries `what was rejected`, and inherits the frame instead of
repeating the mistake.

And the seal is honest end to end — tamper one byte of the sealed source:

```
$ axm-verify shard <tampered> --trusted-key publisher.pub
  E_MERKLE_MISMATCH: computed 78e4e0…, stored 18ae59…   (exit 1)
```

That exact decision shard is committed at **`memory/samples/decisions-this-session/`** —
verify and query it yourself (needs the AXM toolchain on PATH):

```
$ axm-verify shard memory/samples/decisions-this-session \
    --trusted-key memory/samples/decisions-this-session/sig/publisher.pub
  {"status": "PASS", "error_count": 0}
```

The bundled `publisher.pub` is a self-describing key for the sample; in real use
the trusted key arrives out of band (from a sibling `axm-genesis` checkout), never
from inside the shard.

## Honesty seams

- **Utterances, not machinery.** The converter seals what was *said* — user prose
  and assistant text — and drops tool calls, tool results, thinking, and injected
  reminders. The shard is the conversation, not the harness trace.
- **Verbatim or dropped.** A decision enters the shard only if its evidence is a
  verbatim substring of the sealed source. An anchor that doesn't match exactly is
  skipped, never fudged — the distill on this session dropped one such decision
  rather than bind it to bytes that weren't there.
- **The model only appears at distillation.** Query is deterministic SQL; nothing
  leaves the machine at read time. A distilled decision is a claim its extractor
  made, cryptographically bound to the source it was drawn from — not a
  vendor-verified fact until someone else reproduces it, the same doctrine the
  rest of tier-bench follows.
