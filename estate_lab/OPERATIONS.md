# Surface Interop operations

## Installation

The release ZIP is self-contained and offline-verifiable. Verify its detached SHA-256, run `python -m estate_lab verify-release` or `surface-interop verify-release`, and extract it into a new directory. It can run without installation through the path-pinned `python surface-interop.py` bootstrap; `python -m estate_lab` is reserved for an installed distribution. An optional local installation uses `python -m pip install --no-build-isolation --no-deps .`. Python 3.10 or newer is required. The runtime has no third-party dependencies.

After installation, run:

```text
surface-interop doctor
surface-interop validate-spec
surface-interop validate-adapter
```

A failed doctor check is an operational block. Do not route production adapter traffic through an installation whose specification, schemas, version, atomic-publication test, or reference supply pin is failing.

## Adapter onboarding

Generate a starter with `surface-interop init`. Replace only the bounded translation logic. Preserve the command-json envelope, semantic digest, authority fields, idempotency rule, refusal behavior, lifecycle operations, and supply declaration. Run `surface-interop conform --allow-exec --output <fresh-directory>` and retain the atomically published, content-addressed submission directory outside the source checkout. Adapter execution is refused unless `--allow-exec` is present. Verify the complete bundle with `surface-interop verify-submission <bundle-directory>`.

The adapter process receives no stdin, a secret-minimizing environment, bounded output, a process-level timeout, and a temporary request and response directory. A local executable or script must match a descriptor supply digest. A request or response larger than the configured production limit is refused before acceptance.

## Runtime monitoring

Monitor exit code, refusal reason, adapter duration, output byte counts, response and submission identities, and the health state returned by the adapter. Alert on repeated timeout, output overflow, supply-pin mismatch, semantic mutation, authority refusal, nonzero exit, malformed JSON, or release-verification failure. Raw request bodies are not required for routine monitoring and should not be placed in central logs by default.

## Recovery

Conformance runs are stateless except for the adapter process itself. Publish reports only through the atomic writer. After interruption, discard an incomplete hidden staging directory and rerun from the same descriptor, floor, and vectors into a fresh output root. The publisher refuses to overwrite an existing submission directory. Identical inputs must reproduce the same submission identity. A different identity indicates changed bytes or nondeterministic behavior and must be investigated rather than relabeled.

For a failed adapter upgrade, restore the last accepted descriptor and artifact bytes, rerun conformance, and compare the old and new submissions. For a compromised supplier, revoke the registry entry, preserve the original submission, execute the recorded rip-out procedure, and qualify the replacement through the same vectors.

## Release procedure

Run the full unit suite and reference conformance on all supported operating-system lanes. Build the deterministic ZIP twice and require identical SHA-256 digests. Verify the archive without extraction, then verify it again from a clean extracted directory. Install the produced wheel or source tree in a clean environment and run doctor plus reference conformance. Publish the ZIP, detached digest, validation receipt, release manifest, SPDX SBOM, build-provenance attestation, and SBOM attestation together. The permanent tag workflow uses GitHub artifact attestations, while the archive remains independently verifiable without GitHub.

## Support diagnostics

Create a redacted support receipt with `surface-interop support-bundle`. The receipt includes doctor results and hashes of named reports. It omits environment values, request and response content, credentials, and absolute source paths. Operators should attach this receipt before sending raw logs.

## Service objectives

The reference runner has no hosted availability objective because it is local-first. The operational objectives are deterministic completion, bounded failure, reproducible release bytes, and offline verification. Adapter-specific latency and availability objectives belong to the deploying product and must be stated outside the floor.
