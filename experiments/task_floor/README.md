# Task Floor reference kit

This directory contains the public reference manifest, conservative OSS registry, generated gap report, and candidate frontier requirements.

```text
reference_manifest.json  declared capability and TF0-TF5 claim
oss_registry.json        primary-source coverage matrix for 21 representative systems
gap_report.json          generated 26-axis gap analysis
frontier_gaps.json       candidate requirements for a future profile revision
```

Regenerate and validate through:

```powershell
.\TASKFLOOR.cmd -Command quick
```

The registry is evidence, not marketing. Add systems only with primary sources and record `partial` when a project supplies a primitive without enforcing the full Task Floor axis.
