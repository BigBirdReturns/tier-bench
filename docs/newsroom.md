# Tier Desk newsroom constitution

Status: review-only design, machine-encoded in `newsroom.json` and checked by
`python -B scripts/validate_newsroom.py newsroom.json`.

This document defines an institutional layer above the existing Tier Desk. It
does not add an executor, scheduler, provider adapter, merge path, publishing
robot, or external authority. Its purpose is to make the current system legible
as an organization, freeze the authority boundaries that organization needs,
and identify the smallest future layers that can be added without weakening the
existing referee and custody contracts.

## 1. The project that already exists

The newsroom is an interpretation of working components, not a replacement for
them.

| component | classification | authority today |
|---|---|---|
| Tier Bench | measurement and routing | produces evidence about capability, cost, and routing; it does not authorize work |
| `tier run` | execution and referee boundary | creates a disposable candidate worktree, runs frozen acceptance, emits receipts, and supplies the terminal verdict |
| Tier Desk / Monster Wrangler | local control plane | stores task and run state, applies dependency and approval gates, supervises workers, and adopts only verified receipts |
| CRATE OPS | operating method | keeps work in repository-custodied packets, uses disposable sessions, and separates driver, hands, referee, auditor, and operator |
| ChatGPT Chair Inbox | external submission intake | observes a preregistered return, checks custody and path scope, consumes the request once, and creates an approval-gated `DRAFT` only |
| Newsroom constitution | institutional coordination model | review-only; it grants no runtime authority |

Three existing principles constrain every newsroom design.

First, the harness and referee have the last word. A model, external submitter,
operator, or editor may propose a claim or candidate, but none can adjudicate its
own work. Second, work state belongs to the repository and Desk database rather
than to a resident conversation. Third, model selection is routing data. A role
must survive model, vendor, price, and session churn.

The Chair repair directly below this stacked change is part of the assumed
baseline. Chair auto-validation is disabled. A Chair return cannot queue work,
wake the scheduler, invoke a model, check out a pull request, or execute an
acceptance command. It is an untrusted submission that may become a single-use,
approval-gated Draft after the complete changed-file set and immutable custody
tuple are recorded.

## 2. What the newsroom adds

The Tier Desk currently governs bounded action tasks. The newsroom adds a
separate vocabulary for persistent observation, analysis, validation,
publication, and correction. This matters because most of the work one person
cannot keep alive is not a large one-time task. It is a portfolio of weakly
active questions that require longitudinal attention:

- which assumptions expired;
- which dependencies, prices, standards, or external facts changed;
- which rejected approach became viable after an environmental change;
- which accepted claim lost support;
- which source conflicts warrant investigation;
- which unfinished item became unblocked;
- which recurring signal is material rather than repeated noise.

The newsroom turns those questions into standing beats with bounded work in
progress, source policies, expiry and kill criteria, and a valid
`NO_MATERIAL_CHANGE` result. It should reduce the operator's need to remember
that a question exists. It must not create an unlimited stream of summaries for
the operator to close.

## 3. The publisher and the Octopodes

The human operator is the publisher and accountable principal. The publisher
alone may authorize execution, authorize publication, merge changes, change
spending or concurrency caps, or accept an explicit custody exception. Those
powers are not delegable through a prompt, pull-request marker, role manifest,
or model selection.

An **Octopode** is a durable institutional role. Its continuity consists of a
role charter, beat, source policy, authority ceiling, decision history, and
receipt history. It is not a model session, synthetic personality, provider
account, or process. A Research Octopode may use a cheap local lane for routine
monitoring, a frontier lane for difficult synthesis, and an independent lineage
for audit while remaining the same repository-custodied role.

The execution lanes are disposable arms. They may be replaced whenever routing
evidence, cost, availability, or security conditions change. A role's history
must never depend on one conversation remaining alive.

Independence is recorded rather than inferred. Two calls are not independent
merely because they ran separately. A receipt should state source exposure,
context lineage, model or tool lineage, candidate authorship, and validator
lineage whenever independence is material to the claim.

## 4. Five planes

The newsroom separates five planes that are often collapsed in agent systems.

### Observation

Observation acquires tips, deltas, source snapshots, issue reports, repository
state, receipts, and other signals. Observed material is evidence, not an action
instruction. A source can cause an item to be triaged but cannot grant itself
execution authority.

### Analysis

Analysis turns observations into assignments, reports, hypotheses, comparisons,
and correction proposals. It may classify and prioritize work. It may prepare
an action task, but it cannot queue that task.

