# Residue Recorder — constitution (draft v0.4, provisional)

*Working name for the program the operator has run by hand and already named:*
**"capture user residue, make it navigable."** The spine, written before code, for operator + Sol
adversarial review. It **governs.** §3/§6/§8/§9/§10/§11/§12 are operator-ratified (reviews 2026-07-12).
Changing §7–§12 or any authority hierarchy is a gated act, not an edit.

---

## 0. Thesis

Everything we do is the operator steering in natural language and a model executing. The code that
falls out is the *precipitate*; the durable value is the **interaction that produced it** — where
execution diverged from intent and got corrected, the procedures we re-run every session, and the
standing operator constants. That trace is **residue.** The program captures residue across the
surfaces where work happens, promotes only the reusable part through an independently scored gate, and
feeds it back so the next session converges on intent **faster** — a durable, always-fed,
forecast-scored **twin of the working dyad**, not a diary and not a replacement.

## 1–2. What it is / is NOT

- **residue ≠ transcript** — the transcript is everything; residue is the reusable part.
- **twin ≠ replacement** — a twin good enough to run without the operator is one about to drift.
- **synchronized ≠ snapshot** — unfed, a twin is a wax figure.
- Not surveillance, not a "record everything" landfill. Volume is not evidence (EP-008).

## 3. Architecture: Genesis, projection, reducer  *(ratified)*

| Layer | Role | Admissible contents |
|---|---|---|
| **Genesis** | Immutable evidence of what occurred on a particular surface | Raw transcript events, tool calls, tool results, timestamps, surface metadata, source references, integrity hashes |
| **Projection** | Redacted, navigable representation of Genesis | Session views, timelines, search indexes, event groupings, cross-surface mappings |
| **Reducer** | Promotes reusable residue through an independently scored gate | Distinctions, scaffolds, operator constants, handoff capsules, enforceable tests |

Genesis contains events and makes no interpretive claims. `CLAUDE_SESSION_LOG.md`, session summaries,
model-authored handoffs, and compact summaries are **projections or reducer outputs**. A projection
never modifies, replaces, or becomes its Genesis. The reducer may cite Genesis and projections but may
not silently treat a prior summary as raw evidence. The root evidence store must remain outside any
directory or process whose output it governs.

## 4. Three residue types

