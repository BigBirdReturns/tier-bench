# Contributing to the AXM Asset Floor

The floor accepts capabilities, providers, fixtures, verifiers, migrations, and
engine venues. It does not accept provider marketing as evidence or provider
schema fields in the human-owned asset intent.

## Contribution classes

### Capability

A capability proposal must define:

1. stable capability ID and owner;
2. canonical input and output objects;
3. required independent gates;
4. authority exclusions;
5. failure default;
6. neutral fallback;
7. at least one negative witness;
8. migration from any superseded capability.

### Provider

A provider proposal must include:

```text
exact source, package, service, model, or weight identity
reported license and independent review state
execution class and hardware envelope
network, filesystem, shell, and subprocess policy
bounded adapter
shared fixture
two-run determinism or an explicit stochastic protocol
resource measurements
independent semantic verification
known omissions
substitution and rip-out procedure
```

A provider begins in `discovered`. A manifest does not make it qualified.

### Fixture

Fixtures should be small enough for community reproduction and difficult enough to
exercise the declared seam. The first public corpus should include:

```text
mechanism: pressure-release valve
mechanism: opening root gate
prop: wrench-spear
modular kit: wall, floor, pipe, grate, and arch
creature: hopper
creature: shield brute
creature: boss toad
character: plumber hero
material: wet iron, rubber, skin, fungus, and water
animation: locomotion, dodge, attack, valve turn, hold-to-work
```

Every fixture carries source rights, units, axes, scale, semantic parts, sockets,
gameplay anchors, budgets, and hidden or withheld engine checks.

### Verifier

A verifier must be supplier-independent, resource-bounded, and fail closed on
unsupported features. It must retain exact input and output hashes and must never
promote evidence into asset acceptance.

### Engine venue

An engine venue must bind exact engine and importer versions, target hardware,
quality profile, product hash, scene fixture, camera, lighting, measurement window,
and output receipts. Engine success does not establish human readability.

## Pull request requirements

A pull request must state:

```text
classification
capability and profile scope
actors and authority
mechanism
exact receipts
license and provenance
upside
downside
failure mode
rollback
control question
```

Provider comparisons must retain every admissible product and the declared policy.
A recommendation is valid only for the exact fixture, platform, and budget.

## Prohibited shortcuts

- No aggregate readiness score.
- No "game ready" label based only on file export.
- No provider-specific field in `axm-asset-intent/1`.
- No unreviewed model, dataset, or output-rights assumption.
- No hidden network or runtime download.
- No shell string expansion for provider jobs.
- No writing into source references.
- No silent UV, skeleton, part, unit, axis, or material loss.
- No acceptance by the generator, benchmark, adapter, or viewer.
- No deletion of source or fallback after product generation.
- No social popularity as an evidence upgrade.

## Compatibility

Additive metadata may enter extensions. A changed semantic requirement creates a
new capability or profile version. Migrations must account for preserved, changed,
retired, introduced, forked, merged, and unexplained objects.

The rip-out test is mandatory: after deleting the provider runtime, the canonical
source, prior products, receipts, credits, fallback, and independent verifier must
remain usable.