### Validation

Validation independently tests a report, candidate, or correction against a
frozen subject and acceptance rule. It records a verdict and evidence. It does
not author the candidate or execute production actions.

### Execution

Execution performs only a previously authorized local action task. In the
current project this is Tier Desk supervising `tier run`. The production desk
may start, interrupt, or record infrastructure failure for authorized work. It
cannot authorize its own work, adjudicate the result, merge it, or publish it.

### Publication

Publication exposes an accepted claim, edition, decision, or correction to its
intended audience. Publication is separate from acceptance. The human publisher
retains this transition even when preparation and validation are automated.

The planes are connected by receipts and explicit state transitions rather than
by shared conversational context.

## 5. Roles and ceilings

The machine-readable role registry lives in `newsroom.json`. The following
prose is explanatory. The validator freezes the v1 role set and rejects authority
expansion without a schema change.

### Assignment desk

The assignment desk triages observations, creates bounded assignments, imposes
expiry and kill criteria, and prepares action tasks. It cannot queue, execute,
validate, publish, merge, or change its own authority.

### Reporter

A reporter gathers and synthesizes evidence under a source policy. It produces a
report or a correction revision. It cannot validate its own report or turn the
report into an executable task.

### Copy desk

The copy desk normalizes reports into stable schemas, resolves presentation
problems, and accepts material that already has an independent verification
receipt. It cannot substitute editorial confidence for verification and cannot
publish.

### Referee

The referee validates exact subjects against frozen rules and records
`ACCEPTED`, `REJECTED`, or the relevant epistemic verification state. It may not
author the candidate, run production actions, or publish. Existing `tier run`
semantics remain the authoritative implementation for action-task adjudication.

### Auditor

The auditor challenges receipts, source sufficiency, custody, and claimed
independence. It may refute a conclusion without becoming the new referee or
candidate author. A cross-lineage audit is useful only when the different
lineage and source exposure are recorded.

### Archivist

The archivist preserves evidence, deduplicates equivalent observations, tracks
which editions and decisions depend on which evidence, and marks downstream
objects for reopening when custody or source validity changes. It cannot decide
that the reopened claim is correct.

### Corrections desk

The corrections desk watches accepted and published claims for expired sources,
changed assumptions, failed forecasts, superseding receipts, and material
contradictions. It opens a correction and traces dependents. A reporter prepares
the correction, a referee verifies it, and the publisher republishes it.

### Production desk

The production desk maps to the supervised action plane. It may execute a
publisher-authorized task, interrupt a process tree, and record infrastructure
failure. It cannot authorize, author, validate, merge, or publish the work.

### Chair

A Chair is an invited external analyst or reasoning surface. Its return is an
untrusted submission. The Chair may submit and nothing more. A marker, branch,
author identity, or plausible pull request cannot grant queue, validation,
execution, merge, or publication authority.

## 6. Objects and custody

The newsroom distinguishes the following objects because each carries a
different burden and authority.

| object | custody meaning | action authority |
|---|---|---|
| tip | external or local signal, possibly incomplete | none |
| assignment | local scope, question, source policy, expiry, and burden | none |
| submission | externally authored return, including a Chair pull request | none |
| evidence packet | source set plus provenance and extraction history | none |
| candidate | proposed code, text, decision, or correction | none |
| receipt | verifier output bound to an exact subject and inputs | none by itself |
| edition | bounded synthesis of material changes | publication still requires publisher |
| correction | reopened claim and dependent map | publication still requires publisher |
| action task | local, bounded, publisher-gated execution envelope | may enter action plane only after authorization |

An external object may create an observation or, through a trusted intake
process, an approval-gated Draft. It may never become an executable object by
copying a token, marker, command, file path, or workflow convention. A trusted
local admission process creates the action task as a new object and records the
custody boundary.

Future external validation must bind an immutable subject snapshot before it can
exist. For a pull request this means, at minimum, an exact repository, base
commit, head repository, head commit, complete changed-file set, acquisition
method, content hashes, and an isolated workspace whose checked-out `HEAD`
matches the recorded head. That executor is explicitly absent from v1.

## 7. Two state machines

The newsroom keeps knowledge state separate from action state. Identical words
such as `ACCEPTED` must be interpreted within their named machine.

### Epistemic state

The v1 epistemic path is:

```text
OBSERVED -> TRIAGED -> ASSIGNED -> REPORTED -> VERIFIED -> ACCEPTED -> PUBLISHED
                                \-> SUBMITTED -> VERIFIED
```

