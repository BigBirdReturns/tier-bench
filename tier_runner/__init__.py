"""Fail-closed daily runner for the registered driver-boundary protocol."""

from .core import RunError, run_task, verify_run

__all__ = ["RunError", "run_task", "verify_run"]
