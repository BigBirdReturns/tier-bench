# OSS commodity sweep for Tier Desk

Sweep date: 2026-07-21. Evidence was taken from official project repositories
and documentation. This is a decision ledger, not an installation manifest.
Every adopted binary or action still needs an exact version, checksum or commit
pin, license review, and a frozen provider-free acceptance crate.

The selection rule is to buy commodity observation, reporting, and attestation
formats while preserving Tier Desk's local authority semantics. A scanner may
produce an evidence packet. It may not queue remediation, install dependencies,
rewrite a lockfile, execute an untrusted package manager, change Desk policy, or
convert its own finding into an accepted result.

## Decision summary

| commodity | decision | likely gain | integration boundary |
|---|---|---|---|
| SQLite backup API and integrity checks | adopt first | consistent read-only Desk snapshots with zero new dependency | local export only; never a second state store |
| Gitleaks CLI | adopt as an optional security beat | cheap secret-history and working-tree detection with redacted SARIF or JSON | read-only scan; finding is evidence; no automatic history rewrite or secret handling |
| OSV-Scanner | adopt as an optional dependency beat | broad lockfile, source, container, license, and offline vulnerability scanning | scan mode only; never run guided remediation on untrusted input |
| OpenSSF Scorecard | adopt as a periodic external beat | commodity repository-security posture and dangerous-workflow checks | advisory evidence only; no pass authority |
| Datasette | prototype locally | immediate query and browsing surface over Desk evidence without custom UI work | serve a consistent read-only snapshot on loopback, never the live writable database |
| in-toto attestation model | prototype against existing receipts | portable subject, materials, products, functionary, and verification vocabulary | map `tier run` evidence; do not create a second verdict system |
| Witness | prototype only after the in-toto mapping | one binary for in-toto attestations, policy, signing, and air-gap transport | offline fixture first; its policy engine cannot replace Desk admission |
| OpenTelemetry | defer | standard traces and metrics export | derived observability only after event names stabilize; event ledger remains authoritative |
| pip-audit | defer to trusted Python environments | useful Python-specific audit and SBOM output | never audit an input that would be unsafe to install or resolve |
| Cosign | defer until receipts leave the machine | signing and verification for in-toto attestations and artifacts | identity, transparency, and key custody require a separate design |
| OPA | defer | general policy language and engine | current policy is small, local, and transaction-bound; Rego would add a second authority surface |
| Temporal | reject for the current scale | durable distributed workflows | requires a Temporal server and duplicates the local Desk scheduler and custody model |
| APScheduler | reject for the current scale | commodity persistent schedules and triggers | duplicates existing SQLite schedule, claim, and restart semantics |
| pytransitions | reject as the state authority | concise in-process finite-state modeling | does not supply transactional durability, cross-process custody, or the event ledger |

## 1. Zero-dependency gain: consistent SQLite evidence snapshots

Tier Desk already uses SQLite in WAL mode as its authoritative control database.
Before adopting a separate evidence browser, add a deterministic export path
using Python's `sqlite3.Connection.backup()` or SQLite's equivalent online
backup mechanism. Copying only `desk.sqlite3` while the WAL is active can omit
committed pages or produce a snapshot with ambiguous custody.

The export should:

1. open the authoritative database read-only where practical;
2. create a new snapshot through the SQLite backup API;
3. run `PRAGMA quick_check` or the stronger `PRAGMA integrity_check` on the
   snapshot;
4. hash the snapshot and record source database identity, export time, schema
   version, and event-ledger head;
5. expose only the snapshot to exploratory tools;
6. delete or rotate snapshots under an explicit retention rule.

This is the first commodity gain because it enables read-only analytics without
introducing a second writer, a second schema, or a network dependency.

## 2. Adopt: Gitleaks CLI as a secret-observation beat

Upstream: <https://github.com/gitleaks/gitleaks>

Gitleaks is an MIT-licensed standalone scanner for git history, directories,
files, and standard input. It supports JSON and SARIF reports, redaction,
baselines, target-size limits, and explicit timeouts. The upstream project now
describes the engine as feature complete and expects future releases to focus on
security patches, which is acceptable for a commodity scanner but argues for a
replaceable adapter.

The recommended Desk boundary is a pinned CLI binary, not a Python runtime
dependency. A `security_secret_scan_v1` crate should scan either the trusted
operator checkout or a separately acquired immutable subject. It should use
full redaction, a bounded timeout and target size, and a machine-readable report.
The receipt should contain fingerprints, rule identifiers, paths, commit
coordinates where relevant, scanner version, configuration hash, and report
hash. It must not store the detected secret value.

A finding opens an observation. It does not rotate a credential, rewrite git
history, comment on a pull request, or fail an unrelated acceptance command
unless the publisher separately ratifies that policy.

Use the CLI initially rather than `gitleaks-action`. The action has a separate
license from the MIT CLI, requires a license key for organization-owned
repositories, and can comment on pull requests using `GITHUB_TOKEN`. The local
CLI has a smaller permission and licensing surface. A future workflow can still
be considered after its action commit, permissions, reporting behavior, and
license are frozen.

