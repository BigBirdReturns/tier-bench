# PR #44 trial-2 adjudication — transport error, not capability failure

**Claim in #44:** GPT-5.5 Instant/Medium/High all FAILED task02_wildcard
(hidden 0/10681 each).

**Finding: mislabeled evidence.** All three candidates arrived syntactically
unloadable: the `json_candidate_lines` transport (JSON-inside-JSON) collapsed
one escaping level, so every `'\\'` literal in the escape-handling code arrived
as `'\'` → unterminated string. A candidate that cannot compile measures the
pipe, not the model — per the constitution, that is a skip/error, never a fail.

**Diagnosis receipts:** each source has exactly one backslash line, and it is
the broken one (`if c == '\':`). SyntaxError at lines 13/7/6 respectively.

**Derived (NOT a receipt):** re-doubling every backslash — the unique inverse
of a single-level collapse — yields compiling sources that score
**10681/10681 on all three**. Strong evidence the models solved the task and
only the transport failed. These graded repairs are `derived`-class: the
repaired hashes differ from the captured hashes, so they can never be receipts.

**Ledger state on this branch:** the three cells are recorded as
`outcome=error`, `format=json_candidate_lines_syntax_error_transport_suspect`,
hidden grader not run. The capture files are preserved verbatim in run/.

**Fix shipped:** ingest now (a) parses `json_candidate_lines` receipts, and
(b) pre-compiles every function candidate — unloadable source becomes a
transport error and the hidden grader is skipped. Broken pipes can no longer
mint FAIL rows.

**Re-capture instruction (morning):** have the model output the RAW function
directly (starts with `def wildcard_match(`, no JSON wrapper, no code fence) —
plain text copy preserves backslashes; the JSON-lines transport is deprecated
for capture (kept only to read old receipts).
