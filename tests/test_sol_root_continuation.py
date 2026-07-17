"""Model-free regression tests for the bounded Sol-root continuation packet."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "sol_root_matched_config"
sys.path.insert(0, str(EXPERIMENT))

from verify_continuation import (  # noqa: E402
    MAX_SUBJECT_TOTAL_BYTES,
    PACKET,
    inspect_packet,
    verify_committed,
)


def main() -> int:
    checks = 0
    receipt = verify_committed()
    assert receipt["all_pass"] is True, receipt
    assert receipt["provider_calls"] == 0
    assert receipt["scientific_observations"] == 0
    assert receipt["authority_created"] is False
    assert receipt["observed"]["subject_total_bytes"] <= MAX_SUBJECT_TOTAL_BYTES
    checks += 1

    parent = Path(tempfile.mkdtemp(prefix="sol-root-continuation-test-"))
    try:
        copied = parent / ".cart0"
        shutil.copytree(PACKET, copied)
        relocated = verify_committed(copied)
        assert relocated["all_pass"] is True, relocated
        checks += 1

        index = copied / "000.000.INDEX.md"
        index.write_text(index.read_text(encoding="utf-8").replace("300.100.NEXT_TRANSITION.md", "300.100.MISSING.md"), encoding="utf-8")
        broken = inspect_packet(copied)
        assert broken["all_pass"] is False
        assert any(item["name"] == "index_links_complete" and not item["pass"] for item in broken["checks"])
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    checks += 1

    print(f"OK - {checks} Sol-root continuation checks; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
