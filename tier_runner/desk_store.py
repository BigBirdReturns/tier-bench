from __future__ import annotations

from .desk_store_base import DeskStoreBase
from .desk_store_queue import DeskStoreQueueMixin


class DeskStore(DeskStoreQueueMixin, DeskStoreBase):
    pass
