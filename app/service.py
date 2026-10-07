"""写入领域服务：乐观并发控制 + 幂等。

关键不变量：

* 一次写流程的「检查版本 -> 修改 -> 版本推进」在与存储共享的同一把锁内完成，
  并发写天然串行化，不会丢失更新；
* 版本缺失（``version_required``）、版本过期（``version_conflict``）、
  资源不存在（``resource_not_found``）是三类可区分的错误；
* 携带幂等键时，成功与业务错误的终态都会被登记，后续重复请求重放同一结果，
  写入只生效一次。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.errors import (
    APIError,
    IdempotencyConflict,
    ResourceNotFound,
    ResourceVersionConflict,
    ResourceVersionMissing,
)
from app.idempotency import IdempotencyManager, IdempotentRecord
from app.store import ItemStore, StoredItem


@dataclass
class OperationResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool = False
    headers: dict[str, str] = field(default_factory=dict)


def _canonical(item: StoredItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "data": dict(item.data),
        "version": item.version,
    }


class ItemService:
    def __init__(
        self,
        store: ItemStore | None = None,
        idempotency: IdempotencyManager | None = None,
    ) -> None:
        self.store = store or ItemStore()
        self.idempotency = idempotency or IdempotencyManager(self.store.lock)

    # ---- 读取 -----------------------------------------------------------
    def read(self, item_id: str) -> StoredItem:
        with self.store.lock:
            current = self.store.get(item_id)
            if current is None:
                raise ResourceNotFound(
                    f"资源 {item_id} 不存在",
                    details={"resource_id": item_id, "current_version": None},
                )
            # 返回快照，避免在锁外被序列化时与并发写入互相影响。
            return StoredItem(
                id=current.id, name=current.name,
                data=dict(current.data), version=current.version,
            )

    # ---- 写入 -----------------------------------------------------------
    def write(
        self,
        item_id: str,
        *,
        name: str | None,
        data: dict[str, Any],
        merge: bool,
        expected_version: int | None,
        idempotency_key: str | None,
        fingerprint: str,
    ) -> OperationResult:
        replay: IdempotentRecord | None = None
        if idempotency_key is not None:
            replay = self.idempotency.acquire(idempotency_key, fingerprint)
            if replay is not None:
                return OperationResult(
                    status_code=replay.status_code,
                    body=replay.body,
                    replayed=True,
                    headers=dict(replay.headers),
                )

        try:
            result = self._apply(
                item_id,
                name=name,
                data=data,
                merge=merge,
                expected_version=expected_version,
            )
        except IdempotencyConflict:
            raise
        except APIError as exc:
            # 业务错误也是终态：登记后重放，保证重复请求得到一致结果。
            record = IdempotentRecord(
                key=idempotency_key or "",
                fingerprint=fingerprint,
                status_code=exc.status_code,
                body=exc.to_body(),
                headers={},
            )
            if idempotency_key is not None:
                self.idempotency.store_result(idempotency_key, record)
            raise

        if idempotency_key is not None:
            record = IdempotentRecord(
                key=idempotency_key,
                fingerprint=fingerprint,
                status_code=result.status_code,
                body=result.body,
                headers=dict(result.headers),
            )
            self.idempotency.store_result(idempotency_key, record)
        return result

    def _apply(
        self,
        item_id: str,
        *,
        name: str | None,
        data: dict[str, Any],
        merge: bool,
        expected_version: int | None,
    ) -> OperationResult:
        with self.store.lock:
            current = self.store.get(item_id)

            if current is None:
                # 携带了版本却定位不到资源：属于“资源不存在”，与“没给版本即创建”区分。
                if expected_version is not None:
                    raise ResourceNotFound(
                        f"资源 {item_id} 不存在，无法按版本 {expected_version} 更新",
                        details={
                            "resource_id": item_id,
                            "expected_version": expected_version,
                            "current_version": None,
                        },
                    )
                item = StoredItem(
                    id=item_id,
                    name=name or item_id,
                    data=dict(data),
                    version=1,
                )
                self.store.save(item)
                return OperationResult(status_code=201, body=_canonical(item))

            # 资源已存在：更新必须携带版本。
            if expected_version is None:
                raise ResourceVersionMissing(
                    "更新已存在资源必须携带 expected_version",
                    details={
                        "resource_id": item_id,
                        "current_version": current.version,
                    },
                )
            if expected_version != current.version:
                raise ResourceVersionConflict(
                    f"版本 {expected_version} 已过期，当前版本为 {current.version}",
                    details={
                        "resource_id": item_id,
                        "expected_version": expected_version,
                        "current_version": current.version,
                    },
                )

            if merge:
                merged = dict(current.data)
                merged.update(data)
                current.data = merged
            else:
                current.data = dict(data)
            if name is not None:
                current.name = name
            current.version += 1
            self.store.save(current)
            return OperationResult(status_code=200, body=_canonical(current))
