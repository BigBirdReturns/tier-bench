# CART0 Select/Compose bridge — usable payload reduction today

Status: **strict deterministic repair under `CART0-PROFILE-1`**. The original
`CART0-BRIDGE-1` payload bridge and failed B4 receipts remain preserved. The
repair is still a local proposal/test harness: it does not authorize provider
dispatch, gated changes, production signing, or benchmark/context-window
verdicts.

## Grounding and the actual missing bridge

This is not a new memory store and not semantic RAG. The authoritative Genesis
paper, `axm-genesis-frozen-cryptographic-kernel-v0.6.pdf` (SHA-256
`a1c4987a459c74852af705cf06d095b809d342d1cd79813959c7456032004c83`),
defines `Store -> Select -> Compose -> Process -> Output` (§3.3), deterministic
query over a verified shard (§§3.2, 6.5), compile-time LLM use (§8.3), and the
query-time cost shift (§§7.3.3, 8.4). It also warns that a seal preserves a poor
extraction faithfully (§9).

The CART0 contract supplies the specialization: actor-relative position,
objective and prohibitions, a freshness commitment, retrieval pointers,
mechanical transition dispatch, and decision-point resurfacing.

The smallest missing executable bridge is therefore:

1. **Store:** ordinary source files at one Git `event_head`.
2. **Compile/admit:** bounded, revisioned projection candidates with exact
   source spans are admitted only through separate review receipts.
3. **Select:** an independent `cart0@1` transition profile maps a boundary to
   required card revisions/authority IDs and allowed principal/role/lane sets.
   Cards contain data only and cannot select or authorize themselves.
4. **Compose:** a <=256-token-proxy CART0 anchor plus the selected bounded cards.
5. **Process/Output:** outside this harness; the composed payload is pasted into
   the agent. Source spans are rehydrated only on an explicit card lookup.

Projection identity is bound as the CART0 contract requires:
`hash(event_head, reducer_digest, projection_profile_digest)`. Every selected
card carries a stable Dewey-style ID, revision, supersession link, hard
proxy-token budget, Git blob/source/span hashes, and line pointers. Authority,
admission, actor applicability, transition dispatch, and freshness come only
from the external profile and receipts. Relevant evidence, reducer, profile,
review, anchor, or card drift refuses verification. Unrelated Git commits do
not invalidate the evidence-derived project event head.

Current custody is deliberately weaker than Genesis: the receipt is Git-object
and SHA-256 bound, **not a Genesis-signed shard**. The existing Genesis code that
should replace this provisional custody layer is precise and reusable:

- `axm-genesis/src/axm_build/compiler_generic.py`: strict evidence-span matching,
  canonical tables, signing, and compile-then-verify;
- `axm-genesis/src/axm_verify/logic.py`: manifest/signature/Merkle/source-bijection,
  byte-range, span-text, schema and identity verification;
- `axm-genesis/src/axm_verify/identity.py`: derived stable identifiers;
- `axm-genesis/src/axm_verify/cli.py`: fail-closed local verification.

Direct use is not hidden behind this prototype: the bundled runtime currently
lacks `blake3`, and a trusted signer/custody policy plus a queue-authorized CART0
profile are required. The repository's `examples/query_shard.py` is also a
Parquet example while the current verifier/compiler operates on canonical
JSONL, so it is not copied as-is.

ScreenGhost-like capture, Ghostbox-like isolation, and Console review/actuation
remain surfaces around this bridge. They are not made into authority or storage
primitives here.

## Exact commands to use today

Run from the isolated proposal worktree:

```powershell
Set-Location 'C:\Users\BAM-Desktop\Documents\Residue\.codex-worktrees\cart0-anchor-prototype'
$py = 'C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$out = Join-Path $env:TEMP ('cart0-bridge-' + [guid]::NewGuid().ToString('N'))

& $py scripts/cart0_anchor.py build --repo . `
  --spec experiments/cart0_anchor_prototype/task_state.json `
  --catalog experiments/cart0_anchor_prototype/cards.json `
  --profile experiments/cart0_anchor_prototype/transition_profile.json `
  --out $out --boundary implementation_start --max-approx-tokens 256

& $py scripts/cart0_anchor.py verify --repo . --bundle $out

& $py scripts/cart0_anchor.py resurface --repo . --bundle $out `
  --boundary implementation_start `
  --task 'Continue the current task under the selected authority and constraints.' `
  --out (Join-Path $out 'prompt.txt')

