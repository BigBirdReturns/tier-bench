"""Synthetic visual candidates used only by deterministic Task Computer fixtures.

These candidates are deliberately separate from the ScreenGhost contract. They
prove the handoff, coordinate execution, changed-state verification, and evidence
ledger without claiming that a vision model found the target. Real ScreenGhost
qualification replaces this registry with model-produced candidates.
"""
from __future__ import annotations

from typing import Any

from .playwright_computer_common import PlaywrightComputerError
from .task_computer_fixtures import ProjectFixtureApp

_ORIGINAL_VISUAL_TARGET = ProjectFixtureApp.visual_target


def _fixture_visual_target(
    self: ProjectFixtureApp,
    visual_id: str,
    viewport: dict[str, int],
) -> dict[str, Any]:
    if self.scenario_id != "screen-ghost-visual-fallback":
        return _ORIGINAL_VISUAL_TARGET(self, visual_id, viewport)
    if visual_id != "sync-now":
        raise PlaywrightComputerError(f"fixture has no visual target {visual_id!r}")
    width = int(viewport.get("width", 1280))
    height = int(viewport.get("height", 900))
    # The visual target is inside the phone's nested screen, below the explanatory
    # heading and paragraph. These coordinates intentionally point near the center
    # of the rendered yellow control rather than at the phone container.
    return {
        "visual_id": visual_id,
        "x": round(width * 0.56),
        "y": round(height * 0.72),
        "coordinate_space": "viewport_pixels",
        "evidence_tier": "synthetic_fixture_oracle",
        "confidence": 1.0,
        "calibration": "screen-ghost-fixture-css-v1",
    }


def install_fixture_oracles() -> None:
    ProjectFixtureApp.visual_target = _fixture_visual_target
