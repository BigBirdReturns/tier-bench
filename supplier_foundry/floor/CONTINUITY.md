# Asset Floor continuity

The Asset Floor is a contract and conformance layer inside Supplier Foundry. Its
stable mission is to let independently maintained tools, models, standards, DCCs,
engines, marketplaces, and artists contribute bounded production capabilities
without becoming the identity or authority of an asset.

## Stable identity

```text
catalog   axm-asset-floor-catalog/1
intent    axm-asset-intent/1
evidence  axm-asset-qualification/1
report    axm-asset-floor-report/1
```

Semantic identities are canonical SHA-256 digests. Provider names, file paths,
timestamps, repository location, and current maintainer are not identity.

## Authority

The floor may validate contracts, classify per-gate evidence, report provider and
license coverage, preserve gaps, and construct content identities.

It may not:

- generate or alter an asset;
- select a provider for the estate;
- authenticate a mandate;
- accept a product;
- define game law;
- mutate a campaign;
- schedule a job;
- erase a failed, open, or warning gate;
- infer production readiness from a fixture or benchmark.

## Recovery

```bash
python supplier_foundry/floor/asset_floor.py validate \
  --catalog supplier_foundry/floor/catalog.json \
  --intent supplier_foundry/floor/examples/underdrain-valve.asset-intent.json \
  --intent supplier_foundry/floor/examples/underdrain-boss-toad.asset-intent.json

python -m unittest discover -s supplier_foundry/floor/tests -v
```

The implementation is standard-library only. A successor must be able to validate
and render the committed report without any supplier runtime, network, engine, DCC,
or model.

## Replacement law

A provider can be replaced without changing the asset intent. A format or standard
can be replaced only through an explicit capability migration. A human correction
creates a retained delta or lineage branch. A failed supplier cannot make accepted
source, products, credits, receipts, or fallbacks unreadable.

## Maintainer transfer

A new maintainer should verify:

1. catalog and example identities reconstruct;
2. duplicate keys and floats fail closed;
3. provider authority remains `none`;
4. profile gate sets cannot be weakened by an intent;
5. a failed hard gate blocks classification;
6. open gates hold and warnings restrict to pilot;
7. no aggregate score exists;
8. the report reconstructs byte-for-byte;
9. every new supplier remains unqualified until evidence exists;
10. community and benchmark claims stay separate from local acceptance.

The control question is whether a new maintainer can remove every current provider
record and still understand the asset contract, open gaps, required evidence,
fallbacks, and route to independent acceptance.
