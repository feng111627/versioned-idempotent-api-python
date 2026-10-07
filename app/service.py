"""写入领域服务：乐观并发 + 幂等（骨架）。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from app.idempotency import IdempotencyManager
from app.store import ItemStore, StoredItem


@dataclass
class WriteResult:
    status_code: int
    item: StoredItem
    replayed: bool = False
    headers: dict[str, str] = field(default_factory=dict)


class ItemService:
    def __init__(
        self,
        store: ItemStore | None = None,
        idempotency: IdempotencyManager | None = None,
    ) -> None:
        self.store = store or ItemStore()
        self.idempotency = idempotency or IdempotencyManager(self.store.lock)

    def read(self, item_id: str) -> StoredItem:
        ...

    def write(
        self,
        item_id: str,
        *,
        name: str,
        data: dict,
        merge: bool,
        expected_version: int | None,
        idempotency_key: str | None,
        fingerprint: str,
    ) -> WriteResult:
        ...
