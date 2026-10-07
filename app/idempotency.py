"""幂等键登记表。

并发协议（与 :class:`~app.store.ItemStore` 共享同一把可重入锁）：

* ``acquire(key, fingerprint)``：
    - 键不存在：登记一个“进行中”占位并返回 ``None``，
      调用方负责真正执行写入并调用 ``store_result``；
    - 键已完成且指纹一致：直接返回已完成的记录（重放）；
    - 键已完成但指纹不同：抛 :class:`IdempotencyConflict`；
    - 键进行中且指纹不同：同样立即拒绝（不等待）；
    - 键进行中且指纹一致：在事件上等待首个请求完成，随后重放其结果。

由于占位登记发生在全局锁内，并发重复请求里至多一个线程执行实际写入，
因此不会出现重复生效或部分生效。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.errors import IdempotencyConflict


@dataclass
class IdempotentRecord:
    key: str
    fingerprint: str
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str]


@dataclass
class _Pending:
    fingerprint: str
    event: threading.Event = field(default_factory=threading.Event)
    record: IdempotentRecord | None = None


class IdempotencyManager:
    def __init__(self, lock: threading.RLock | None = None) -> None:
        self._entries: dict[str, _Pending | IdempotentRecord] = {}
        self._lock = lock or threading.RLock()

    def acquire(self, key: str, fingerprint: str) -> IdempotentRecord | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = _Pending(fingerprint=fingerprint)
                return None
            if entry.fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "Idempotency-Key 已被用于不同内容的请求",
                    details={"idempotency_key": key},
                )
            if isinstance(entry, IdempotentRecord):
                return entry
            pending = entry
        # 与进行中的首个请求内容一致：等待其结束后重放。
        pending.event.wait()
        with self._lock:
            record = self._entries[key]
            assert isinstance(record, IdempotentRecord)
            return record

    def store_result(self, key: str, record: IdempotentRecord) -> None:
        with self._lock:
            entry = self._entries.get(key)
            assert isinstance(entry, _Pending), f"幂等键 {key} 未处于进行中状态"
            self._entries[key] = record
            entry.event.set()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
