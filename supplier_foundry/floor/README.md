# AXM Asset Floor v1

The Asset Floor is the provider-neutral production contract above Supplier Foundry.
It exists so game teams, tool authors, researchers, marketplaces, and engine vendors
can contribute useful asset machinery without forcing every consumer to adopt the
supplier's identity, prompt format, file layout, license assumptions, or definition
of "game ready."

The floor does **not** generate an asset and does **not** select or accept a supplier.
It defines the canonical objects and independent gates that let many generators,
standards, DCC tools, engines, validators, and human artists participate in one
reconstructable production path.

## Governing separations

```text
asset intent          != prompt
capability            != supplier
design reference      != generated candidate
candidate             != production product
format validity       != engine validity
engine validity       != gameplay readability
supplier benchmark    != local acceptance
evidence              != authority
recommended provider  != vendor mandate
```

There is no aggregate readiness percentage. A failed authority, license, gameplay,
security, or engine gate cannot be averaged away by strong geometry or attractive
renders.

## Canonical records

| Record | Identity | Purpose |
|---|---|---|
| `axm-asset-floor-catalog/1` | `assetfloor1_…` | Capability, profile, provider, gate, and gap registry |
| `axm-asset-intent/1` | `assetint1_…` | Human-owned gameplay, art, budget, provenance, and fallback contract |
| `axm-asset-qualification/1` | `assetqual1_…` | Independent per-gate evidence |
| `axm-asset-floor-report/1` | `assetfloorreport1_…` | Coverage, concentration, license, and open-gap report |
| future `axm-asset-product/1` | `assetprod1_…` | Accepted source, variants, receipts, credits, and fallback |

All semantic JSON is duplicate-key refusing and integer-only. Identity is canonical
SHA-256 over the content rather than filenames, timestamps, provider narration, or
repository location.

## Profiles

The core catalog currently defines:

```text
3d_prop
3d_mechanism
3d_character
3d_creature
3d_environment_kit
material
animation_clip
vfx
audio
ui
```

Profiles select exact required gates and capabilities. A provider is never named in
an asset intent. The same intent can therefore be executed through local open
weights, procedural code, a DCC tool, a hosted service, or a human workflow and
compared without changing the asset's identity or game contract.

## Production tiers

```text
Tier 0  design reference
Tier 1  generated candidate
Tier 2  structurally qualified candidate
Tier 3  engine-qualified product
Tier 4  human-accepted product
```

A GLB that opens is not Tier 3. A rig that plays one idle clip is not Tier 3. A
studio render is not evidence that a weak point or valve reads at play distance.
Tier 4 requires a named human authority in the real product venue.

## Standards spine

The floor consumes existing standards instead of replacing them:

```text
OpenUSD                 composition, layering, variants, long-lived authoring
glTF                    efficient delivery products
MaterialX / OpenPBR     portable material intent
KTX2 / Basis Universal  portable compressed textures
OpenAssetIO             stable entity references and product resolution
KHR_interactivity       constrained portable behavior graphs
C2PA / SPDX / in-toto   provenance, license, and process attestations
```

These standards remain suppliers of bounded capability. An OpenUSD stage, glTF
asset, MaterialX graph, or C2PA manifest still must satisfy the asset intent and
engine/gameplay gates.

## What the first catalog exposes

The catalog contains 26 capabilities, 22 independent gates, 10 profiles, 44
discovered suppliers or standards, and 20 open or emerging production gaps.
Only the already accepted `asset.optimize.gltf/v1` pilot has fixture-qualified
suppliers. Every other entry is deliberately unqualified until an exact adapter,
fixture, verifier, budget, license review, fallback, and rip-out receipt exist.

The two worked intents are:

```text
UNDERDRAIN pressure-release valve assembly
UNDERDRAIN Crown toad boss
```

They demonstrate semantic parts, sockets, interactions, state transitions,
platform budgets, style family, provenance, license policy, and neutral fallbacks.

## Local use

```bash
python supplier_foundry/floor/asset_floor.py validate \
  --catalog supplier_foundry/floor/catalog.json \
  --intent supplier_foundry/floor/examples/underdrain-valve.asset-intent.json \
  --intent supplier_foundry/floor/examples/underdrain-boss-toad.asset-intent.json

python -m unittest discover -s supplier_foundry/floor/tests -v

python supplier_foundry/floor/asset_floor.py report \
  --catalog supplier_foundry/floor/catalog.json \
  --intent supplier_foundry/floor/examples/underdrain-valve.asset-intent.json \
  --intent supplier_foundry/floor/examples/underdrain-boss-toad.asset-intent.json \
  --output /tmp/asset-floor-report.json

cmp /tmp/asset-floor-report.json \
  supplier_foundry/floor/examples/floor-report.json
```

## Contribution contract

A provider contribution must add a candidate supplier record, exact acquisition,
a bounded adapter, one or more shared fixtures, independent verification, license
and output-rights review, resource receipts, fallback, substitution, and rip-out.
It may not add provider-specific fields to `axm-asset-intent/1`.

A benchmark contribution must preserve external results as a separate evidence
plane. It may challenge or prioritize a local experiment but cannot promote a
provider into an engine or product route.

A new profile or capability requires a contract migration, a failure default, and
at least one negative witness.

## Authority membrane

Supplier Foundry and the Asset Floor may acquire, isolate, execute, compare,
measure, package, revoke, and recommend. They may not define game law, authenticate
a mandate, schedule the estate, accept an asset, mutate a campaign, or publish a
provider winner outside the exact measured context.

The control question is whether two different supplier chains can begin from the
same asset intent and produce substitutable products that preserve required parts,
behavior anchors, visual identity, engine budgets, provenance, and fallback while
neither supplier becomes the definition or authority of the asset.
