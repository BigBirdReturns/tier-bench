"""Frontier Residue Refinery mixin for Monster Wrangler.

The refinery sequences verified ``tier run`` tasks over an operator-declared
route ladder. It calls no provider directly and leaves grading, patch application,
and capture-ledger closure to their existing authorities.
"""
from __future__ import annotations

from .residue_controller import ResidueControllerMixin
from .residue_query import ResidueQueryMixin
from .residue_resources import ResidueResourceMixin
from .residue_schema import ResidueSchemaMixin


class ResidueStoreMixin(
    ResidueResourceMixin, ResidueControllerMixin, ResidueQueryMixin, ResidueSchemaMixin
):
    pass