## 3. Adopt: OSV-Scanner as a dependency and license beat

Upstream: <https://github.com/google/osv-scanner>

OSV-Scanner is Apache-2.0 and supports broad source, lockfile, container,
license, and offline vulnerability scanning. Its offline mode can use a local
OSV database after the database is downloaded, which gives Tier Desk a useful
privacy and reproducibility option. Online scans may send package names,
versions, ecosystems, and some file hashes to upstream services, so the receipt
must name the data surface and mode.

The recommended boundary is scan-only. A `security_osv_scan_v1` crate should:

- pin the scanner binary and database snapshot or record the online source time;
- enumerate the scanned manifests and lockfiles;
- use offline mode for private or frozen evaluations;
- retain normalized vulnerability identifiers, affected package coordinates,
  severity evidence when supplied, and the raw report hash;
- produce an observation or correction candidate rather than a dependency PR.

Do not run OSV-Scanner's experimental guided-remediation `fix` command on an
untrusted project. Upstream warns that remediation may invoke package managers,
execute scripts, or follow external registries declared by the project. That is
an execution surface and belongs behind a separate publisher-authorized action
task in an isolated workspace.

OSV-Scanner should be preferred over adding a Python-only audit as the first
beat because the repository and its future estate may contain multiple package
ecosystems.

## 4. Adopt: OpenSSF Scorecard as a periodic external signal

Upstream: <https://github.com/ossf/scorecard>

Scorecard provides commodity security-health checks for open-source projects,
including dangerous workflow patterns, branch protection, dependency update
practice, token permissions, and related posture. It offers an official GitHub
Action, command-line interface, and public API. The public API's weekly scans
omit some checks, so the receipt must distinguish API evidence from a
repository-owned action run.

Use Scorecard as a weekly or monthly reporter beat. It may open an investigation
when a score or check changes materially. It must not become a binary acceptance
criterion because some checks are contextual, API results can be incomplete,
and the score is external evidence rather than the project referee.

A future Action adoption should pin every action by full commit SHA, minimize
permissions, disable checkout credential persistence, and preserve the raw SARIF
or JSON report. The first experiment can instead consume the public API from a
read-only observer to avoid changing workflow authority.

## 5. Prototype: Datasette over an immutable Desk snapshot

Upstream: <https://datasette.io/> and
<https://docs.datasette.io/en/stable/>

Datasette can expose SQLite tables, facets, SQL queries, JSON, and CSV through a
small local web application. Its immutable mode and permission system make it a
strong commodity candidate for ad hoc Desk evidence exploration. It could
provide immediate value for questions such as task aging, failure reasons,
cost by role, correction frequency, source freshness, event sequences, and the
human editorial-closure burden.

Do not point Datasette at the live Tier Desk database. Produce a consistent
snapshot through the export procedure above, hash it, and serve that snapshot on
loopback. Disable database download unless explicitly needed, do not expose it
through `--unsafe-network`, and assume task text, paths, logs, and external
references may be sensitive even when provider secrets are absent.

The prototype should remain an operator tool. It does not become the Desk API,
state writer, authentication system, or publication surface.

## 6. Prototype: in-toto vocabulary for portable receipts

Upstream: <https://github.com/in-toto/in-toto> and
<https://github.com/in-toto/attestation>

in-toto models a supply-chain layout, authorized functionaries, materials,
products, signed link metadata, and verification rules. Those concepts align
with several existing Tier Bench objects:

| Tier Bench / Desk object | possible in-toto mapping |
|---|---|
| frozen task or run envelope | predicate and declared step |
| base commit, fixture, manifest, acceptance | materials |
| candidate patch and receipt files | products |
| backend adapter or referee identity | functionary metadata |
| `tier verify` result | verification evidence |
| `700.100` receipt | project-specific attestation predicate |

The initial work should be a pure mapping exercise against existing receipts.
It should demonstrate lossless round-trip of subject hashes, materials,
products, verdict, reason, lineage, and cost without changing who has verdict
authority. in-toto verification may confirm provenance properties, but only the
existing referee decides whether the task is accepted.

Do not adopt an in-toto layout as the Desk scheduler or policy kernel in the
first pass. The project already has a local task DAG, execution envelope, and
referee. The commodity value is interoperability and portable custody.

## 7. Prototype later: Witness as an attestation carrier

Upstream: <https://github.com/in-toto/witness>

Witness is Apache-2.0 and implements in-toto attestations. It also includes an
OPA Rego policy engine, Sigstore and SPIFFE/SPIRE signing options, timestamping,
attestation storage, and air-gap transport. This can compress several future
supply-chain features into one replaceable binary.

That breadth is also the risk. The first Witness experiment should be offline,
provider-free, and restricted to a synthetic receipt fixture. It should verify a
project-specific attestation without process tracing, network signing,
attestation storage, or policy enforcement. Only after the predicate mapping is
stable should the project compare Witness with a smaller direct in-toto
implementation.

Witness policy success is not a Tier Bench verdict. It may verify that required
attestations exist and satisfy a transport policy. The local referee retains
acceptance authority.

## 8. Defer: OpenTelemetry as derived observability

