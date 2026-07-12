# ARC-D buffalo pilot v2

This directory is a separately versioned retry of `arc_d_buffalo_pilot_v1`.
It extends and does not supersede the immutable v1 partial at commit
`8517e3f56dd1228bf0efd007fcd8f48ec4c619a2`.

The capacity preflight is administration evidence only and is excluded from the
scientific denominator. Subject prompts are copied byte-for-byte from the v1 Git
blobs. Subjects run sequentially in fresh projectless threads with no tools or
repository checkout. A provider failure with no assistant bytes stops further
dispatch. Completed responses remain ungraded and unadjudicated because the
HARVEST gate is still proposal-only.
