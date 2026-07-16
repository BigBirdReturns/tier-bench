# Luna/Sol Anchor Replication v2.2.1 Call-Count Correction

Date: 2026-07-16

Disposition: **PARTIAL_UNPAIRED_NO_CAPABILITY_VERDICT**

This additive note corrects one administrative count in the v2.2.1 prose. The corrected run made **16** model calls, not 15. It admitted zero candidates and ran zero hidden grades. This correction does not change the run disposition and does not admit a benchmark or capability verdict.

The sealed `run/run_v221_corrected_20260716T003429Z/collection_receipt.json` records `"calls": 16`. A filesystem audit finds 16 preserved `dispatch.json` receipts:

- 6 full-agent calls: 3 Sol and 3 Luna.
- 3 initial-planner calls: Luna.
- 3 HAND 1 calls: Spark.
- 2 continuation-planner calls: Luna, both in replicate 2.
- 2 HAND 2 calls: Spark, both in replicate 2.

The collection receipt binds the unchanged manifest, schedule, comparison, and report with these SHA-256 values:

- manifest: `42a3726c9640f40a1f58576a365946c358ff6dfa3c629ed39213d5b862cf7029`
- schedule: `1e0fce13365d9d55ccc10cfcb0d9e6ef47c0612a667d8a24de50d75e9035dd18`
- comparison: `e4c1fe1689bf8e155bb81282fd1fc3c1f237d271dd8cbb5d4a67144a5c5066b9`
- report: `89ada22f523d74186c36f7c2f7f44788d72a14ed9e665cf3607d1b745d0b39c9`

All v2.2.1 raw outputs and receipts remain immutable. The earlier prose is retained as historical evidence; this note is the authoritative additive correction for its call count.
