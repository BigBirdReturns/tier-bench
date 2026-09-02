#!/usr/bin/env python3
"""Standalone Interaction Floor command-json adapter.

This file intentionally uses only the Python standard library. It may translate
into a domain runtime, but it may not grant authority or change semantic fields.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ADAPTER_ID = 'org.axm.reference-echo'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value):
    payload = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(payload).hexdigest()


def stable(prefix, value, length=32):
    return f"{prefix}_{sha256(value)[:length]}"


def response_id(response):
    return stable("floorres1", {key: value for key, value in response.items() if key != "response_id"})


def request_id(request):
    return stable("floorreq1", {key: value for key, value in request.items() if key != "request_id"})


def semantic(event):
    return {
        "semantic_id": event.get("semantic_id"),
        "subject": event.get("subject"),
        "operation": event.get("operation"),
        "state_path": event.get("state_path"),
        "value": event.get("value"),
        "authority": event.get("authority"),
    }


def finish(request, accepted, reason=None, outcome=None, **extra):
    response = {
        "format": "axm-interaction-response/1",
        "request_id": request.get("request_id", "unresolved"),
        "adapter_id": ADAPTER_ID,
        "kind": str(request.get("kind") or "unknown"),
        "accepted": accepted,
        "reason": reason,
        "outcome": outcome or ("accepted" if accepted else "refused"),
        "semantic_digest": None,
        "observations": {},
    }
    response.update(extra)
    response["response_id"] = response_id(response)
    return response


def main(request_path, response_path, descriptor_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    descriptor = json.loads(Path(descriptor_path).read_text(encoding="utf-8"))
    if request.get("format") != "axm-interaction-request/1":
        result = finish(request, False, "request_format_unsupported")
    elif request.get("request_id") != request_id(request):
        result = finish(request, False, "request_identity_mismatch")
    elif request.get("target_adapter_id") != ADAPTER_ID:
        result = finish(request, False, "adapter_target_mismatch")
    elif str(request.get("floor_version", "")).split(".", 1)[0] != "1":
        result = finish(request, False, "floor_version_unsupported")
    elif request.get("context", {}).get("deadline_unix_ms", 1) <= 0:
        result = finish(request, False, "request_deadline_expired")
    elif request.get("kind") == "describe":
        result = finish(request, True, descriptor_id=descriptor["descriptor_id"], descriptor=descriptor)
    elif request.get("kind") == "health":
        result = finish(request, True, health={"state": "ready", "details": "reference adapter ready"})
    elif request.get("kind") == "snapshot":
        snapshot = {"format": "axm-interaction-snapshot/1", "adapter_id": ADAPTER_ID, "state": {}}
        snapshot["snapshot_id"] = stable("floorsnap1", snapshot)
        result = finish(request, True, snapshot=snapshot)
    elif request.get("kind") == "reset":
        result = finish(request, True, outcome="reset")
    elif request.get("kind") == "execute":
        event = request.get("event")
        if not isinstance(event, dict):
            result = finish(request, False, "semantic_event_missing")
        elif event.get("format") != "axm-semantic-event/1":
            result = finish(request, False, "semantic_event_format")
        elif not all(key in event.get("authority", {}) for key in ("actor", "role", "mandate", "ownership_epoch")):
            result = finish(request, False, "authority_incomplete")
        elif event.get("semantic_digest") != sha256(semantic(event)):
            result = finish(request, False, "semantic_digest_mismatch")
        else:
            observations = {
                "event_id": event.get("event_id"),
                "privacy_class": request.get("context", {}).get("privacy_class"),
            }
            traceparent = request.get("context", {}).get("traceparent")
            if traceparent is not None:
                observations["traceparent"] = traceparent
            delegation = request.get("context", {}).get("delegation")
            if isinstance(delegation, dict):
                observations["delegation_id"] = delegation.get("delegation_id")
            result = finish(
                request,
                True,
                outcome="accepted",
                semantic_digest=event["semantic_digest"],
                observations=observations,
            )
    else:
        result = finish(request, False, "request_kind_unsupported")
    Path(response_path).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: adapter.py REQUEST RESPONSE DESCRIPTOR")
    main(sys.argv[1], sys.argv[2], sys.argv[3])
