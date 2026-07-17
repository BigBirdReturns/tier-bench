# Local Qwen residue: SQL null-filter knot

## Result

`qwen3.5:9b-q4_K_M` hit a sealed 0/3 wall on `t3_null_filter_001`.
The residue broker therefore abstained at the only measured rung. This is a
local-Qwen observation, not Spark evidence.

## Frozen condition

- Transport: local Ollama loopback (`127.0.0.1:11434`)
- Packet: prompt plus `input.py`; no hidden grader, peer conclusion, or tool access
- Sampling: temperature 0.2; fresh seeds 101, 202, and 303
- Calls: exactly three; no retries
- Packet SHA-256: `3bc8c2a66165d88195fd972ed00c07d9170d12a48d40a39655b29be977626021`
- Prompt SHA-256: `bd13aca4ee9899f26df03206d6a78eb5e1dc061018ee6d90fb2b07a40c7a1bcd`
- Hidden grader SHA-256: `183d1539ad94e928ee917aa3958ee8359591312246aa44ccbc58e45c32059dd5`

## Receipts

| Trial | Seed | Input tokens | Output tokens | Final chars | Thinking chars | Wall time | Hidden grade |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 101 | 972 | 7,220 | 0 | not captured | 233.98 s | fail twice |
| 2 | 202 | 972 | 7,220 | 0 | 27,748 | 219.07 s | fail twice |
| 3 | 303 | 972 | 7,220 | 0 | 29,277 | 217.02 s | fail twice |

All three final candidates are the empty byte string, SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
The visible command exits zero for an empty Python file, while the deciding
hidden grader exits one on both coordinator reruns. This is exactly why the
hidden receipt, not the visible validator, controls the capability claim.

Trial 1 completed before reasoning-length fields were added to the local
transport receipt, so its thinking character count is intentionally recorded
as unavailable. Its native token counters, empty final response, hashes, and
double hidden-grade result are preserved.

## Durable residue

Under this condition, the model spends the full 7,220-token generation budget
without emitting a final answer. The next deterministic task is therefore not
"fix SQL three-valued logic." It is to test the transport/model boundary with
an explicit reasoning budget or thinking-disabled condition as a new rung,
while preserving this 0/3 layer unchanged.
