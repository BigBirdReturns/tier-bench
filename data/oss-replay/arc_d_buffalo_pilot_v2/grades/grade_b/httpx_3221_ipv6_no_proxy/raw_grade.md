# ARC-D B2 packet-only grade — raw grader analysis

- item_id: `httpx_3221_ipv6_no_proxy`
- grade_id: `grade_b`
- grader: provider_lineage `anthropic`, model `claude-fable-5` (charter instrument name `fable-5`), effort `high`
- surface: `claude-code Agent-tool subagent (fable-high)`
- grading started_at: `2026-07-13T01:38:00Z` (UTC, packet opened)
- grading sealed_at: `2026-07-13T01:42:45Z` (UTC, analysis fixed before payload write)
- protocol_id: `arc_d_buffalo_pilot_v2`
- charter_sha256: `44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e` (verified by local recompute)
- prompt_sha256: `a5ee77e4991f2bddae9b7281aa5e1a6c2aca857ccfc3383e5af612136c796fd4` (verified)
- response_sha256: `3f0f2b1e423d9230fa4663302ca81f1eeb46022eb21cea444358bc1977f0c3c1` (verified; 5933 bytes exactly as sealed)

## Custody and isolation verification

Every packet file was re-hashed locally with `sha256sum` and matched `PACKET.json`
byte-for-byte: `SEALED_RESPONSE.txt`, `ORIGINAL_PROMPT.md`, `CHARTER.json`,
`SOURCE_EXCERPT.py`, `PROBLEM.md`, `REFERENCE_STATUS.json`, `ORIGINAL_ITEM.json`,
`ADMINISTRATION_RECEIPT.json`, `GRADE_PAYLOAD.schema.json`. The administration
receipt's `response_sha256` and `response_bytes` (5933) match both `PACKET.json`
and the on-disk sealed response. The charter's `sealed_evidence` entry for this
item matches the same prompt/response hashes and the administration-receipt hash
(`c9769ae3...e4cc4`). Custody is intact; no B2_PARTIAL trigger from custody.

`ORIGINAL_ITEM.json` records the v1 provider-error status
(`PARTIAL_SYSTEM_ERROR_NO_RESPONSE`); per the grading task, the v2
administration receipt (turn_status `completed`, tool_calls 0) and the sealed
response control here, so that v1 status does not affect this grade.

Exposure attestations (all truthfully false):
- `peer_grade_seen_before_seal = false` — no peer grade or coordinator conclusion was present in the packet or seen by this session.
- `repository_context_seen = false` — no repository file, checkout, history, queue/handoff/roadmap document, or git command was read or run; the only paths accessed were inside the packet directory plus this grade's output directory. Disclosure for the comparison reviewer: the claude-code harness auto-injects the host project's standard `CLAUDE.md` instruction banner into every session on this surface; that banner contains no content about this item, this response, httpx, the rubric's application, or any peer grade, and was not used in grading. No repository context bearing on this item was seen.
- `other_response_seen = false` — no other item's response was present or seen.

