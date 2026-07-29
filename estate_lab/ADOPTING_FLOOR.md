# Adopt the Interaction Floor

An outside project does not need the AXM estate manifest. It needs a descriptor, one adapter process or component, and the public vectors.

## Fast path

```bash
python -m estate_lab floor init-adapter ./my-adapter \
  --adapter-id org.example.my-adapter \
  --name "Example Adapter"

python -m estate_lab floor test \
  --adapter ./my-adapter/adapter.json \
  --output ./my-adapter/conformance
```

The generated Python adapter uses only the standard library. Replace the accepted execute branch with a bounded translation into your product. Preserve the request ID, event ID, semantic digest, authority fields, deadline, privacy class, trace context, delegation, and explicit refusal behavior.

## What your adapter may do

It may translate device reports, API calls, GUI procedures, controller actions, messages, or physical I/O into the public floor envelope. It may reject unsupported operations. It may add observations, health, diagnostics, and supplier-specific evidence. It may maintain a software twin or snapshot when declared.

## What your adapter may not do

It may not define the domain action, grant authority, broaden a mandate, advance ownership, rewrite semantic fields, treat telemetry as truth, claim physical execution from software evidence, or present protocol conformance as deployment approval.

## Submission contents

Submit the adapter declaration, exact implementation bytes, passing conformance bundle, license, source location, known limitations, and contact or ownership information. Platinum submissions also include an independent verifier result and substitution receipt.

## Integration strategy

Start with command JSON. Add a transport binding only when a real deployment requires it. Keep the command binding as a diagnostic and resurrection route. This preserves a low-complexity path when brokers, SDKs, browsers, or vendor services are unavailable.

## Review question

Can another maintainer replace your product while preserving the same floor requests, authority results, responses, domain receipts, and verification path?