`REPORTED` is an internal report. `SUBMITTED` is an external return. Both require
the referee before `VERIFIED`. The copy desk may move verified material to
`ACCEPTED`. Only the publisher may move accepted material to `PUBLISHED`.

Correction paths are explicit:

```text
ACCEPTED or PUBLISHED
  -> CORRECTION_OPEN
  -> CORRECTION_REPORTED
  -> CORRECTED
  -> PUBLISHED
```

The corrections desk opens the issue and traces dependents. A reporter authors
the revised material. A referee verifies it. The publisher decides whether to
republish. Open work may also become `KILLED` or `EXPIRED`; deletion is not the
default because the dead approach and its reason remain evidence.

### Action state

The action machine mirrors the current Tier Desk states:

```text
DRAFT -> QUEUED -> RUNNING -> ACCEPTED | REJECTED | ERROR | INTERRUPTED
   \         \          \-> CANCELED
    \----------------------> CANCELED
```

Only the publisher may move a Draft into `QUEUED`. The production desk may move
an already authorized queued task into `RUNNING`. Only the referee may adjudicate
`RUNNING` as `ACCEPTED` or `REJECTED`. Infrastructure paths remain `ERROR` or
`INTERRUPTED`. Retry returns a terminal failure to `DRAFT` and requires publisher
approval before it can queue again.

This separation prevents a verified article, accepted pull request, or trusted
source from being mistaken for an authorized action. It also prevents a
successful process exit from being mistaken for a verified result.

## 8. Standing editions

The first newsroom should produce three bounded editions. Their initial work in
progress limits are policy hypotheses for review, not measurements.

### Daily project edition

The daily project edition consumes task state, verified run receipts, repository
deltas, and source freshness. It reports only material changes, decisions needed
from the publisher, newly blocked or unblocked work, and evidence failures. Its
valid empty result is `NO_MATERIAL_CHANGE`. The proposed limit is twelve items.

### Weekly investigations edition

The weekly investigations edition maintains at most five open questions. It
compares evidence for and against each hypothesis, records contradictions and
failed approaches, and names the next discriminating observation or decision.
It should close or kill an investigation rather than preserve motion without a
burden.

### Monthly corrections edition

The monthly corrections edition revisits accepted claims, expired sources,
changed assumptions, failed forecasts, and superseding receipts. It emits a
correction ledger and a dependent map. Its valid empty result is
`NO_CORRECTION_REQUIRED`. This edition is mandatory because a durable knowledge
system without reopening semantics accumulates confident rot.

V1 does not schedule these editions, invoke a model to write them, or publish
them. The first implementation should be a read-only deterministic projection
from existing Desk and repository evidence. Model-assisted synthesis can be
considered only after the projection, source binding, and no-change behavior are
stable.

## 9. Attention policy for one publisher

A newsroom can make the human bottleneck worse by producing more material than
one publisher can adjudicate. Every beat therefore needs:

- a finite work in progress limit;
- a review or expiry date;
- a kill criterion;
- a materiality threshold;
- a valid no-change result;
- one next control question rather than an unbounded recommendation list.

An alert should reach the publisher only when a material delta, deadline,
evidence conflict, or authority decision exists. Routine observation should be
archived and deduplicated without demanding ceremonial review.

The Desk should measure the cost of editorial closure, not only the cost of
model calls. Useful measures include items opened versus killed, age of open
investigations, corrections per accepted claim, publisher decisions requested,
false escalation rate, and verified decisions per unit of human attention.
These measures are currently unmeasured and must be labeled accordingly.

## 10. Applications implied by the architecture

The newsroom is useful wherever one principal needs persistent, evidence-bound
attention across more questions than they can personally keep resident.

### Repository and software operations

Issues become tips, reproductions become reporting, candidate patches become
submissions, tests become fact checking, releases become editions, and
regressions become corrections. Standing beats can monitor dependency changes,
security advisories, flaky tests, performance drift, documentation claims,
stale feature flags, and abandoned work. Any candidate action still passes
through the existing publisher-gated Tier Desk and `tier run` boundary.

### Research and intelligence

Separate beats can maintain literature, competitors, standards, regulation,
scientific disputes, or technology ecosystems. A report records claims and
sources. A referee checks quotations, numbers, and methods. A corrections desk
reopens conclusions when a paper is retracted, replicated, superseded, or shown
to rely on a failed assumption. The value is maintained comparison over time,
not one more summary.

### Incident response

