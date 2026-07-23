#!/usr/bin/env python3
"""Execute the seven referee-kernel negative witnesses (010.100.TASK.md).

Fixture mode only: every witness drives tier_runner.core.run_task/verify_run
against a disposable Git repo with a fake Python "backend" standing in for a
model. Zero model calls. Does not modify tier_runner/ or any production
adapter path.

Prints REFEREE-WITNESSES OK and exits 0 only if all seven witnesses terminate
with their card-specified reason code. A witness that cannot be constructed
is reported as WITNESS-BLOCKED with its reason, never silently skipped or
faked as a pass.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import traceback
from pathlib import Path

CRATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CRATE_DIR.parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(CRATE_DIR))

import reasons  # noqa: E402
from witnesses.w1_acceptance_command_mutated_post_freeze import witness as w1  # noqa: E402
from witnesses.w2_scope_escape import witness as w2  # noqa: E402
from witnesses.w3_base_commit_drift import witness as w3  # noqa: E402
from witnesses.w4_empty_patch_not_accepted import witness as w4  # noqa: E402
from witnesses.w5_acceptance_failed_rejected import witness as w5  # noqa: E402
from witnesses.w6_verifier_mutated_candidate import witness as w6  # noqa: E402
from witnesses.w7_corrupted_receipt_binding import witness as w7  # noqa: E402

WITNESSES = [w1, w2, w3, w4, w5, w6, w7]


def main() -> int:
    results = []
    passed = 0
    for module in WITNESSES:
        tmp_path = Path(tempfile.mkdtemp(prefix=f"referee-witness-{module.WITNESS_ID}-"))
        expected = reasons.WITNESS_INDEX[module.WITNESS_ID]
        try:
            messages = module.construct(tmp_path)
            got = reasons.classify(messages)
            if got == expected:
                results.append((module.WITNESS_ID, "PASS", expected.value, module.CARD_TEXT))
                passed += 1
            elif got is None:
                results.append((
                    module.WITNESS_ID, "WITNESS-BLOCKED",
                    f"no unique reason signature matched; raw={messages!r}", module.CARD_TEXT,
                ))
            else:
                results.append((
                    module.WITNESS_ID, "WITNESS-BLOCKED",
                    f"expected {expected.value}, classified {got.value}", module.CARD_TEXT,
                ))
        except AssertionError as exc:
            results.append((module.WITNESS_ID, "WITNESS-BLOCKED", f"assertion failed: {exc}", module.CARD_TEXT))
        except Exception as exc:  # noqa: BLE001 - a blocked witness must not crash the run
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            results.append((module.WITNESS_ID, "WITNESS-BLOCKED", f"unexpected error: {detail}", module.CARD_TEXT))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    for witness_id, status, detail, card_text in results:
        print(f"[{witness_id}/7] {status} - {card_text}")
        print(f"        {detail}")

    print(f"{passed}/7 witnesses green")
    if passed == 7:
        print("REFEREE-WITNESSES OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
