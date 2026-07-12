# OSS replay field — where captured grammars meet the wild (ARC-D)

The capture ledger (ARC-A) converts expensive cognition into artifacts and
amortizes them only through **validated replays on distinct work items** — the
same-instance rule forbids credit for repeats. The almanac corpus (ARC-B) and
the edge family supplied *synthetic* distinct instances. The OSS replay field
supplies **real** ones: tasks derived from pinned open-source code where a
captured knot grammar genuinely occurs in the wild.

The claim being built toward (NOT yet made): *a grammar captured once from
frontier spend keeps paying for itself on real code, not just in the
greenhouse.* The field is the admission layer for that claim; credit itself is
only ever minted by the capture ledger's own gated replay process.

## What an entry is

One JSONL row in `data/oss_replay/field.jsonl`
(schema: `schemas/oss_replay_entry.schema.json`):

- **upstream** — project, file, release ref pinned to a **full commit hash**,
  license, and a vendored directory whose bytes are sha256-bound (with the
  upstream LICENSE alongside). Custody is bytes, not URLs.
- **task_manifest** — a normal `tasks/*.json` manifest, **hidden-graded only**
  (gameable tasks are refused, same rule as `breadth_tasks.py`).
- **capture_links** — which captured artifact this instance exercises, with a
  `distinct_work_item_id` that must be unique across the field **and** never
  already spent in the capture ledger (same-instance rule enforced at
  admission time, not remembered later).
- **admission** — license allowlist, PII statement, determinism statement,
  vendored-bytes verification.
- **replays** — receipts only; an entry can never carry `validated_replays`.

`scripts/validate_oss_replay_field.py` enforces all of this fail-closed and
runs in `breadth-durability` CI.

## Entry 001 — CPython `fnmatch` character classes

The task02 capture (`task02_escape_class_boundary`, $0.6805 real-billed)
isolated one grammar: **inside a character class, backslash is a literal, not
an escape**. That exact grammar ships in every Python installation —
`fnmatch.translate`'s `[...]` branch (Lib/fnmatch.py, v3.12.0 lines 93–145) —
along with three more knots the visible spec-reader will not guess:

- a `]` in the first content position is content, so **`[!]` is unterminated**
  (its only `]` gets consumed) and falls back to a literal `\[`;
- hyphen chunking with invalid-range **merging** (`[b-a]` → `(?!)`);
- regex set-operation characters (`&~|`) escaped after the fact.

`fixtures/t2_ossrf_fnmatch_charclass/` poses `translate_charclass(pat, i)`
with the complete normative rules in the docstring (black-letter, like the
almanac corpus) and three easy visible checks. The hidden grader carries 23
vectors whose expected values are **machine-derived from the vendored
upstream**: `experiments/oss_replay/generate_vectors.py` transcribes the class
branch as a reference, and CI (`--check`) proves

1. a full `translate` spliced from that reference **equals the vendored
   upstream byte-for-byte** on a 38-pattern corpus,
2. the naive escape-inside-class implementation (the wild miss the capture
   recorded) **still fails** the vectors — the knot still discriminates,
3. the baked vectors match regeneration — no silent drift.

## What is NOT claimed

- **No model results.** No solver has been run against the entry; the field
  row is `admitted`, `replays: []`.
- **No amortization credit.** A future replay run (floor + scaffold packet vs
  floor bare, sealed-before-grade, hidden-graded) may mint at most one
  validated replay for `task02_escape_class_boundary` — through the capture
  ledger's process, not this file.
- **No generality.** One entry is an existence proof of the admission
  machinery, not a field. Growth rule: every new entry passes the same gate.

## Burden note (docs/burden-discipline.md)

```text
requested_outcome: an admission layer for real-world replay instances of captured grammars (ARC-D foundation)
claimant: the 2026-07-12 driver session (Fable, ARC-D go)
authority: vendored upstream bytes at a pinned release commit; splice-equivalence proof against the shipping implementation
predicates: license allowlisted (PSF-2.0); vendored bytes sha256-bound; task hidden-graded; vectors machine-derived with CI drift guard; naive-fails verified; distinct-instance rule enforced against the capture ledger
burden_holder: data/oss_replay/field.jsonl + this doc
evidence: vendored upstream + PROVENANCE.json, fixture + manifest, generator --check, validator + 11 tests, CI wiring
verifier: scripts/validate_oss_replay_field.py; experiments/oss_replay/generate_vectors.py --check
gap: zero replays run; the field has one entry; the wild-amortization claim is UNMEASURED
closure_decision: partial
failure_default: keep_open — no routing, capability, or amortization conclusion may cite this field until replays run through the capture ledger
```
