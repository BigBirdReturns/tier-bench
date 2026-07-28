# Supplier Foundry: first commodity pilot

This directory is the first executable test of a Supplier Foundry organ. It does not create a universal package manager or control plane. It qualifies exact external suppliers behind one AXM-owned capability contract, preserves a supplier-independent source and verifier, and proves that the suppliers can be removed without losing the canonical product or its evidence.

The name is deliberately **Supplier Foundry**. It is unrelated to the Palantir Foundry exit work now owned by the GhostBox spoke.

## Organ boundary

Supplier Foundry may:

- acquire an exact supplier product;
- record package integrity, version, license, and source identity;
- execute it in a bounded job directory and network namespace;
- validate its output against an AXM-owned semantic contract;
- measure build time, peak resident memory, and product bytes;
- compare qualified providers under a declared policy;
- package source, products, receipts, and independent verification tools;
- prove substitution and rip-out;
- recommend a provider for the measured fixture.

Supplier Foundry may not:

- define what the domain capability means;
- choose estate policy;
- accept evidence or an action outcome;
- mutate Arc law or a campaign;
- schedule work across the estate;
- infer that one fixture proves production performance;
- turn a provider recommendation into a permanent vendor mandate.

## First capability

```text
asset.optimize.gltf/v1
```

The pilot compares two exact MIT-licensed OSS suppliers:

```text
@gltf-transform/cli 4.4.1
gltfpack            1.2.0
```

The fixture is a glTF 2.0 scene containing two reachable named triangle instances, deliberately duplicated mesh storage, and one unreachable duplicate mesh. The two providers may reorganize, quantize, deduplicate, or prune the internal representation, but their standard GLB products must preserve:

- reachable world-space triangle geometry;
- the scene count;
- total triangle count;
- world-space bounds;
- named-node world transforms.

The independent verifier uses only the Python standard library. It refuses compressed, sparse, skinned, morphed, or non-triangle products rather than silently approximating them.

## Qualification transaction

```text
exact package manifest
→ generated package lock with registry integrity
→ npm ci
→ provider execution in isolated job directories
→ two identical runs per provider
→ byte determinism
→ dependency-free semantic comparison
→ resource and size budgets
→ policy-bounded recommendation
→ source-preserving fallback
→ consumer bundle
→ delete node_modules
→ verify and finalize using bundled stdlib tools only
→ verify the final receipt again
```

The resulting bundle uses:

```text
axm-supplier-qualification/1
supplierqual1_<sha256>
```

The selected product is a measurement recommendation under the policy recorded in `supplier_manifest.json`. The original source remains the neutral fallback.

## Local reproduction

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

## Evidence limit

This pilot uses one synthetic static triangle fixture on one hosted Linux class. It establishes the acquisition, semantic-conformance, deterministic-product, substitution, fallback, and rip-out mechanics for this bounded surface. It does not establish visual quality, production asset compatibility, Unity import, Quest performance, texture quality, animation correctness, or GPU runtime cost.

The control question is whether either supplier can be upgraded, replaced, disabled, or removed while the same bounded asset semantics, source bytes, receipts, and verification path remain available without the supplier runtime.
