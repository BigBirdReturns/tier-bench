# ARC-D B2 packet-only grade — grade_b — attrs_1567_setattr_mro

## Grader identity and session

- grade_id: grade_b
- provider_lineage: anthropic
- model: claude-fable-5 (charter instrument designation: fable-5)
- effort: high
- surface: claude-code Agent-tool subagent (fable-high)
- session: claude.ai/code session_01XNsE5QPUjqdTM57pTdGm7R (packet-only grading lane)
- started_at: 2026-07-13T01:37:50Z
- sealed_at: 2026-07-13T01:44:30Z

## Attestations

- peer_grade_seen_before_seal = false (no peer grade, coordinator conclusion, or
  comparison material was present in or read outside this packet)
- repository_context_seen = false (only files inside the packet directory were read;
  no repository checkout, git history, queue/handoff documents, or network access
  were used)
- other_response_seen = false (only SEALED_RESPONSE.txt for this item was read)

Local read-only computation was used solely to verify packet SHA-256 hashes and to
locate exact UTF-8 byte offsets in SEALED_RESPONSE.txt, as permitted by
GRADING_TASK.md. Those tool events are preserved in the raw session.

## Custody verification

All hashes recomputed locally with sha256sum and compared against PACKET.json
(packet_id arc_d_b2_attrs_1567_setattr_mro_v1) and CHARTER.json
(charter_id arc_d_buffalo_pilot_v2_b2_charter_v1):

| File | Recomputed SHA-256 | Matches PACKET.json |
|---|---|---|
| SEALED_RESPONSE.txt (7345 bytes) | 804aa2cdf06c0ad7379487fefe2d7f3684b8b2b49526f3988380233e5d74b898 | yes; also matches CHARTER.json sealed_evidence and ADMINISTRATION_RECEIPT.json |
| ORIGINAL_PROMPT.md (6214 bytes) | f9c554fb1d5094b90d5c7037db8192e017325289779a85ca396f96b7997ffbe9 | yes; matches charter prompt_sha256 and administration receipt v1_prompt_sha256 |
| SOURCE_EXCERPT.py (4621 bytes) | 1ad73e4c19e8cae3f4c71852fbd8ca1b9b8a58ef93769acb59835d9cae2979e3 | yes; matches ORIGINAL_PROMPT_RECEIPT.json source_excerpt_sha256 |
| CHARTER.json | 44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e | yes (PACKET.json charter_sha256) |
| ADMINISTRATION_RECEIPT.json | 843d1158fd457244001c8bdd628623324bcf681aa4a9097a2cb7e23c59540666 | yes; matches charter administration_receipt_sha256 |
| ORIGINAL_ITEM.json | bcf63606570e6989597398bd9f2cec9ca0096456ffcc4d03f3c9f8928a0c96f5 | yes |
| REFERENCE_STATUS.json | 96345b04f197404445d533534fee45055d21acd2c9208ca8b18cffd8a7a82b0f | yes |
| PROBLEM.md | 2d44eb11e5664f884e6d8136654aa9ad2054ccfc6843a90cc612b2e6a548c5c4 | yes; matches ORIGINAL_PROMPT_RECEIPT.json problem_sha256 |
| ORIGINAL_PROMPT_RECEIPT.json | 0d27474ba1023ef58e7cfc71c8d274f02f158003e77b91b3a0be48701bb906cb | yes |
| GRADING_TASK.md | c4254ed1419a574d988ae842d2980aa02cc52c6eaa6e78fc908e1e29c60cc4c3 | yes |
| GRADE_PAYLOAD.schema.json | b8092a44767a3d5a421c254bd9d989203292a0b1c71dfbf3d7236ea08ef9f6d5 | yes |
| GRADE_RECEIPT.schema.json | 476cb0b358e49372f0878156e8d2f7f091b759921d28446f5997d3c041382836 | yes |

Custody is intact: response bytes (7345), prompt bytes (6214), and every packet
file match their declared hashes. ORIGINAL_ITEM.json notes v1 pilot status
PARTIAL_SYSTEM_ERROR_NO_RESPONSE; per GRADING_TASK.md the v2 administration
receipt (turn_status "completed", 0 tool calls, response sealed) controls, so the
v1 provider-error status does not impair this grade.

## Authority frame

