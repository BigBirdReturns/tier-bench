# Blind Review Quality Experiment

Date: 2026-07-17

## Question

Can the first independently valid Spark clone blind-review sibling implementations and predict which one survives requirements absent from the visible validator?

The prospective fixture is `review_quality_fixture`. Executors and reviewer received `tasks/patcher.md` and `test_patcher.py`. They did not receive `audit_patcher.py`. All three candidates had to pass the visible validator before review. The audit was executed afterward against the preserved candidate directories.

## Replicate 1: useful critique, initially weak audit

The fastest valid candidate was clone 2 at 4.188 seconds. The blind reviewer selected the slowest candidate, clone 3 at 7.907 seconds, scoring the candidates 9, 7, and 5. It cited empty JSON Pointer segment handling as a weakness in the rejected candidates.

The initial four-group withheld audit passed all three candidates, so it did not establish the ranking. Two additional tests were then added from written requirements the review exposed but the audit omitted:

- empty reference tokens inside non-root JSON Pointer paths;
- isolation of mutable values inserted from the operations input.

This expanded diagnostic was post-hoc and is not counted as prospective evidence. It did corroborate the review:

| Candidate | Expanded audit |
| --- | --- |
| clone 1 | failed: one failure, one error |
| clone 2, fastest | failed: two failures |
| clone 3, reviewed winner | 6/6 passed |

## Replicate 2: frozen audit, incorrect selection

The six-test expanded audit was frozen before a fresh three-clone race. The first valid candidate was clone 3 at 16.360 seconds. Blind review selected clone 2 at 21.860 seconds.

| Candidate | Review rank | Prospective audit |
| --- | ---: | --- |
| clone 2, selected | 1 | failed: one failure, one error |
| clone 1 | 2 | failed: one failure |
| clone 3, fastest | 3 | failed: one failure |

All three shared an aliasing defect: mutable values inserted from an operation were not deep-copied. The selected candidate also rejected valid empty JSON Pointer segments. The reviewer nevertheless claimed the selected implementation had full deep-copy semantics and ranked it first. Therefore blind prose review did not predict withheld correctness on this replicate.

## Generated-audit probes

A separate bounded Spark lane generated executable `unittest` audits using only the task and visible test, never candidate source or the withheld audit.

1. The first generated audit contained nine tests and passed all three flawed replicate-2 candidates. It repeated the visible validator's blind spots.
2. A strengthened requirement-by-requirement prompt generated ten tests. It failed all three candidates, but at least one failure was invalid: the test deliberately mutated the returned result and then asserted that the returned result still equaled its pre-mutation value.

The second generated suite therefore cannot be used as acceptance evidence. Generating a test is not the same as validating the test.

## Result

The experiment establishes three boundaries:

- Clone diversity is useful: candidates differed materially despite sharing model, prompt, and source state.
- Blind peer review is useful for critique and sometimes selects a genuinely stronger slower candidate, but it is not a correctness oracle.
- Model-generated validators require an independent oracle or trusted repository review; otherwise they can miss shared defects or introduce false failures.

The production rule remains: repository-owned validators decide promotion. A first finisher may grade, challenge, or rank siblings, but its output is advisory unless converted into independently trusted executable evidence.

## Evidence hashes

- Replicate 1 summary: `0DDEF36C9011AC2EBAD50738C520A7E1734A1AD4FBE6017757B400FDA92AA57A`
- Replicate 2 summary: `7F45422842D1FFBF143370DC2F258DA4E70C85DFD260F0D77538D6EB04D808BE`
- Frozen withheld audit: `68FCD302E9C355722551E164F3A7AF793F9961C92EC7D199671F8B232EAD6C10`
- First generated audit: `4F36D62F24B604DA0C0CD662B9F3AC99669E04558E34507724C61E4BE7FE572E`
- Strengthened generated audit: `26A5814AD36178DFB30820586B5329C46CEE9F1117596C11D2FB07219BAB23AB`