1. **Correction residue → distinctions** (`X ≠ Y` + would-have-caught test).
2. **Recurring paths → scaffolds** (replayable templates; derivation paid once).
3. **Operator constants → standing preferences** (the operator's `TasteSpec` as operator).

## 5. What it feeds

Pre-emptive execution · cross-session handoff · the breadth thesis turned inward · cross-engine
Claude⇄Sol. **Nothing downstream inherits an ungated claim.**

## 6. Coverage and durability: per-surface contracts  *(ratified)*

Work occurs across surfaces that do not share storage, lifecycle controls, authentication systems, or
export capabilities. The system uses **one explicitly authorized capturer per surface and a
provenance-preserving merge.** No capturer may imply visibility into another surface. No merger may
infer events merely to fill a gap.

Each surface must publish a versioned **capture contract** containing: (1) surface identity —
product, client, environment, device, OS, authenticated principal, local/remote status; (2) authorized
scope — opt-in and independently revocable per surface; (3) capture source; (4) evidence fidelity —
full/partial events, rendered text, interpretation, or summary-only; (5) capture events / checkpoint
triggers; (6) maximum loss window (time, events, or bytes); (7) durability destination — store,
encryption, key custody, retention, acknowledgement condition; (8) privacy boundary; (9) authentication
method; (10) integrity mechanism — sequence numbers, hashes, signatures, manifests, duplicate &
truncation detection; (11) failure representation; (12) merge key.

**6.1 Local Claude Code.** Source: native session JSONL + hook payloads. Full event fidelity where the
client records it; subagents separately identified. Persistent disk, but a second encrypted durable
replica is required (device loss / corruption). Triggers: tool batches, response completion/failure,
compaction, subagent completion, termination. Loss window declared and verified by forced-termination
tests — session termination alone is not a durability mechanism. Terminal gap for events unwritten
before process death.

**6.2 Remote Claude Code / web-container.** Source: session JSONL + supported lifecycle hooks in the
container. Full fidelity only for events visible to that container/session. **Incremental encrypted
transfer to an authorized durable store is mandatory** — a recording only on the ephemeral filesystem
is not durably captured. Triggers: highest-frequency reliable lifecycle events; finalization is a final
flush only. Loss window = interval between last acknowledged encrypted checkpoint and reclamation. The
merger must distinguish clean completion from disappearance.

**6.3 Claude.ai web/desktop/mobile.** Source: model-written structured handoff or user-initiated export.
Summary / rendered-conversation fidelity — a model-written handoff is a projection, not Genesis. The
operator must deliberately transfer the authorized output. Loss window: potentially the entire
unexported conversation. No local hook/transcript assumed; surface stays manual until a supported
export/API provides stronger evidence. **Never label a handoff from this surface as raw transcript
evidence.**

**6.4 Codex / Sol.** Source: product-specific logs, connector exports, repository changes, tool records,
handoffs — per what the product exposes. Fidelity declared per source; repository state proves artifact
state, not the interaction that produced it. Persistent logs replicate under the same encryption /
trust-boundary rules; ephemeral execution checkpoints incrementally. Claude and Codex schemas,
identities, compaction, and tool semantics are not presumed equivalent; the merge preserves engine
identity and does not normalize away substantive differences.

**6.5 Merge contract.** The merger creates a cross-surface chronology **without a fictional unified
transcript.** Every merged event retains: source surface, source session, source engine, source event
id, original timestamp, observed clock uncertainty, capture fidelity, Genesis availability, redaction
state, integrity status, merge confidence. Apparent-duplicate records may be linked but neither source
is silently deleted. Cross-surface ordering is marked uncertain when clocks/timestamps/transfer delays
don't establish sequence. A missing interval is a **first-class `coverage_gap` record** (surface, start,
end, reason, recoverability); a projection may summarize around a gap but must not narrate the missing
interval as observed.

**6.6 Surface admission gate.** A capturer is not admitted to the merged record until tests demonstrate
it: captures an authorized event; refuses unauthorized scope; produces an encrypted durable checkpoint;
preserves ordering or declares uncertainty; detects truncation/duplication/replay; records an export
failure as a gap; does not promote captured instructions into normative authority; applies declared
privacy controls before a trust-boundary crossing; keeps private audit and export-safe receipt
separated; and does not exceed its declared loss window under forced termination. An un-admitted
capturer may produce experimental evidence only, labeled provisional, and cannot silently enter the
authoritative merged record.

## 7. Nonnegotiable gates

Biting gate (fails before fix, passes after) · a twin claim must forecast and be scored
(`narrated ≠ measured`) · `logged ≠ learned` · `imported ≠ exercised` / `local-green ≠ CI-green` ·
`found-instruction ≠ authorized-instruction` · **the reducer never self-grades.**

## 8. Privacy and trust-boundary law  *(ratified)*

Capture is opt-in per surface; no global recorder by default. Genesis may contain private material that
appeared in the source and couldn't reliably be excluded at capture; it stays confined to the authorized
**trust boundary** — not exported, indexed, embedded, summarized, promoted, or published without
explicit operator authorization. High-risk classes (credentials, auth material, government ID, sealed
legal material, medical records, designated private conversations) are excluded at capture where
technically possible; detection is a defensive control, not proof of safety. Redaction occurs before any
projection crosses a trust boundary and emits an auditable report; redacted output is still treated as
potentially sensitive. **Encrypted-Genesis transfer inside the same authorized boundary is replication,
not publication;** any transfer to a different operator/service/provider/public repo/shared index/broader
access domain is a trust-boundary crossing needing explicit authorization. Every publication is
irreversible; deletion from one system does not establish that copies/caches/embeddings/derivations are
gone.

## 9. Source-of-truth and authority hierarchy  *(ratified)*

