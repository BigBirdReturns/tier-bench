# Luna/Sol Anchor Replication v2.2.1 Administrative Partial

Protocol revision: `2.2.1`
Repair commits: `3f6379ad62a11d3d1523e553f5f1a0bc757500f3`, corrective frozen-binding restore `4c57303`
Benchmark disclosure: none
Benchmark calls: `0`
Candidates admitted: `0`
Hidden grades: `0`

All pre-disclosure repository gates passed. The post-repair administrative schema proof was dispatched once through the pinned authenticated CLI using the exact embedded production `planner_initial`, `planner_continuation`, and `spark` schema trees. The command vector contained `agents.max_depth=0` and `agents.max_threads=1`.

The pinned CLI rejected the request before any thread or turn event:

`Error: agents.max_depth must be at least 1`

This is a typed administrative CLI configuration blocker, not a provider schema result, model result, candidate result, benchmark result, or capability verdict. The directive requires `agents.max_depth=0`; changing the vector to `1` would violate the frozen 2.2.1 contract. The replacement initial-planner canary and the K=3 benchmark were therefore not run.

Raw proof custody: `run/admin_preflight_v221_20260715T223700Z/`.

Proof artifact SHA-256:

- `completion.json`: `2c10d77decc32a0393857191d4bde139c35c838ab52f36a1f3a8e30c3c472d58`
- `union.schema.json`: `a7e19e90d1500152cabdb6037214dadc7ad3f519270627dc695ca159af636101`
- `dispatch.json`: `4624fa48dedc43ddb25167eda4086a5d0eaf0558dbc46e049325e36c25ce614`
- `stderr.txt`: `25f17be186feb39402202b65c0e5c8fd9925962733418f8a797dfd93582287bd`
- `events.jsonl`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

The deterministic contract-gate receipt is `controller_contract_gate_v221.json` with SHA-256 `545a040f54262c0db56e98a43f60f605b50476d07e832716342198c03a538ce8`.
