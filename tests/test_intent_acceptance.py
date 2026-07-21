from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.intent_acceptance import AcceptanceError, verify_insertion  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tier-intent-acceptance-") as raw:
        repo = Path(raw)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "tier@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Tier Test"], cwd=repo, check=True)
        path = repo / "guide.md"
        path.write_text("# Guide\n\nKeep this.\n", encoding="utf-8")
        subprocess.run(["git", "add", "guide.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
        path.write_text("# Guide\n\nNew sentence.\nKeep this.\n", encoding="utf-8")
        assert verify_insertion("guide.md", 1, repo) == 0
        path.write_text("# Guide\n\nRewritten.\n", encoding="utf-8")
        try:
            verify_insertion("guide.md", 1, repo)
        except AcceptanceError as exc:
            assert "changed or removed" in str(exc)
        else:
            raise AssertionError("replacement must fail insertion-only acceptance")
    print("PASS - intent acceptance rejects semantic overreach")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