Local computation was used only to verify packet hashes and to locate exact
UTF-8 byte spans in `SEALED_RESPONSE.txt` (byte `find` on the sealed bytes);
the sealed response was never modified. `REFERENCE_STATUS.json`
(open, unmerged, unreviewed PR encode/httpx#3741; `may_serve_as_ground_truth:
false`) was read as hypothesis-locating context only and was NOT used to close
correctness in any direction.

## Response summary (what the subject proposed)

The sealed response returns the five required sections. Its content, by span
(zero-based UTF-8 byte offsets into `SEALED_RESPONSE.txt`, end-exclusive):

- [0, 571) `## Diagnosis`, first paragraph: `is_ipv6_hostname()` validates only the substring before `/`, so `fe11::/16` is classified IPv6 and the mount key `all://[fe11::/16]` is built with the CIDR suffix inside the brackets; `URLPattern` hands the malformed pattern to `URL(pattern)`, which raises `InvalidURL: Invalid port: ':'` during sync and async client construction, before any request.
- [573, 1145) Diagnosis, second paragraph: merely respelling the key as `all://[fe11::]/16` would avoid the crash but not implement CIDR bypass, because `URLPattern.matches()` compares only scheme, host regex, and port; the existing IPv4 case `all://192.168.0.0/16` therefore appears to match only the literal address — explicitly hedged as excerpt-based inference.
- [1147, 2650) `## Minimal change design`: localized to `_utils.py` (`get_environment_proxies` + `URLPattern`); validate slash-bearing values with `ipaddress.ip_network(..., strict=False)`; bracket only the address; retain an `IPv4Network`/`IPv6Network` on the pattern; add network-membership testing in `matches()` after the existing scheme/port checks; preserve the regex path, priority, and all non-network behavior; deterministic ordering for network patterns; both clients covered via the shared path.
- [2652, 4753) `## Regression matrix`: explicit input → candidate URL → expected-result rows, including the primary construction case ([2743, 2845): `no_proxy=fe11::/16` → client construction succeeds with a valid network-aware bypass mount), membership positives/negatives, family mismatch, hostname false-positive, `/0`, `/128`, invalid prefix lengths, and preservation rows drawn from the pinned `PROXY_CASES` (`127.0.0.1`, `::1`, `localhost`, `192.168.0.0/16` key form), wildcard `*`, scheme- and port-qualified behavior, ordering, and Client/AsyncClient parity.
- [4755, 5181) `## Candidate residue`: one reusable rule — "when a configuration token embeds non-URL semantics inside a URL-shaped dispatch key, making it parseable is insufficient; the dispatcher must explicitly preserve and evaluate those semantics" — with an applicability limit (CIDR-like selectors encoded into proxy/mount patterns) and an exclusion (downstream URL abstraction documented to retain and match the selector natively).
- [5183, 5933) `## Confidence and disconfirmation`: confidence 0.91 plus concrete disconfirmers (URL treating CIDR paths as network selectors, conversion at another layer, bypass outside the shown mount mechanism, IPv4 CIDRs already matching in-network addresses, compatibility constraints).

The response proposes exactly ONE candidate residue. I extract one atomic unit
and do not mint any further candidate (the hedged "latent IPv4 defect" remark is
supporting diagnosis, not proposed as a residue, and is not counted).

## Adjudication of atomic candidate `cand-1`

### Required finding 1 — exact response byte spans
Satisfied. Spans cited above and in the payload: [0,571), [573,1145),
[1147,2650), [2743,2845), [4755,5181), [5183,5933). All were located by exact
byte search against the sealed bytes.

### Required finding 2 — concrete behavior claim supported by authoritative evidence
The load-bearing behavior claim decomposes into two legs, both closable from
packet evidence classes the charter admits (pinned source, released behavior,
project tests):

1. **Crash leg.** `SOURCE_EXCERPT.py` (pinned to encode/httpx
   `b5addb64f0161ff6bfe94c124ef76f6a1fba5254`; `_utils.py` blob
   `7fe827da4d071b32ea6da44328629699d6fc88ce`) shows `is_ipv6_hostname()`
   validating `hostname.split("/")[0]` only, and `get_environment_proxies()`
   emitting `mounts[f"all://[{hostname}]"]` for the IPv6 branch — so
   `fe11::/16` deterministically yields the key `all://[fe11::/16]` with the
   CIDR suffix inside the brackets, exactly as the response says. `PROBLEM.md`
   independently records the released 0.27.0 behavior: `ValueError: invalid
   literal for int() with base 10: ':'` → `httpx.InvalidURL: Invalid port: ':'`
   at `httpx.Client()` construction. Source mechanism and released symptom are
   mutually consistent; the response's uncertainty note about unseen `URL`
   internals is honest and does not weaken the closed part (the report itself
   fixes the released symptom). CLOSED.

2. **"Parseable is insufficient" leg.** `URLPattern.matches()` is shown in
   full in the pinned excerpt (from `def matches` through `return True`) and
   compares only scheme, exact-host regex, and port — no network-membership
   logic anywhere in the shown dispatch path (`_client.py` blob
   `13cd9336732a0854dae25b53b34e4b2e749b5897` shows `_transport_for_url`
   iterating `pattern.matches(url)`). The curated `URL_MATCH_CASES` (derived
   from `tests/test_utils.py` blob `f9c215f65a131e9a96cf3be6002e0117a1f59050`)
   corroborate scheme/host/port-only matching semantics. Even under unseen
   `URL` parsing variants, an exact-host regex over `other.host` cannot express
   network membership, so the claim that a merely-parseable CIDR key would not
   implement bypass holds for the pinned code. The response itself scopes this
   correctly ("the absence of explicit network-membership logic shown here").
   CLOSED for the pinned commit.

The excerpt is curated ("not a byte slice") — I checked whether elision could
undermine either leg. The relevant functions (`get_environment_proxies`,
`URLPattern.__init__`, `URLPattern.matches`, both `is_ip*_hostname` helpers,
both client mount constructions, `_transport_for_url`) appear as complete
units, and the released-behavior traceback independently anchors the crash. No
authority in the packet conflicts with either leg. The response makes NO claim
that requires the unmerged PR; `REFERENCE_STATUS.json` was not needed and was
not used as ground truth.

The secondary, hedged inference (IPv4 `192.168.0.0/16` "appears likely to match
only `192.168.0.0`") is presented with explicit uncertainty and its own
disconfirmer; it is supporting narrative, not part of the residue's required
support, and its truth is not needed for `cand-1` to close.

### Required finding 3 — regression test, explicit expected result, no invented contract
Satisfied. Primary test ([2743,2845)): run `no_proxy=fe11::/16` and construct
`httpx.Client()` — expected result: construction succeeds and produces a valid
network-aware `all://` bypass mount. This uses only the existing public surface
(`no_proxy` environment variable, `httpx.Client()`/`AsyncClient()`), and the
expected network-bypass semantics are the problem report's own stated intended
behavior ("bypasses the proxy for addresses within that network"), not an
invented contract. The matrix further pins membership positives/negatives
(`fe11::/16` vs `http://[fe11::1]/` → bypass; `http://[fe12::1]/` → proxy;
family mismatch → proxy; hostname `fe11.example` → proxy) and
non-regression rows that restate the pinned `PROXY_CASES` and priority/match
behavior. Boundary rows (`/0`, `/128`, `/33`, `/129`) are included, with the
invalid-prefix rows deliberately left as "must be deliberate and
non-ambiguous" rather than inventing a specific error contract — that is the
correct non-invention posture. No fabricated API, no fabricated upstream
verdict, no claim of having run tests.

### Required finding 4 — falsifiable residue statement
Satisfied ([4755,5181)). The rule ("making a URL-shaped dispatch key parseable
is insufficient when the token embeds non-URL semantics; the dispatcher must
explicitly preserve and evaluate those semantics") is falsifiable, and the
response supplies its own concrete disconfirmers ([5183,5933)): a `URL`
abstraction that natively treats CIDR paths as network selectors, or conversion
at another layer, would falsify it for this code path.

### Required finding 5 — bounded applicability predicate and explicit exclusions
Satisfied. Applicability: CIDR or similar selectors encoded into proxy/mount
patterns whose matcher evaluates only scheme/host/port. Exclusion stated in the
response: does not apply when the downstream URL abstraction is documented to
retain and match that selector natively. Grader-added scope bounds (recorded in
the payload): no claim beyond the pinned excerpt's mount mechanism; no
cross-project generality, transfer, harvest, rate, compounding, amortization,
or waterline claim is made or implied at B2.

### Required finding 6 — distinctness
UNIQUE. The response proposes exactly one residue; the packet discloses no
registry of already-counted artifacts and no other item's response (denylist
enforced), so no duplicate exists in the evidence available to this
instrument. Distinctness against any external artifact registry must be
re-checked by the coordinator at B3 dedup; within this packet's evidence the
decision is UNIQUE.

### Required finding 7 — exact hashes and locations
All cited in the payload, verified locally:
- source: `SOURCE_EXCERPT.py` `9ed25770804e6d186c05777fbfc8f17c6427dc7da47c68622920a986a0620210` (pins upstream blobs `7fe827da…88ce` `_utils.py`, `13cd9336…5897` `_client.py`, `f9c215f6…9050` `tests/test_utils.py` at commit `b5addb64…5254`)
- released behavior: `PROBLEM.md` `fe714658c80597bbb7540091b1b909e29f54a04cf3030609811db48f8163e04b`
- prompt: `ORIGINAL_PROMPT.md` `a5ee77e4991f2bddae9b7281aa5e1a6c2aca857ccfc3383e5af612136c796fd4`
- response: `SEALED_RESPONSE.txt` `3f0f2b1e423d9230fa4663302ca81f1eeb46022eb21cea444358bc1977f0c3c1`
- administration receipt: `ADMINISTRATION_RECEIPT.json` `c9769ae33108596be7411f30b380b64bacc924f54f4cda12855e1da7b05e4cc4`
- charter: `CHARTER.json` `44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e`
- reference status (not used for correctness): `REFERENCE_STATUS.json` `4a1290243604d934237b3703d0001acbda669113ef71cca73c087ea89544c9d0`

### Authority-rule check
- Correctness support comes from pinned source, released behavior, and project
  tests — all admitted classes.
- The open PR (#3741) was not used to close correctness; nothing in the packet
  presents it as ground truth, and no competing or contract-disputed reference
  exists in the packet. The `B2_REFERENCE_AMBIGUOUS` default is therefore not
  triggered.
- No grader narration substitutes for cited evidence: every load-bearing claim
  above cites a hashed packet file and, where relevant, the pinned upstream
  blob hashes recorded inside it.

### Atomic disposition
`cand-1` → **B2_CANDIDATE_RESIDUE**. All seven required findings are satisfied
and no authority rule is violated.

## Response-level disposition

**B2_CANDIDATE_RESIDUE** — exactly one atomic candidate, disposed
B2_CANDIDATE_RESIDUE, with no required evidence missing. Custody, packet,
receipt, and grading evidence are complete, so B2_PARTIAL does not apply.

Charter compliance notes: no numeric score is emitted; no HARVEST, transfer,
generality, rate, compounding, amortization, or waterline claim is made; this
disposition permits (but does not perform) separately authorized B3
artifactization, and the prospective B4 gate remains entirely unsatisfied.
