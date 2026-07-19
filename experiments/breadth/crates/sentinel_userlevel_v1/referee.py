"""FROZEN REFEREE — sentinel_userlevel_v1. Deterministic; the only pass criterion.
Run from repo root: python experiments/breadth/crates/sentinel_userlevel_v1/referee.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CRATE = Path(__file__).parent
STAGED = CRATE / "staged"
LIVE_USER_SETTINGS = Path(r"C:\Users\BAM-Desktop\.claude\settings.json")
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (" — " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


# 1. Staged artifacts exist
for rel in ("hooks/session_sentinel.py", "hooks/session_burn_hook.py",
            "settings.json", "APPLY.md"):
    check(f"exists_{rel}", (STAGED / rel).is_file())

# 2. Staged settings: valid JSON, original keys preserved, 5 hook events, user-level paths
try:
    staged = json.loads((STAGED / "settings.json").read_text(encoding="utf-8"))
    live = json.loads(LIVE_USER_SETTINGS.read_text(encoding="utf-8"))
    for k, v in live.items():
        if k != "hooks":
            check(f"preserves_{k}", staged.get(k) == v)
    hooks = staged.get("hooks", {})
    for ev in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"):
        cmds = json.dumps(hooks.get(ev, []))
        check(f"hook_{ev}", ".claude" in cmds and "hooks" in cmds
              and "CLAUDE_PROJECT_DIR" not in cmds)
except Exception as e:  # noqa: BLE001
    check("staged_settings_valid", False, str(e))

# 3. Staged sentinel runs standalone: no CLAUDE_PROJECT_DIR, HOME/USERPROFILE sandboxed
# REFEREE CORRECTION (v2, 2026-07-18): v1 sent transcript_path="" — the sentinel
# no-ops on a missing transcript BY DESIGN (guard at its payload parse), so v1's
# state_under_home check could never fire. Hand adjudicated NOT at fault; probe
# now supplies a real (empty) transcript file.
with tempfile.TemporaryDirectory() as td:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env["USERPROFILE"] = td
    env["HOME"] = td
    fake_transcript = Path(td) / "transcript.jsonl"
    fake_transcript.write_text("", encoding="utf-8")
    payload = json.dumps({"session_id": "referee-test", "cwd": str(Path.cwd()),
                          "hook_event_name": "PreToolUse",
                          "transcript_path": str(fake_transcript)})
    r = subprocess.run([sys.executable, str(STAGED / "hooks" / "session_sentinel.py")],
                       input=payload, capture_output=True, text=True, timeout=30, env=env)
    check("staged_sentinel_exit", r.returncode in (0, 2),  # 2 = legitimate hard-cap deny
          f"rc={r.returncode} err={r.stderr[-200:]}")
    wrote_home = any(Path(td).rglob("*"))
    wrote_repo = "experiments" in (r.stderr + r.stdout) and ".sentinel_state" in (r.stderr + r.stdout)
    check("state_under_home", wrote_home, "sandboxed HOME got no state files")

# 4. Live surfaces untouched
live_txt = LIVE_USER_SETTINGS.read_text(encoding="utf-8")
check("live_user_settings_untouched", "session_sentinel" not in live_txt)
g = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
# Sibling crates run concurrently in this worktree; their targets are not contamination.
ALLOWED = {"experiments/breadth/run/burn_log.jsonl", "scripts/burn_report.py",
           "tests/test_tier_pilot_admin.py"}
touched = [l for l in g.stdout.splitlines()
           if l.strip() and not l.startswith("experiments/breadth/crates/")
           and l not in ALLOWED]
check("repo_untouched_outside_crate", not touched, ",".join(touched))

print("REFEREE:", "PASS" if not FAILS else "FAIL " + ",".join(FAILS))
sys.exit(0 if not FAILS else 1)