- Authoritative in-packet evidence: SOURCE_EXCERPT.py — curated allowlisted
  excerpts pinned to python-attrs/attrs commit
  d2fbfccc1ce77dcc927a86eae9521c95dc4e289c, with upstream blob ids recorded in
  ORIGINAL_ITEM.json (src/attr/_make.py = 793bfd89d6cd51f194dbc7ca9062f502ac172f09,
  tests/test_setattr.py = f44abf65847a433b83ad13e197d2a59ccc66c38a). It contains
  both accepted upstream source logic and the project's own executable tests,
  including the xfail reproducer `test_slotted_confused`
  (`@pytest.mark.xfail(raises=attr.exceptions.FrozenAttributeError)`).
  Caveat noted: the excerpt is curated, not a byte slice; within packet-only scope
  it is the charter-allowlisted "pinned authoritative source and executable-test
  evidence" and is treated as AUTHORITATIVE for the claims graded below.
- REFERENCE_STATUS.json: PR python-attrs/attrs#1567 is OPEN_UNMERGED_UNREVIEWED,
  may_serve_as_ground_truth=false. Per charter authority rules it may locate a
  hypothesis but cannot close correctness. This grade does NOT rely on it for any
  correctness closure; the response itself never cites the PR.
- Blindness class: HIGH_HINT_CALIBRATION — the pinned source names the
  immediate-base limitation and xfails the confused chain. This lowers novelty but
  does not change the B2 rubric; the candidate is graded on evidence-grounded
  correctness, falsifiability, bounding, and distinctness, not on discovery
  difficulty.

## Response structure and candidate extraction

SEALED_RESPONSE.txt (7345 bytes, UTF-8; note multibyte characters — curly quotes,
arrows — so byte offsets differ from character offsets) contains the five
prompted sections. Section start offsets (zero-based bytes):
Diagnosis 0; Minimal change design 1762; Regression matrix 3235; Candidate
residue 5592; Confidence and disconfirmation 6336.

The response proposes exactly ONE candidate residue (the "Candidate residue"
section states a single rule). One atomic finding is therefore graded.

## Atomic finding 1 — effective-provider-then-ownership-marker rule

candidate_id: `attrs_1567_setattr_mro::effective_provider_ownership_rule`

### Cited response spans (zero-based UTF-8 byte offsets, end exclusive; all verified by extraction)

| Span | Content (verified) |
|---|---|
| [66, 853) | Diagnosis steps 1-5: slotted A owns attrs frozen setter with `__attrs_own_setattr__=True`; non-attrs B has neither `__setattr__` nor marker in `B.__dict__`; `_create_slots_class()` checks only immediate bases via `base_cls.__dict__.get("__attrs_own_setattr__", False)`; immediate base B fails the check so C keeps A's frozen setter; `C(1).x = 2` raises `FrozenAttributeError`. |
| [855, 1092) | Resolution-rule statement: the correct question is which class supplies the effective inherited `__setattr__` and whether that same class owns the attrs marker. |
| [1094, 1300) | Bounding caveat: walking until any marked ancestor is incorrect; a user-owned intermediate setter must survive. |
| [1302, 1760) | Honest uncertainty on the dict-backed path and unseen `_has_custom_setattr` computation. |
| [1788, 2361) | Minimal change design: single predicate — traverse MRO, stop at first class whose own `__dict__` contains `__setattr__`, treat as attrs-owned only if that class's own dict has `__attrs_own_setattr__ is True`; apply in both builder paths. |
| [3307, 3548) | Regression row "Reported chain" with explicit expected results: assignment succeeds for both slot modes, `C.__setattr__ is object.__setattr__`, `C.__attrs_own_setattr__` false. |
| [3873, 4054) | Regression row "User-owned intermediate": preserve `B.__setattr__`, no reset. |
| [5614, 5822) | The residue rule itself. |
| [5824, 6007) | Explicit falsifiability statement. |
| [6009, 6334) | Applicability limit and exclusions. |

### Behavior claim (required finding: concrete claim + authoritative executable evidence)

Claim graded: at attrs commit d2fbfccc1ce77dcc927a86eae9521c95dc4e289c, for a
slotted chain `A` (attrs, `on_setattr=setters.frozen`) → non-attrs `B(A)` →
mutable slotted attrs `C(B)`, `_create_slots_class()` consults only
`self._cls.__bases__` for `__attrs_own_setattr__` in each base's own `__dict__`;
`B.__dict__` carries neither the marker nor a `__setattr__`, so `C` is not reset
to `object.__setattr__` and `C(1).x = 2` dispatches to A's attrs-generated frozen
setter, raising `attr.exceptions.FrozenAttributeError`.

