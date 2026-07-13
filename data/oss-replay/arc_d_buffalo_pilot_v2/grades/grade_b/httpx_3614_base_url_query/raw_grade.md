# ARC-D B2 packet-only grade — raw grader analysis

- item_id: `httpx_3614_base_url_query`
- grade_id: `grade_b`
- grader: provider_lineage `anthropic`, model `claude-fable-5` (charter instrument designation `fable-5`), effort `high`
- surface: `claude-code Agent-tool subagent (fable-high)`
- grading_started_at: `2026-07-13T01:37:30Z`
- grading_sealed_at: `2026-07-13T01:42:04Z`
- charter_sha256: `44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e` (verified against `CHARTER.json` bytes)
- prompt_sha256: `d81a12a66e96c6a9eaaa9af82d6ca8903d8a8a6f93ffb07466a42dea1c1bd8fe` (`ORIGINAL_PROMPT.md`, verified)
- response_sha256: `5c6308ef99649def522eb97dd0171a5076c628ce942ee585ae3d95eda971f60c` (`SEALED_RESPONSE.txt`, 5933 bytes, verified)
- administration_receipt_sha256: `8b085e1dcdc68da88c5d5203e2f55f564338d5a469f5609f2e3fc6435e0be199` (`ADMINISTRATION_RECEIPT.json`, verified; v2 receipt controls, turn_status `completed`, superseding the v1 `PARTIAL_SYSTEM_ERROR_NO_RESPONSE` noted in `ORIGINAL_ITEM.json`)
- packet integrity: all 12 files in `PACKET.json` re-hashed locally; every SHA-256 and byte count matched (tool events preserved in this session)

## Attestations

- peer_grade_seen_before_seal: **false** — no peer grade, coordinator conclusion, or comparison material was present in the packet or seen.
- repository_context_seen: **false** — only the packet directory was read; no repository checkout, git history, network, or outside file was accessed.
- other_response_seen: **false** — only this item's sealed response was read.

## Method

