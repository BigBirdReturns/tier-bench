# Partial closure: Luna/Sol Anchor Replication v2

Status: `PARTIAL_UNADJUDICATED_PROVIDER_SCHEMA_REJECTION`

The v2 oracle, subject-bundle leak scan, isolated-repository checks, model
catalog check, prompt freeze, and schedule freeze passed before dispatch.
Suite commit: `ca64a5d3862c7de8b8ce99f9d6e81cbe01edd2c1`.

The first provider-bound requests reached `thread.started` and `turn.started`
but were rejected before any agent message, tool call, file change, or final
response. The sealed error is in each call's `events.jsonl` and states:
`invalid_json_schema`: in `properties.visible_validators.items`, `required`
must include `detail`. Because the first provider request occurred, the
frozen schema cannot be repaired in this run under the protocol.

This run contains 9 provider-bound attempts, 0 agent outputs, 0 candidates, 0
hidden grades, and 0 admitted capability comparisons. `NOT_RUN_NO_CANDIDATE`
is the failure default for every arm; it is not a model FAIL and does not
support a Sol, Luna, or anchor verdict.

The earlier administrative run directories are preserved separately: one
stopped on the controller arm-argument defect and one stopped on the pinned
CLI rejecting `agents.max_depth=0`. They are not benchmark outcomes.