Verification against packet evidence:

1. SOURCE_EXCERPT.py shows the exact immediate-base loop
   (`for base_cls in self._cls.__bases__: if base_cls.__dict__.get("__attrs_own_setattr__", False): cd["__setattr__"] = _OBJ_SETATTR; break`)
   with the upstream comment "We don't walk the MRO because we only care about our
   immediate base classes" and the XXX comment naming exactly this confused case.
2. SOURCE_EXCERPT.py contains the project's executable reproducer
   `test_slotted_confused`, xfailed with `raises=attr.exceptions.FrozenAttributeError`,
   whose body is byte-for-byte the A→B→C chain and `C(1).x = 2` assignment the
   response describes. The xfail marker is itself executable evidence that the
   failure occurs at the pinned commit (an xfail that did not raise would XPASS).
3. Diagnosis step 2 (Python resolves `B.__setattr__` to `A.__setattr__` while
   `B.__dict__` lacks both entries) is standard, independently executable Python
   MRO semantics.
4. The dict-backed contrast ("appears to avoid the reported failure") matches the
   test docstring "It works with dict classes because we can look the finished
   class and patch it" and the `getattr(cls, "__attrs_own_setattr__", False)`
   MRO-visible lookup in `_patch_original_class`; the response correctly hedges
   the unseen `_has_custom_setattr` computation rather than inventing it.

Every step of the diagnosis is directly supported by the pinned source and the
project's own tests. FINDING SATISFIED with AUTHORITATIVE evidence.

### Regression test (required finding: explicit expected result, no invented API/contract)

The response's regression matrix row [3307, 3548) is a concrete test: for
`slots=False` and `slots=True`, with A attrs-frozen, transparent non-attrs B(A),
mutable attrs C(B): assignment to `C.x` succeeds, `C.__setattr__ is
object.__setattr__`, and `C.__attrs_own_setattr__` is false. This uses only
existing public/observable attrs API (`attr.s`, `attr.ib`, `on_setattr`,
`setters.frozen`, `__attrs_own_setattr__`, `object.__setattr__`) — the identical
vocabulary of the packet's existing tests. The expected result is not an invented
contract: it is (a) the exact reset contract the project already asserts in
`test_setattr_reset_if_no_custom_setattr` (`NoHook.__setattr__ ==
object.__setattr__`, marker false) for the direct-inheritance case, and (b) the
project's own stated intent for the confused case ("setattr reset detection
should still work, but currently doesn't" — test_slotted_confused docstring).
The preservation-side row [3873, 4054) mirrors the passing
`test_setattr_inherited_do_not_reset` contract. FINDING SATISFIED.

Note on matrix breadth: some rows (multiple-inheritance orderings, marker
inherited through a non-attrs class) extrapolate beyond packet tests. They are
presented as proposed boundary tests consistent with the existing reset contract
(installing `object.__setattr__` on the child is exactly what the current code
does when it does reset), and the response itself lists "unseen tests establish
different multiple-inheritance semantics" as disconfirmation. This is bounded
proposal, not contract invention; it does not defeat the candidate.

### Falsifiable residue statement (required finding)

Span [5614, 5822): "When inherited behavior carries an ownership marker, decide
whether to remove it by locating the effective method provider first, then read
the ownership marker from that provider's own namespace." Span [5824, 6007)
supplies the disconfirmation predicate: a hierarchy where the rule selects a
different provider than Python's actual `__setattr__` lookup, or replaces an
effective user setter, disproves it. Concretely testable. FINDING SATISFIED.

Consistency check of the rule against every executable case in the packet:

- test_slotted_confused chain: first MRO provider of `__setattr__` above C is A;
  A's own dict carries the marker → attrs-owned → reset. Matches the project's
  stated intended behavior.
- test_setattr_inherited_do_not_reset: provider is user class A, no marker →
  preserve. Matches the passing test's assertions for both slot modes.
- test_setattr_reset_if_no_custom_setattr: provider WithOnSetAttrHook, marker
  owned → reset to `object.__setattr__`. Matches assertions.
- test_slotted_class_can_have_custom_setattr: descendant supplies its own setter;
  rule is out of scope by its own precondition. Matches.

The rule is consistent with all packet-visible authoritative tests and with
independently executable Python MRO semantics.

