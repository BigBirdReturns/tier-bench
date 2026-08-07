# MARY operator-aperture treatment

This laboratory verifies MARY operator-aperture artifacts without importing the
MARY package or reading a MARY checkout. The laboratory receives three external
JSON artifacts:

```text
operator-aperture plan
operator-aperture canary verdict
owned-read response
```

It verifies their canonical self-digests, exact plan/verdict/response
cross-bindings, deterministic ownership law, cartridge coverage, candidate-only
authority, evidence references, read-only machine sessions, and route usage.

The committed fixtures are sanitized structural examples. They do not contain
the private MARY artifacts or any live Tier Desk, AXM Chat, KimiLab, user-memory,
or machine evidence. A local laboratory may point the same command at exact
private artifacts without changing this repository.

## Run

```console
python -m tier_runner.mary_aperture_treatment \
  --plan labs/mary-aperture-treatment/fixtures/plan.json \
  --verdict labs/mary-aperture-treatment/fixtures/verdict.json \
  --response labs/mary-aperture-treatment/fixtures/response.json \
  --output /tmp/mary-aperture-treatment.json
```

The committed sanitized receipt is deterministic:

```text
labs/mary-aperture-treatment/SANITIZED-TREATMENT-RECEIPT.json
```

## Provider-free law

The default treatment refuses a packet that:

- lets a model decide ownership;
- marks an unowned clause claimable;
- gives an owned clause no covering cartridge;
- widens candidate-only authority;
- loses evidence references;
- uses a non-read-only machine;
- routes to the internet or a frontier model;
- attempts mutation;
- introduces an aggregate score, winner, or readiness field;
- fails any canonical digest or cross-binding.

`--allow-external-routes` permits recording internet or frontier use for a later
supplier-market treatment. It does not grant the supplier authority or accept
its result.

## Claim boundary

A pass proves the supplied artifact packet is internally consistent under this
treatment contract. It does not qualify the live sources, the truth of the
answers, model quality, hardware, safety, mutation authority, production use, or
field use. TierBench recommends and measures routes; it does not answer the
operator's question or decide what MARY owns.
