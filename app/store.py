"""带版本号的内存资源存储（骨架）。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class StoredItem:
    id: str
    name: str = ""
    data: dict = field(default_factory=dict)
    version: int = 0


class ItemStore:
    def __init__(self) -> None:
        self._items: dict[str, StoredItem] = {}
        self.lock = threading.RLock()

    def get(self, item_id: str) -> StoredItem | None:
        ...

    def save(self, item: StoredItem) -> None:
        ...
