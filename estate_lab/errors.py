"""Typed Estate Lab failures.

Failures are data-bearing outcomes. The runtime converts these exceptions into
explicit refusal or fault receipts rather than silently selecting another path.
"""

from __future__ import annotations


class EstateLabError(RuntimeError):
    """Base class for expected laboratory failures."""


class ManifestError(EstateLabError):
    """The estate manifest is malformed or internally contradictory."""


class ScenarioError(EstateLabError):
    """A scenario is malformed or references unknown estate objects."""


class RouteRefused(EstateLabError):
    """No admissible route satisfies the declared constraints."""

    def __init__(self, reason: str, details: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


class AuthorityRefused(EstateLabError):
    """The source does not hold the required role, mandate, or ownership epoch."""

    def __init__(self, reason: str, details: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


class ProjectionMismatch(EstateLabError):
    """A projection did not reproduce the expected desired-output digest."""


class CommodityCatalogError(EstateLabError):
    """The reviewed OSS/community commodity catalog is malformed or unsafe."""


class FloorProtocolError(EstateLabError):
    """The public Interaction Floor protocol or conformance product is invalid."""


class FloorGapError(EstateLabError):
    """The Interaction Floor gap ledger is malformed or internally contradictory."""
