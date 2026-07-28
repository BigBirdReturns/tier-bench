# Supplier Foundry continuity

Supplier Foundry is a bounded qualification organ inside Tier Bench. It turns exact external supplier products into measured, substitutable, removable capability providers without allowing the supplier, adapter, benchmark, or current maintainer to acquire domain authority.

## Stable mission

Supplier Foundry may acquire, isolate, execute, measure, compare, package, substitute, revoke, and remove suppliers under a human-owned capability contract. It may emit a measurement recommendation for the exact tested context.

It may not define the domain capability, choose estate policy, accept evidence or outcomes, mutate Arc law or campaigns, schedule the estate, or infer that a supplier wins outside the measured fixture and budget.

## Current accepted pilot

The first accepted capability is:

```text
asset.optimize.gltf/v1
```

The exact providers are pinned in `package-lock.json`; the human-owned mission, authority membrane, limits, and policy are in `supplier_manifest.json`; the dependency-free semantic and bundle verifiers are `verify_asset.py` and `verify_bundle.py`; the permanent qualification gate is `.github/workflows/supplier-foundry-asset-pilot.yml`.

A successor must preserve the source fixture, exact package integrity, two-run determinism, semantic equivalence, source fallback, network quarantine, product and resource receipts, and the supplier-independent rip-out test. The selected provider remains a measurement recommendation rather than a mandate.

## Recovery

```bash
cd supplier_foundry
npm ci --ignore-scripts --no-audit --no-fund
python -m unittest discover -s tests -v

AXM_SUPPLIER_REQUIRE_NETWORK_QUARANTINE=1 \
AXM_SUPPLIER_NETWORK_WRAPPER='sudo unshare --net --' \
python qualify.py --output ../.supplier-foundry-run

rm -rf node_modules
python ../.supplier-foundry-run/bundle/tools/verify_bundle.py \
  ../.supplier-foundry-run/bundle --finalize
python ../.supplier-foundry-run/bundle/tools/verify_bundle.py \
  ../.supplier-foundry-run/bundle
```

An unavailable supplier must not make the source, prior product, fallback, or receipt unreadable. A replacement supplier enters as another provider behind the same capability contract and must pass the same verifier. A changed capability requires a new capability ID or a reviewed contract migration.

## Change discipline

Before adding a supplier class or broadening the verifier, record:

1. the capability and its owner;
2. the canonical input and output products;
3. exact suppliers and licenses;
4. semantic equivalence and known omissions;
5. budgets and platform context;
6. fallback behavior;
7. substitution and rip-out procedures;
8. authority exclusions;
9. independent evidence limits;
10. the rollback point.

Do not generalize from the synthetic triangle fixture to production assets, Unity, Quest, textures, animation, skins, morphs, compression, or GPU behavior. Those require separate fixtures and receipts.

## Control question

Can the next maintainer replace every current supplier while preserving the capability contract, canonical products, evidence, fallback, and independent verification without inheriting an undocumented vendor dependency or expanding Supplier Foundry's authority?
