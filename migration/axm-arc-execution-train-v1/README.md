# AXM Arc execution train migration staging

This directory stages the move of the domain-neutral execution train that was built in `BigBirdReturns/axm-arc` under ASOIAF-specific names. It is a custody and refactoring contract, not an imported runtime.

The source export is sealed by axm-arc Actions run `31516794814`, artifact `9111377925`, outer ZIP digest `sha256:7ba0655985cd8d15eae45d275c23638a937eb00698b77aa4a6651e00d22ed592`. Independent inspection passed the outer digest, every internal `SHA256SUMS` entry, and the three-ref Git bundle.

The three source objects are the terminal Linux product donor from PR #294, the terminal V2-published orthogonal credential-service donor from PR #282, and the diagnostic-only Windows mechanism from PR #298. PR #298 remains outside product ancestry until a clean Windows product independently reproduces it.

The move must separate the generic work, transport, credential, runtime, process, and capability protocols from the ASOIAF dossier, reconciliation, reviewed-answer, lore, and canon adapters. The latter belong in `axm-canon/asoiaf`. A blind textual rename would preserve the wrong dependency direction and is therefore forbidden.

Current stage: `SOURCE_CUSTODY_SEALED_DESTINATION_STAGED`. No source code has been imported, no public API has been renamed, and no old-home cleanup is authorized.