### Applicability predicate and exclusions (required finding)

Span [6009, 6334): applicability limited to machinery where ownership is reliably
represented on the method-defining class via ordinary class-dictionary/MRO
lookup. Explicit exclusions: post-creation independent mutation of methods or
markers, metaclass-supplied dynamic `__setattr__`, and resolution mechanisms not
represented by ordinary MRO lookup. Bounded and explicit. FINDING SATISFIED.

### Distinctness (required finding)

The packet discloses no previously counted B3 artifacts, and this response
contains exactly one candidate residue. Within all evidence available to this
packet-only instrument the candidate is UNIQUE. (Deduplication against any
external artifact registry is a coordinator/B3 concern outside this packet.)
FINDING SATISFIED: distinctness = UNIQUE.

### Evidence hashes (required finding)

- Source logic: SOURCE_EXCERPT.py, sha256
  1ad73e4c19e8cae3f4c71852fbd8ca1b9b8a58ef93769acb59835d9cae2979e3, kind=source,
  AUTHORITATIVE (pinned commit d2fbfccc1ce77dcc927a86eae9521c95dc4e289c; upstream
  blob 793bfd89d6cd51f194dbc7ca9062f502ac172f09 per ORIGINAL_ITEM.json).
- Executable tests (same packet file, test portion): SOURCE_EXCERPT.py, sha256
  1ad73e4c19e8cae3f4c71852fbd8ca1b9b8a58ef93769acb59835d9cae2979e3, kind=test,
  AUTHORITATIVE (upstream blob f44abf65847a433b83ad13e197d2a59ccc66c38a).
- Prompt: ORIGINAL_PROMPT.md, sha256
  f9c554fb1d5094b90d5c7037db8192e017325289779a85ca396f96b7997ffbe9.
- Response: SEALED_RESPONSE.txt, sha256
  804aa2cdf06c0ad7379487fefe2d7f3684b8b2b49526f3988380233e5d74b898 (7345 bytes).
- Administration receipt: ADMINISTRATION_RECEIPT.json, sha256
  843d1158fd457244001c8bdd628623324bcf681aa4a9097a2cb7e23c59540666.
- Charter: CHARTER.json, sha256
  44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e.

FINDING SATISFIED.

### Authority-rules check

- Correctness of the diagnosis is closed by accepted upstream source and project
  tests at the pinned commit (authority rule 1) — not by the unmerged PR.
- The unmerged PR #1567 was not used for any closure (authority rule 2).
- No competing or contract-disputed reference is present in the packet. The
  upstream "For now that's OK with us" comment acknowledges and tolerates the
  defect; the test docstring simultaneously states the intended behavior
  ("should still work"). These are not competing correctness authorities — they
  agree on what the behavior is and on what correct detection would be; they
  differ only on urgency, which the B2 rubric does not grade (authority rule 3
  not triggered).
- The candidate is an alternative implementation direction supported by
  authoritative behavior and tests (authority rule 4).
- All load-bearing claims above cite executable packet evidence, not grader
  narration (authority rule 5).

### Weaknesses noted (not disqualifying)

1. High-hint context: the source excerpt hands the subject the confused case; the
   residue's incremental content is the effective-provider-then-marker
   formulation and the explicit user-owned-intermediate bound. ORIGINAL_ITEM.json
   pre-declares this as HIGH_HINT_CALIBRATION; no blindness claim is minted here.
2. Two regression-matrix rows extend to multiple-inheritance territory with no
   packet test coverage; the response self-flags this in disconfirmation.
3. The dict-backed-path analysis is hedged because `_has_custom_setattr`
   computation is unseen; the response correctly declines to assert it.

None of these violates a required finding: the claims that carry the candidate
are evidence-closed, the extrapolations are bounded and flagged, and nothing is
invented.

### Atomic disposition

All seven required findings satisfied; all authority rules respected.
**B2_CANDIDATE_RESIDUE**.

## Response-level disposition

One atomic candidate; it receives B2_CANDIDATE_RESIDUE and none of its required
evidence is missing. Per the charter's response_dispositions table:

**B2_CANDIDATE_RESIDUE** (atomic findings: 1)

No HARVEST, transfer, generality, rate, compounding, amortization, or waterline
claim is made or implied. This disposition proposes candidate residue for
separately authorized B3 artifactization only; the prospective harvest gate
remains not satisfied.