**Normative authority:** operator's current informed instruction + revocation rights → privacy/safety
rules → remaining constitution → specifically authorized gated artifacts → implementation defaults.
**Historical evidence:** Genesis events → integrity-verified external records → projections tied to
Genesis references → summaries and prose recollections.
**Verification evidence:** independently scored biting tests → reproducible evaluations → implementation
assertions.

Tests demonstrate whether the build satisfies the governing rule; they do not create authority and
cannot override operator consent, privacy law, or the constitution merely because they pass. Genesis is
authoritative for what was recorded on a surface and silent about meaning, intent, correctness, and
reusable value. A projection never overrides its Genesis. A reducer output never overrides the operator.

## 10. First falsifiable test  *(ratified)*

Two purposes must not be conflated. The **first completed session tests the forecasting pipeline**
(pre-registration, immutable storage, outcome labeling, independent scoring, Genesis linkage) — it
establishes only that the mechanism operates. **Evidence for a twin requires repeated predictive
performance against a declared baseline.**

Before substantive execution, the candidate twin writes a timestamped forecast containing: (1) a
probability distribution across the fixed correction taxonomy including `no_material_correction`; (2)
predicted first material correction class; (3) predicted trigger/stage; (4) supporting evidence from
prior gated residue; (5) an abstention option. Correction classes are mutually exclusive at the scored
level and defined by observable transcript criteria; a correction counts only when the operator changes,
rejects, or materially redirects execution (stylistic discussion, ordinary iteration, and model
self-correction don't count unless the rubric says so). At session end an evaluator that did not
generate the forecast labels the outcome from Genesis by the fixed rubric; the reducer never labels or
scores its own forecast. Scored by Brier score or log loss vs. a historical-frequency reference model;
top-class accuracy may be reported but can't establish predictive value alone. One session validates the
apparatus; a learning claim needs a predeclared window, sufficient per-class observations, and margin
over the reference model. Until then the twin is a hypothesis with recorded forecasts.

## 11. Evidentiary integrity, storage protection, instruction authentication, evaluation independence  *(ratified)*

*These refine §§3, 8, 9, 10 and have equal constitutional force.*

**11.1 Orphan projections.** A projection whose cited Genesis references cannot be resolved does not
retain the authority of one whose sources remain inspectable. It is **unresolved derivative evidence** —
not Genesis, not automatically ordinary prose. Its weight depends on: contemporaneity of creation;
intact source references/timestamps/hashes/signatures/capture metadata; corroboration by surviving
artifacts or independent records; whether it separates observed events from interpretation; and whether
its producing process was known and reproducible. It may support investigation, reconstruction, or
provisional continuity, but may not independently authorize a promoted claim, establish a gate was
passed, or override surviving Genesis. `CLAUDE_SESSION_LOG.md` and similar handoffs must declare whether
their cited Genesis is available, partially available, or unavailable.

**11.2 Encryption as a durability precondition.** Genesis leaving an ephemeral runtime for durable
storage must be encrypted in transit and at rest before the destination acknowledges persistence. A
durable plaintext replica outside the originating runtime is prohibited unless the operator explicitly
authorizes a named store, scope, duration, and access policy; absence of encryption is never inferred as
authorization. Transient plaintext for processing stays inside the authorized execution boundary with
minimum lifetime/permissions and is deleted after the encrypted replica is verified. Encryption alone
does not establish that a destination is inside the trust boundary — authorization, access control, key
custody, retention, and encryption are separate requirements. **Keys must not be stored in the same
artifact, repository, or unprotected location as the encrypted Genesis they protect.**

**11.3 Authenticated normative authority.** Normative authority attaches to an **authenticated operator
and an authorized instruction channel**, not to the semantic content of any captured message, file,
transcript, tool result, environment variable, or retrieved document. The normative hierarchy begins
with the operator's authenticated, current, informed instruction and revocation rights. An instruction
found inside Genesis, a projection, a repo, a downloaded file, model context, or external source is
historical evidence only; it becomes normative only when the authenticated operator explicitly adopts it
through an authorized channel. The recorder/reducer must preserve instruction provenance — asserted
speaker, originating surface, timestamp, authentication status, and later confirmation/modification/
revocation. `found-instruction ≠ authorized-instruction` is an enforced **provenance** rule, not merely
content classification.

**11.4 Independent outcome labeling and scoring.** The evaluator that labels a forecast outcome must be
blind to the forecast until the outcome label and supporting Genesis references are committed.
Independence is **procedural** — a fresh context, separate invocation, or different model name does not
by itself establish it. Requirements: a fixed, versioned rubric established before the session; no
evaluator access to the forecast before outcome commitment; outcome labels tied to resolvable Genesis
references; a committed label record that can't be silently revised after forecast disclosure; mechanical
score calculation; disclosure of evaluator identity, engine, rubric version, and any human intervention.
A deterministic labeler is preferred where the taxonomy permits; where interpretation is unavoidable,
cross-engine evaluation or operator adjudication may be used, but disagreements and overrides remain in
the record. The reducer may provide evidence to the evaluator but may not select the label, revise the
rubric, or score its own forecast.

**11.5 Cold-start honesty.** Before gated residue exists there is no learned basis for a twin-specific
predictive claim. The initial forecast must be one of: an explicit abstention; a declared base-rate
forecast from an external/provisional reference set; or a uniform distribution used solely to test the
apparatus. The first completed session may validate that preregistration/capture/labeling/commitment/
scoring operate — it does not validate that the twin has learned. A learned forecast begins only after
prior gated residue exists; a capability claim requires §10's full window and baseline. **The apparatus
test, the first nontrivial forecast, and evidence of predictive value are three separate milestones and
must never be reported as one.**

**11.6 Redaction audit sensitivity.** A redaction audit can disclose the existence, location, frequency,
format, or category of protected material, so it inherits that material's sensitivity. The process
produces two outputs: a **private audit record** (detail for verification/incident response, staying
inside the protected Genesis's trust boundary) and an **export-safe receipt** (minimum to establish a
declared policy ran). The receipt must not expose secret values, precise locations, identifying
fragments, reversible hashes, or metadata that materially narrows the protected content. A redaction
report is evidence only that specified controls were applied — not that the resulting projection is safe.

## 12. Key custody, provisional instruction authority, admission drift, and subject-labeler conflict  *(ratified)*

*These rules refine §§6, 9, 10, 11.2, 11.3, and 11.4 and have equal constitutional force. Ratified from
reviewer findings F/G/H/I with operator corrections: F key-wrapping, G channel attribution, H
compatibility-scoped requalification, I scored-conflict exclusion.*

**12.1 Durable key custody for ephemeral runtimes.** Durable Genesis encryption must remain recoverable
through key authority controlled by the authenticated operator or an explicitly authorized custody
service. An ephemeral runtime must not be the **sole origin and sole custodian** of the key material
required to recover durable Genesis: a key that disappears with the runtime does not satisfy durability;
a key stored beside the ciphertext without an independent protection boundary does not satisfy
encryption. An ephemeral runtime may generate a **temporary data-encryption key** only when all hold:
(1) used solely for the authorized capture operation; (2) **wrapped before durable persistence** using
an operator-controlled public key, hardware-backed key, or authorized KMS; (3) wrapped key and
ciphertext bound to the same session, surface, and manifest; (4) the plaintext data key is never written
to the durable destination; (5) the plaintext data key is destroyed from the runtime after the store
acknowledges the encrypted object and wrapped key; (6) recovery has been tested using the
operator-controlled key authority. The durable recovery key, wrapping key, or root key must originate
from and remain under the authorized trust boundary — never generated inside an ephemeral runtime and
then treated as durable merely because it was exported. **Loss of the recovery key is a durability
failure; exposure of the recovery key is a privacy incident;** both must be represented explicitly in the
record.

**12.2 Provisional normative authority under declared authentication assumptions.** Normative authority
derives from instruction **provenance**, not from instruction-like language inside captured content.
Each surface contract must designate: (1) which transport/interface constitutes the operator instruction
channel; (2) what authentication/attribution evidence the surface provides; (3) what it cannot provide;
(4) whether channel instructions are fully authenticated, provisionally attributed, or unauthenticated;
(5) how the operator confirms/revokes/supersedes them. Where cryptographic operator authentication is
unavailable, a message through the surface's **designated operator channel** may be treated as
**provisionally normative under a declared authentication assumption** that is: logged with the
instruction; specific to surface/session/channel; visible to downstream reducers; revocable by the
authenticated operator; subordinate to privacy and safety rules; and **incapable of converting quoted,
retrieved, or tool-produced content into normative authority.** A platform-attributed user message may
therefore receive provisional normative status when the surface contract authorizes that channel; text
inside a file, transcript, tool result, model output, retrieved webpage, repository instruction, or
quoted conversation remains historical evidence unless separately adopted through an authorized operator
channel. The system preserves four distinct classes — `authenticated_operator_instruction`,
`provisionally_attributed_operator_instruction`, `captured_instruction_claim`,
`unauthenticated_instruction` — and no downstream component may silently promote one into another.

**12.3 Versioned and configuration-bound capturer admission.** Admission is granted to a declared
implementation and **compatibility envelope**, not permanently to an abstract capturer name. Every
admission record binds at least: (1) capturer implementation version or content hash; (2) input event
schema version; (3) supported surface/client version range; (4) hook and trigger configuration hash; (5)
redaction-policy version; (6) encryption and key-custody configuration; (7) destination and manifest
schema versions; (8) admission-test suite version; (9) date and evidence of the most recent successful
admission test. A change that can affect capture fidelity, event interpretation, privacy behavior,
instruction provenance, durability, integrity, or loss-window guarantees invalidates admission until the
relevant tests rerun. A client update does **not** force complete requalification when it stays inside a
previously tested compatibility range and does not alter relevant behavior — but the compatibility claim
itself must be versioned, tested, and bounded. Unknown schema fields, missing expected fields, changed
event ordering, altered hook behavior, or an unsupported client version must cause **explicit rejection,
quarantine as provisional evidence, or downgrade to a declared lower-fidelity mode** — silent best-effort
ingestion into the authoritative merged record is prohibited. Admission status is one of `admitted`,
`admitted_within_compatibility_range`, `requalification_required`, `provisional`, `rejected`. A
previously admitted capturer may **rot out of admission**; historical admission does not establish
current conformity.

**12.4 Subject-as-labeler conflict.** The operator is both the subject whose behavior is forecast and the
final authority on the operator's intent; those roles conflict when the operator labels or adjudicates
outcomes used to **measure** the twin's predictive performance. Operator adjudication may be necessary
when Genesis establishes what was said but not whether an intervention was a material correction,
reflected actual intent, or belonged to one class rather than another. When used, the record must state:
(1) which label/element the operator decided; (2) what evidence was available; (3) whether the operator
had seen the forecast; (4) whether it changed a prior blinded label; (5) whether the result is included
in the primary performance score. An operator-adjudicated outcome is marked `subject_labeler_conflict:
true` and — unless a **predeclared** protocol states otherwise — is **excluded from the primary blinded
performance score and reported separately.** Preferred evaluation order: (1) deterministic labeling under
a fixed rubric; (2) blinded independent labeling; (3) blinded cross-engine adjudication; (4) operator
adjudication for unresolved intent or taxonomy disputes. Operator adjudication remains authoritative for
the operator's **present intent** and for correcting a mischaracterized record; it is **not**
automatically evidence that the forecasting system performed well. A forecast evaluation report must
separately report mechanically resolved, independently adjudicated, operator-adjudicated, unresolved, and
conflict-excluded outcomes. **The system must not improve its reported performance by selectively
requesting operator adjudication only after an unfavorable independent result.**

---

*Status: hypothesis, not measured. Provisional v0.4. §3/§6/§8/§9/§10/§11/§12 operator-ratified
2026-07-12. Governance document under review — not implementation-ready specification. Sequence agreed:
§12 ratified → §6 contracts ratified → build the §10 apparatus (which cannot be meaningfully
preregistered or scored until the system knows which evidence is authoritative, which is derivative, and
where the record declares gaps). Awaiting Sol adversarial review on the v0.4 diff: do these amendments
close the four seams without opening new authority or operability failures?*
