"""带版本号的内存资源存储。

存储本身不做并发策略决策，只持有数据与一把可重入锁；
乐观并发判断与版本推进在 service 层、持锁完成。
"""
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
        # RLock：同一工作线程内幂等管理与存储操作可嵌套加锁。
        self.lock = threading.RLock()

    def get(self, item_id: str) -> StoredItem | None:
        with self.lock:
            return self._items.get(item_id)

    def save(self, item: StoredItem) -> None:
        with self.lock:
            self._items[item.id] = item

    def clear(self) -> None:
        with self.lock:
            self._items.clear()