Upstream: <https://github.com/open-telemetry/opentelemetry-python>

OpenTelemetry Python currently marks traces and metrics stable while logs remain
in development. A later adapter could export Desk poll duration, queue latency,
run duration, worker termination, observer freshness, edition generation, and
publisher-decision latency to an existing collector.

The current event ledger is already the auditable source of truth. OpenTelemetry
should therefore be an optional one-way projection with no control path back
into the Desk. Adopting it before event names, cardinality, and privacy rules are
stable would create telemetry churn and another dependency without changing the
operator's decisions.

## 9. Defer: pip-audit to trusted Python environments

Upstream: <https://github.com/pypa/pip-audit>

pip-audit is Apache-2.0, supports PyPI and OSV sources, emits JSON and CycloneDX,
and can audit installed environments or requirements files. It is useful when a
Python environment is already trusted and fully resolved.

Its own security model states the relevant boundary plainly: an input that is
unsafe to install is unsafe to audit through dependency resolution. It may need
to resolve requirements with behavior comparable to `pip install`. For that
reason it is not the first tool for untrusted Chair or estate inputs. OSV-Scanner
provides a broader initial beat. pip-audit can later complement it inside a
trusted, prebuilt Python environment with `--fix` disabled.

## 10. Defer: Cosign until attestations cross a trust boundary

Upstream: <https://github.com/sigstore/cosign>

Cosign supports signing and verifying binaries, containers, and in-toto
attestations. It is useful when a receipt or release leaves the local Desk and a
remote verifier needs a portable identity and integrity claim.

Current Tier Desk evidence remains local and repository-custodied. Adding
keyless identity, transparency-log participation, key custody, or bundle
verification now would precede the actual exchange protocol. Revisit Cosign
when the project has a ratified attestation predicate and a real external
consumer. Pin a current security-patched release and freeze online versus
offline verification behavior in that proposal.

## 11. Defer: OPA as a policy engine

Upstream: <https://www.openpolicyagent.org/>

OPA is a mature Apache-2.0 policy engine with the Rego language. It is a good
commodity when multiple systems need a shared policy service or when policy
must be authored and distributed independently of application code.

Tier Desk's current authority rules are small, transaction-bound, and directly
connected to SQLite state changes. The new newsroom contract is deliberately
stdlib-only and frozen. Introducing Rego now would create a second policy
language, evaluation runtime, packaging path, and failure mode without removing
the need for atomic database enforcement. Revisit OPA only when there are
multiple policy consumers or external policy authors and a clear conformance
suite exists.

## 12. Reject for current scale: replacement workflow and FSM frameworks

### Temporal

Upstream: <https://github.com/temporalio/sdk-python>

Temporal supplies durable distributed workflows, retries, timers, workers, and
workflow history, but it requires a Temporal server. Tier Desk currently runs
one local repository with SQLite custody, one scheduler, supervised process
trees, and verified run directories. Temporal would add an external service and
split the event and retry authority before distributed scale exists.

### APScheduler

Upstream: <https://github.com/agronholm/apscheduler>

APScheduler has persistent SQLite, PostgreSQL, MySQL, and MongoDB stores plus
cron, interval, calendar, and one-off triggers. Those are useful commodity
features, but Tier Desk already stores schedules, claims tasks atomically,
recovers interrupted work, and controls a bounded worker. Replacing the small
current scheduler would risk semantic drift in approval, dependency, and
receipt adoption for little immediate gain.

### pytransitions

Upstream: <https://github.com/pytransitions/transitions>

pytransitions is an MIT-licensed lightweight object-oriented finite-state
machine with hierarchical, graph, lock, and async extensions. It may be useful
for visualization prototypes, but it does not supply the transactional database
transition, cross-process ownership, custody record, or event ledger that Tier
Desk requires. The state machine belongs next to the data transaction, not in an
in-memory object graph.

## 13. First four commodity crates

The following provider-free crates would test the adoption claims without
changing production authority.

### `desk_sqlite_snapshot_v1`

Freeze a temporary Desk database with WAL activity, export it through the SQLite
backup API, run integrity checks, bind the event-ledger head and SHA-256, and
prove the snapshot is read-only and internally consistent. This is the gate for
Datasette or any analytics tool.

### `security_secret_scan_v1`

Run a pinned Gitleaks CLI against a synthetic repository containing known test
secrets and non-secrets. Require full redaction, bounded runtime, stable
fingerprints, JSON or SARIF output, and zero secret bytes in stdout, logs, and
the receipt.

### `security_osv_scan_v1`

Run a pinned OSV-Scanner and frozen offline database against synthetic lockfiles
with one vulnerable and one clean package. Require no network, no package
manager invocation, no file mutation, exact database identity, and a normalized
observation receipt.

### `scorecard_snapshot_v1`

Acquire one public Scorecard result, record source time and omitted-check
semantics, normalize check deltas, and prove that the output can only create an
observation. A changed score must not queue or reject a Tier Desk action task.

## 14. Adoption control question

For every commodity, ask: **does this tool replace undifferentiated plumbing
while remaining an evidence producer, or does it quietly acquire authority over
admission, execution, validation, or publication?**