Get-Content -Raw (Join-Path $out 'prompt.txt')
```

If a selected card is insufficient, rehydrate only its pinned source spans:

```powershell
& $py scripts/cart0_anchor.py rehydrate --repo . --bundle $out `
  --card-id 010.100.CART0 `
  --out (Join-Path $out 'rehydrated-010.100.CART0.txt')
Get-Content -Raw (Join-Path $out 'rehydrated-010.100.CART0.txt')
```

Recompile/admit a new profile revision after relevant evidence, reducer, review,
or policy changes. Use a boundary-specific bundle; the wrong boundary refuses.

## Reproduce the measured A/B and tests

```powershell
$py = 'C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tests/test_cart0_anchor.py

$b4 = Join-Path $env:TEMP ('cart0-b4-' + [guid]::NewGuid().ToString('N'))
& $py experiments/cart0_anchor_prototype/run_profile_conformance.py --out $b4

$ab = Join-Path $env:TEMP ('cart0-ab-' + [guid]::NewGuid().ToString('N'))
& $py scripts/cart0_anchor.py ab-demo --repo . `
  --spec experiments/cart0_anchor_prototype/task_state.json `
  --catalog experiments/cart0_anchor_prototype/cards.json `
  --profile experiments/cart0_anchor_prototype/transition_profile.json `
  --out $ab --boundary implementation_start `
  --task 'Implement and verify the opt-in CART0 Select/Compose bridge without crossing gated boundaries.'
Get-Content -Raw (Join-Path $ab 'ab_receipt.json')
```

The initial proposal-worktree run remains preserved at
`experiments/cart0_anchor_prototype/run_genesis_bridge_20260714/`. The
claimed-state run at
`experiments/cart0_anchor_prototype/run_claimed_bridge_20260714/` binds the
same harness to reachable implementation commit `88e5bfb49bc8`, with raw
inputs, both exact prompt payloads, the compiled bundle, rehydrated evidence,
and refusal receipts. Its `ab_receipt.json` SHA-256 is
`077df6d6ede86535d2cb345f5ced4920c87bd33401e25241a584cc66c615b248`.

## Measured result (one local projection A/B)

Baseline A loaded the five full, pinned current-state files. B carried the same
task plus a 231-token-proxy anchor and four deterministically selected cards.

| Measure | A full context | B anchor + cards | Saved |
|---|---:|---:|---:|
| UTF-8 bytes | 50,320 | 2,623 | 47,697 |
| `ceil(bytes/4)` proxy | 12,580 | 656 | 11,924 |
| whitespace tokens | 6,666 | 287 | 6,379 |

Measured payload reduction: **94.7874%**. End-to-end local harness wall time,
including build, repeated verification, raw writes, and two refusal probes:
**6,595.959 ms**. Individual cards used 89/128, 76/96, 106/128, and
93/112 proxy tokens. The anchor itself used 231/256.

The run also demonstrated fail-closed behavior for an unknown card ID and a
tampered card. The test suite separately demonstrated stale-HEAD, wrong-boundary,
unsafe-path, and revision-gap refusal: 3/3 test groups passed, zero model calls.

## Repair boundary and residual risk

The strict profile mechanically refuses missing required authority/cards,
principal/role/lane mismatch, stale project event head, reducer/profile drift,
unaccepted or missing review evidence, card self-selection fields, unavailable
source spans, projected-byte tampering, and inactive lookup. Rehydration uses an
explicit `untrusted-source-evidence` envelope with
`INSTRUCTION_AUTHORITY: false`.

Two boundaries remain deliberately uncryptographic. A mistaken or malicious
reviewer/publisher can admit and sign a semantically false summary; signatures
prove byte integrity and publisher identity, not truth. Quarantine labels and
runtime policy also cannot prove that a later LLM will ignore a malicious source
instruction. The repair therefore requires admission evidence and quarantine,
records both proof flags as false, and includes positive residual-risk vectors;
it does not claim semantic proof.

## Blunt limit

Demonstrated: this deterministic bridge placed 47,697 fewer bytes (11,924 fewer
`bytes/4` proxy tokens) into one representative prompt while retaining explicit
control state, selected compiled claims, and on-demand source pointers.

Not demonstrated: actual provider-token billing, equal answer quality, successful
task completion, fewer model output tokens, cross-session continuity, production
Genesis custody, semantic truth, instruction safety, or a general context-window
solution. The current admissions are explicitly `driver-reviewed` test-proposal
evidence, not production approval. B1/model quality work requires a separate
committed provider/model experiment row after this repaired B4 rung and its
positive vectors pass. Production Genesis integration remains outside
`CART0-PROFILE-1`.
