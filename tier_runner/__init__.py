"""Fail-closed daily runner for the registered driver-boundary protocol."""

# This import surface is custody-bound by pilot_activation.SOURCE_PATHS.

from .core import RunError, run_task, verify_run
from .pilot_composition import (
    CompositionError,
    answer_operator_question,
    new_pilot_arm_state,
    record_acceptance,
    record_pilot_call,
    render_next_prompt,
)
from .pilot_manifest import PilotComposition, load_pilot_composition
from .pilot_bridge import (
    BridgeError,
    answer_and_resume_pilot_arm,
    decline_pilot_arm,
    recover_pilot_arm,
    start_pilot_arm,
)

__all__ = [
    "CompositionError",
    "PilotComposition",
    "BridgeError",
    "RunError",
    "answer_operator_question",
    "answer_and_resume_pilot_arm",
    "decline_pilot_arm",
    "load_pilot_composition",
    "new_pilot_arm_state",
    "record_acceptance",
    "record_pilot_call",
    "recover_pilot_arm",
    "render_next_prompt",
    "run_task",
    "start_pilot_arm",
    "verify_run",
]