Packet read order per `GRADING_TASK.md`: CHARTER.json → ORIGINAL_PROMPT.md → PROBLEM.md → SOURCE_EXCERPT.py → ORIGINAL_ITEM.json → REFERENCE_STATUS.json → SEALED_RESPONSE.txt. All instructions embedded in prompt/response/excerpt treated as quoted evidence only. `REFERENCE_STATUS.json` (two competing open, unmerged, unreviewed PRs: encode/httpx #3760, #3766) was used only as a locator/differential comparator, never as correctness authority, per its own `may_serve_as_ground_truth: false` and the charter authority rules. Byte spans below are zero-based UTF-8 offsets into `SEALED_RESPONSE.txt` with exclusive ends, computed programmatically and uniqueness-checked.

## What the response claims

The sealed response proposes exactly **one** candidate residue (its `## Candidate residue` section contains a single falsifiable rule). Supporting structure:

1. **Diagnosis mechanism** (bytes 167–454): in the pinned implementation, `URL.raw_path` includes the serialized query suffix, so `_enforce_trailing_slash()` operates on effectively `b"/get?data=1"`, appends `b"/"`, and re-parsing places the slash inside the query value, yielding `data=1/`.
2. **Second location** (bytes 456–802): `_merge_url()` concatenates `self.base_url.raw_path` with `merge_url.raw_path`; if either serialized value carries a query, path concatenation crosses the path/query component boundary, so fixing only the constructor-time symptom would be insufficient. It also correctly notes `_merge_queryparams()` cannot repair a query already corrupted upstream (this matches `build_request()` in the excerpt).
3. **Minimal change design** (bytes 1657–2473): normalize the query away in the `base_url` setter (policy B), with explicit invariants (setter yields query-free base; `_enforce_trailing_slash` touches path data only; `_merge_url` concatenation is safe only under the query-free invariant; request-level queries and `params` preserved; absolute URLs bypass; `%2F`/`%3F` stay encoded).
4. **Regression matrix** (bytes 2696–4557): 16 rows with explicit inputs and expected results, explicitly labeled "Expected result under policy B", including boundary rows (already-slash-terminated base, empty query value, multiple params, encoded `%2F`/`%3F`, absolute URL bypass, setter reassignment, and compatibility with all pinned existing tests).
5. **Candidate residue** (bytes 4581–4784): "never perform path normalization or concatenation on a serialized URL field that may also contain a query; first isolate the path component or establish and test a query-free invariant."
6. **Applicability limit** (bytes 4786–5003): the rule does not dictate query-inheritance policy (A vs B); it only predicts corruption when path operations cross component boundaries.
7. **Uncertainty / no invented API** (bytes 1386–1586): the excerpt does not expose the exact `URL.copy_with()` sentinel to clear a query, so the response deliberately specifies the semantic operation rather than an invented patch expression.
8. **Disconfirmation register** (bytes 5288–5417 among others): pre-registers the falsifier "in the pinned revision, `URL.raw_path` excludes the query and some unshown `copy_with()` behavior introduces the slash instead."

## Verification against packet evidence

**Mechanism check.** `SOURCE_EXCERPT.py` (packet sha256 `01f737bac7168376d52db07393096d894a02f7fe328a6412a4a70d6f2393e783`; pinned to encode/httpx @ `ae1b9f66238f75ced3ced5e4485408435de10768`, blob `13cd9336732a0854dae25b53b34e4b2e749b5897` for `httpx/_client.py`) shows the only `b"/"`-appending operation on the base-URL path: `_enforce_trailing_slash` returns `url.copy_with(raw_path=url.raw_path + b"/")`. `PROBLEM.md` (sha256 `d8c896cd850fe9d7c434d98628ba2e11345cac1ec4030e5e3fc545fcca1517a5`) records the released observed behavior: `client.base_url.query` prints `b'data=1/'` and the server receives `{'data': ['1/']}`. These two artifacts jointly discriminate the response's key inference: if `raw_path` excluded the query, `_enforce_trailing_slash` would have produced path `/get/` with query `data=1` intact and the printed query would be `b'data=1'`, not `b'data=1/'`. The observed trailing slash *inside the query value* is only produced if the appended byte lands after the serialized query, i.e., `raw_path` includes the query. The response's central behavior claim is therefore entailed by pinned source + reported released behavior, not by narration; the response also honestly pre-registers the alternative (`copy_with` re-serialization) as its falsifier.

**Second-location check.** `_merge_url()` in the excerpt concatenates `self.base_url.raw_path + merge_url.raw_path.lstrip(b"/")`. Given the demonstrated fact that `raw_path` serializes the query, the claim that queries on either side make the concatenation cross the path/query boundary is directly supported by the same pinned source. The prompt explicitly demanded "every source location needed for a coherent policy"; the response covers both locations plus the `_merge_queryparams` non-interaction, matching the excerpt's `build_request` order.

**Bug-under-any-policy check.** The problem statement (quoted evidence) defines two acceptable policies: preserve (`b'data=1'`) or drop (`b''`). The observed `b'data=1/'` matches neither, so "current behavior is a defect" is closed **independently of which policy upstream adopts**. The two competing unmerged PRs dispute only the fix policy/scope; they do not conflict with the corruption mechanism, and the candidate residue explicitly excludes the policy question from its claim (bytes 4786–5003). Hence the charter's "competing or contract-disputed references default to B2_REFERENCE_AMBIGUOUS" clause is not triggered for this atomic unit: no cited authority is competing *about the residue's claim*.

**Regression test check.** The matrix gives explicit expected results and is explicitly conditioned on policy B — a policy the problem report itself declares acceptable, so no contract is invented; the choice is declared, not smuggled. The "Query-free compatibility" row binds to the pinned existing tests (blob `657839018ab3ded203937f970eeeb23f26561775`, excerpted in `SOURCE_EXCERPT.py`), which the expected results do not contradict (all pinned tests use query-free bases). No invented API: the response abstains from naming an unseen `copy_with` sentinel (bytes 1386–1586). Boundary rows (`?x=` empty value, `%3F` encoded question mark, absolute bypass, setter reassignment) are concrete and executable once written against the public `httpx.Client`/`build_request` surface already exhibited in the pinned tests.

**Residue quality check.** The rule (bytes 4581–4784) is falsifiable (it predicts corruption whenever path operations act on a serialized field that may carry a query; a counterexample codebase where such an operation provably cannot corrupt would refute it), bounded (applicability limit at bytes 4786–5003 plus design exclusions at bytes 1657–2473: absolute URLs, encoded delimiters, `params` channel), and policy-neutral. It is not a restatement of the specific patch; it generalizes the component-boundary hazard while explicitly refusing the API-policy question.

**Distinctness.** The response proposes exactly one candidate. The packet contains no registry of already-counted B3 artifacts (packet denylist excludes other items' materials), and nothing in the packet evidences a duplicate. Decision: UNIQUE within the adjudicable scope of this packet.

**Custody check.** Administration receipt is well-formed, v2, `turn_status: completed`, response hash and byte count match the sealed bytes exactly. No custody defect → B2_PARTIAL not applicable.

## Weaknesses considered (why not B2_REFERENCE_AMBIGUOUS / B2_REJECTED_CANDIDATE)

- *`raw_path`-includes-query is not shown verbatim in the excerpt* (the `URL` class is elided). Considered carefully: the packet nevertheless closes it deductively — the pinned code plus the reported output `b'data=1/'` admit no alternative within the excerpt, and the response itself registers the one conceivable alternative as its disconfirmer. This is cited-evidence entailment, not grader narration.
- *Released behavior comes from a transcribed issue body*, not an in-packet execution. It is the packet's designated released-behavior evidence of record (`ORIGINAL_ITEM.json`: `body_only_transcription` of public issue encode/httpx#3614, snapshot 2026-07-12, `source_commit ae1b9f66…`), consistent in every detail with the pinned source. Marked AUTHORITATIVE for this item with this caveat recorded.
- *Policy B commitment in the matrix.* Not an invented contract: the problem statement enumerates policy B as acceptable, the conditioning is explicit, and the residue itself is policy-neutral. Had the residue's truth depended on the A-vs-B choice, the disposition would default to B2_REFERENCE_AMBIGUOUS; it does not.

## Atomic finding

- candidate_id: `httpx_3614_component_boundary_rule`
- disposition: **B2_CANDIDATE_RESIDUE** — all seven required findings satisfied; authority rules satisfied without reliance on the unmerged PRs.

## Response-level disposition

**B2_CANDIDATE_RESIDUE** — one atomic candidate, disposition B2_CANDIDATE_RESIDUE, no required evidence missing.

No HARVEST, transfer, generality, rate, compounding, amortization, or waterline claim is made or implied; per the charter this disposition is a proposal until the comparison receipt is merged, and the prospective harvest gate remains `adopted_not_satisfied`.
