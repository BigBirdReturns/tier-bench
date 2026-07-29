# Estate Lab adapter contract

A command adapter is a bounded process invoked by a human-owned estate manifest. It receives an exact request file and returns an exact response. The laboratory owns invocation, timeout, semantic non-mutation verification, and receipt capture. The adapter owns only the translation between its project surface and the shared semantic event.

## Request

```json
{
  "format": "axm-adapter-request/1",
  "adapter_id": "screen.procedure",
  "phase": "source",
  "event": {
    "format": "axm-semantic-event/1",
    "event_id": "event1_...",
    "run_id": "labrun1_...",
    "sequence": 1,
    "semantic_id": "engineering.coolant_bypass.set",
    "subject": "ship.engineering.coolant_bypass",
    "operation": "set",
    "state_path": "/engineering/coolant_bypass",
    "value": true,
    "authority": {
      "actor": "jonathan",
      "role": "engineering",
      "mandate": "ship.engineering.control",
      "ownership_epoch": 7
    },
    "route_id": "route.world.screen",
    "state_before_hash": "..."
  },
  "semantic_digest": "..."
}
```

The source phase may observe or execute the source surface. The target phase may verify that the target surface accepts the event. Neither phase may change `semantic_id`, `subject`, `operation`, `state_path`, `value`, or `authority`. The laboratory recomputes the semantic digest after the response.

## Response

```json
{
  "format": "axm-adapter-response/1",
  "adapter_id": "screen.procedure",
  "phase": "source",
  "accepted": true,
  "reason": null,
  "semantic_digest": "...",
  "observations": {
    "procedure_id": "engineering-coolant-bypass-v1",
    "before_capture": "sha256:...",
    "after_capture": "sha256:...",
    "verification": "visible-state-confirmed"
  }
}
```

The response may carry adapter-specific observations. Those observations are evidence beside the event. They cannot modify the event, raise the event's evidence class, authenticate their own actor, or grant authority.

## Command declaration

```json
{
  "id": "screen.procedure.live",
  "organ_id": "screenghost",
  "kind": "bounded-interface-procedure",
  "mode": "command",
  "capabilities": ["screen.procedure", "semantic.input"],
  "local_only": true,
  "deterministic": true,
  "replayable": true,
  "evidence_class": "measured",
  "command": [
    "python",
    "{repo}/tools/estate_adapter.py",
    "--request",
    "{request}",
    "--response",
    "{response}"
  ],
  "timeout_seconds": 30
}
```

The runtime substitutes only the three declared placeholders. If `{request}` is absent, the request path is appended as the final argument. If `{response}` is absent, stdout must contain the response JSON. The runtime does not invoke a shell.

## Failure taxonomy

| Reason | Meaning |
|---|---|
| `adapter_repository_missing` | The live owning repository could not be resolved below the workspace. |
| `adapter_executable_missing` | The manifest command's executable was not present. |
| `adapter_timeout` | The bounded command did not return before its declared timeout. |
| `adapter_nonzero_exit` | The command returned an unaccepted process status. |
| `adapter_response_missing` | A declared response file was not produced. |
| `adapter_response_malformed` | The response was not valid JSON. |
| `adapter_identity_mismatch` | The response named a different adapter. |
| `adapter_phase_mismatch` | The response confused source and target phases. |
| `adapter_refused` | The adapter returned `accepted: false` without a more specific reason. |
| `adapter_semantic_mutation` | The response's semantic digest did not match the requested event. |
| `human_intervention_required` | A human adapter reached a noninteractive run and refused. |

A failed source or target adapter leaves the semantic state unchanged. The fault remains in the run receipt and may be tested as an expected failure.

## Public adapter boundary

The internal `axm-adapter-request/1` contract remains scoped to Estate Lab manifests and route execution. External projects should implement the public `axm-interaction-adapter/1` declaration and `axm-interaction-request/1` / `axm-interaction-response/1` envelopes documented in `FLOOR_SPECIFICATION.md`. The public floor removes organ and repository assumptions while retaining semantic non-mutation, actor and authority preservation, shell-free command execution, lifecycle, replay, privacy, and conformance evidence.

An internal project adapter may expose both contracts. The translation must be explicit and testable. Passing the public floor does not register the adapter as an AXM estate organ, and passing an internal route probe does not certify public interoperability.
