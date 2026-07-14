"""Fail-closed daily runner for the registered driver-boundary protocol."""

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

__all__ = [
    "CompositionError",
    "PilotComposition",
    "RunError",
    "answer_operator_question",
    "load_pilot_composition",
    "new_pilot_arm_state",
    "record_acceptance",
    "record_pilot_call",
    "render_next_prompt",
    "run_task",
    "verify_run",
]
