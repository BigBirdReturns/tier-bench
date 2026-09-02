# Surface Interop support

Support requests should begin with a redacted `surface-interop support-bundle` receipt, the exact release ID, the adapter descriptor ID, the submission ID when available, the command being run, the observed exit code, and the smallest public reproducer. State whether the failure occurs during descriptor validation, hardened execution, vector validation, registry projection, release construction, or offline verification.

Do not attach credentials, live request bodies, private response bodies, complete environment dumps, or proprietary domain state. The support bundle deliberately records hashes and machine facts without those values. A maintainer may request a synthetic reproducer that preserves the failure mechanism while removing user content.

Supported production releases are the current `1.x` minor and its immediate predecessor for security and compatibility defects. Historical releases remain offline-verifiable but may require an upgrade before receiving operational fixes. Protocol-major migrations are documented separately and never relabel old submissions.

A production incident is closed only when the mechanism is identified, affected actors are named, the fix is represented by a permanent test or refusal vector, the release and compatibility impact are recorded, and the operator has a deterministic recovery or rollback path.