During an incident, different roles can own timeline reconstruction, system
state, dependency status, customer impact, mitigation options, and
communications. Their evidence remains separate until editorial synthesis. The
production desk performs only explicitly authorized mitigations. The archive
preserves what was believed at each time so the postmortem does not rewrite the
incident history.

### Product, customer, and vendor intelligence

A customer beat can preserve minority signals and distinguish repeated comments
from convergent evidence. A vendor beat can track pricing, terms, reliability,
security posture, integration cost, and exit cost. Renewal or product decisions
then draw on a continuing evidence record instead of a hurried reconstruction.

### Due diligence and personal operations

Financial, technical, legal, market, and customer desks can investigate in
parallel while preserving independent burdens. For one person's operations, the
same mechanism can maintain commitments, decisions, correspondence follow-ups,
renewals, household systems, and administrative deadlines. Medical, legal, and
financial beats should organize records and questions for qualified
professionals rather than impersonate those professionals.

### Procedure compilation and organization design

A successful one-off run can be compiled into a reusable cartridge with frozen
inputs, source policy, acceptance, escalation, and receipt requirements. The
role topology can also be tested before hiring or formalizing a team. Redundant
roles, missing custody owners, and approval bottlenecks become observable in the
state transitions rather than remaining organizational intuition.

### Method competition and decision escrow

Multiple methods may address the same bounded assignment under a common
referee. Tier Bench can compare verified yield, latency, cost, correction burden,
and failure mode against the operator's real work. Separately, the newsroom can
prepare an action and accumulate evidence while enforcing a threshold before
commitment. Preparation does not imply authority.

### Federation and auditability

Separate Desks may eventually exchange signed evidence packets or receipts
without sharing execution authority. That supports open-source projects,
research collectives, and organizations with local policies. The portable audit
record may become more valuable than any individual agent because it explains
which subject, source set, role, lineage, tool access, verifier, cost, and
approval produced an outcome.

## 11. OSS commodity boundary

`docs/oss-commodity-sweep.md` records the initial sweep. The adoption rule is to
buy commodity plumbing without outsourcing authority semantics.

The first low-cost candidates are read-only secret and vulnerability beats,
read-only SQLite exploration, and periodic repository security posture reports.
They must produce evidence packets or receipts, never actions. Supply-chain
attestation formats are promising for portable custody, but they should map onto
existing `tier run` receipts rather than create a second verdict system.

Workflow engines, policy engines, and in-memory state-machine libraries are not
current shortcuts. Tier Desk already owns transactional SQLite state,
dependency gates, process custody, and a supervised scheduler. Replacing those
with a commodity framework before a demonstrated scaling boundary would add
failure surfaces and split authority.

## 12. Implementation sequence

### Phase 0: existing foundation

Keep Tier Bench, `tier run`, Tier Desk, CRATE OPS, and the repaired Chair intake
as the current authority-bearing system. Do not broaden Chair intake.

### Phase 1: ratify the review contract

Review `newsroom.json`, this document, the validator, and the negative witnesses.
No production code imports the manifest. Changes to role powers or transitions
require an explicit schema revision and renewed review.

### Phase 2: deterministic read-only editions

Build a projection command that reads committed repository state, Desk snapshots,
and verified receipts and emits the three edition schemas with source bindings.
It may not mutate the Desk or call a model. The first acceptance burden is that
unchanged inputs produce `NO_MATERIAL_CHANGE` and byte-stable output.

### Phase 3: standing beats that create observations and Drafts

Optional observers may append deduplicated observations and propose assignments.
They may create only approval-gated Drafts through trusted local admission. They
may not queue, execute, or publish. Every observer needs source freshness,
timeouts, bounded enumeration, and a retryable failure state.

### Phase 4: immutable-subject validation proposals

An external-validation executor, if still desirable, is a separate security
project. It must acquire and hash an immutable subject in an isolated workspace,
use a fixed validation profile, make zero provider calls unless separately
authorized, and preserve the operator checkout. Chair markers remain intake
hints rather than capabilities.

### Phase 5: publication and federation

Publication workflows, signed attestations, and cross-Desk exchange remain
separate proposals. The publisher transition and local policy boundary must
survive any transport or signing technology.

## 13. Review burden

Review should answer whether the classification is accurate, whether any role
can cross an authority ceiling through a state transition, whether the two state
machines preserve current Desk semantics, whether the standing editions are
worth their attention cost, and whether the proposed OSS commodities remain
read-only evidence sources.

The governing control question is: **which state transitions may each role
perform autonomously, and which transitions must remain under the publisher's
explicit authority?**
