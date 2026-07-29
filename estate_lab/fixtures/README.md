# Estate Lab fixtures

`estate.example.json` is the retained internal estate manifest. The five scenarios under `scenarios/` exercise routing, authority, deterministic state, handoff, fault recovery, and cross-organ action flow.

`commodities.example.json` is the reviewed 81-candidate supplier and standards ledger. It is an acquisition map, not a claim that every upstream has been integrated.

The `floor/` directory is the public interoperability surface:

```text
floor.example.json                 normative floor specification
floor-gaps.example.json            executable gap ledger
reference-adapter/adapter.json     public adapter declaration
reference-adapter/adapter.py       zero-dependency reference implementation
vectors/*.json                     individual public vectors
```

The floor fixtures do not require the internal estate manifest. A third-party implementation may use only the floor specification, schemas, vectors, and command binding.
