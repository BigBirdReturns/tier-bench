# CART0-PROFILE-1 delta-only independent retest

Do not read
`docs/cart0-profile-1-independent-review-remediation-20260714.md`, any Codex
conversation, or any implementation conclusion before completing and sealing
the steps below. This is a delta retest of your sealed report with SHA-256
`9a75696089c7e7ef0e8fa11a75fb09e0ed905556cfe5c2223f63764654b844bb`.

1. Hash
   `experiments/cart0_anchor_prototype/cart0-profile-1-independent-verification-v2-a30ca1a.zip`.
   Expected SHA-256:
   `fb912f39d08681ff60108e0cf5ca7199f339de25bc36bfe1d1c5300602f66bdc`.
2. Extract it into a new directory outside the source repository. Do not use
   network access or borrow any `.git` state from the source worktree.
3. From the extracted directory, run this single command with a path that does
   not already exist:

   ```powershell
   .\verify.ps1 -Scratch (Join-Path $env:TEMP ('cart0-claude-retest-' + [guid]::NewGuid().ToString('N'))) -Python py
   ```

4. Require exit 0 and terminal marker
   `PORTABLE_CART0_PROFILE_1_VERIFIED`. Confirm the run itself reports:
   `py_compile` PASS; bridge tests PASS; preserved historical receipt PASS;
   fresh conformance 15/15 with reject-all guard PASS; remediated B0 PASS; and
   preserved historical B0 PASS.
5. Independently inspect/re-execute these additive vectors before reading the
   remediation report:
   - `rehydrate_head_drift`: inject a real commit between verify and emission;
     emitted normal source must remain the verified blob and injected bytes must
     be absent, or the operation must refuse;
   - `unsafe_control_paths`: NUL, representative C0, DEL, and nested `.git`
     components must raise only `AnchorError` / `CART0_ANCHOR_REFUSED`, never raw
     `ValueError`;
   - `quarantine_delimiter_hardening`: source containing legacy delimiter text
     must still produce exactly one nonce-bound generated begin/end pair;
   - isolated archive verification must use only the embedded Git bundle and
     tested tree.
6. Seal a delta report and SHA-256 before opening
   `docs/cart0-profile-1-independent-review-remediation-20260714.md`. Then compare
   and record any discrepancies in a separate post-seal note. Do not modify your
   original sealed report or witnesses.

No model/provider dispatch, hidden grader, B1, semantic-truth claim,
instruction-safety proof, production Genesis claim, provider-billing claim, or
context-window claim is authorized by this retest.
