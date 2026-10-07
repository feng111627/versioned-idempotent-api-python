"""幂等键登记表（骨架）。"""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class IdempotentRecord:
    key: str
    fingerprint: str
    status_code: int
    body: dict
    headers: dict[str, str]


class IdempotencyManager:
    def __init__(self, lock: threading.RLock | None = None) -> None:
        ...

    def acquire(self, key: str, fingerprint: str):
        ...

    def store(self, key: str, record: IdempotentRecord) -> None:
        ...
