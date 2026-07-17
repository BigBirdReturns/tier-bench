# Luna/Sol Anchor Replication v2.2 Administrative Partial

Protocol revision: `2.2`
Repair commit: `6b30ce9`
Benchmark disclosure: none
Benchmark calls: `0`
Candidates admitted: `0`
Hidden grades: `0`

The zero-inference controller-contract gate passed all 12 checks. The preferred controller interpreter was Python 3.12.13 at `C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, SHA-256 `3c6a206b7d93cca823934a83732220dcffd413fd1036d9fb82eebb64599cf7f3`.

Exactly two unscored live administrative canaries were dispatched through the pinned CLI. Canary 1 passed: the controller detected the actual `value.txt` diff, ran the controller-owned text validator, and admitted the candidate. Canary 2 stopped the task: the pinned CLI exited `1` before a final JSON response, yielding `instance_errors: ["no final JSON"]`. No planner object was parsed, hashed, or admitted.

This is an administrative partial, not a model capability result. The v2.2 stopping rule forbids benchmark disclosure after either canary fails. No benchmark call, hidden grading, comparison, or capability verdict was performed.

Administrative receipt: `admin_canaries_v22.json` (SHA-256 `0731b4f0110cad6034a552cc68e06e46137d4c300e2edc3bde8c5ac7ee251008`). Raw canary custody is under `canaries/`; the per-call prompts, schemas, JSONL, stderr, final response where present, usage, controller receipts, diffs, and hashes are preserved there.

Canary 1 controller receipt SHA-256: `a7e86d6696130f369e0b99965f7dd1b986fc1b41ad0decd3c5a3174ef949474a`.

Canary 2 controller receipt SHA-256: `85ee2fe0f8750bd9ef5eb5da22796e35ed7de107787a02396d52fa2e1c0b2253`.
