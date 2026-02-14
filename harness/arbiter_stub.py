from __future__ import annotations

def should_invoke_arbiter(det_checks_passed: bool, gaps_exist: bool) -> bool:
    return bool(det_checks_passed and gaps_exist)

def arbiter_verdict_stub() -> dict:
    return {
        "verdict": "ESCALATE",
        "score": 0.0,
        "evidence": [],
        "blockers": ["Arbiter not implemented in Phase 1"],
    }
