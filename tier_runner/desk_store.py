from __future__ import annotations

from .desk_store_base import DeskStoreBase
from .desk_store_queue import DeskStoreQueueMixin
from .residue import ResidueStoreMixin


class DeskStore(ResidueStoreMixin, DeskStoreQueueMixin, DeskStoreBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_residue()
