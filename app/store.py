"""内存存储：资源状态 + 幂等记录，内置并发控制。

并发模型：

* 一把全局 ``RLock`` 保护资源表与幂等表的所有读写，保证“检查 + 变更”
  这类复合操作的原子性，乐观并发控制因此不会出现 check-then-act 竞态；
* 每个幂等键另有一把专属锁（``lock_for_key``），让同一幂等键的并发
  请求严格串行：第一个请求执行并落盘结果，其余请求阻塞后回放同一结果，
  既不会重复生效，也不会部分生效。

存储是进程内内存实现（演示用途），v1/v2 路由共享同一个 ``store`` 单例，
因此两个 API 版本看到的资源状态与版本号始终一致。
"""

import threading
from dataclasses import dataclass, field, replace

from app.errors import InvalidVersionError, NotFoundError
from app.schemas import DocumentIn


@dataclass
class Resource:
    """一份资源的内部表示。"""

    id: str
    title: str
    content: str
    version: int = 0
    update_count: int = 0


@dataclass
class IdempotencyRecord:
    """一条幂等键对应的处理结果快照。"""

    request_hash: str
    status_code: int
    body: dict
    resource_id: str | None = None


@dataclass
class Store:
    """线程安全的内存存储。"""

    _resources: dict[str, Resource] = field(default_factory=dict)
    _idempotency: dict[str, IdempotencyRecord] = field(default_factory=dict)
    _key_locks: dict[str, threading.Lock] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def lock_for_key(self, key: str) -> threading.Lock:
        """取得某个幂等键专属的锁（不存在则创建）。"""
        with self._lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        """读取幂等记录。"""
        with self._lock:
            record = self._idempotency.get(key)
            return replace(record, body=dict(record.body)) if record else None

    def save_idempotency(self, key: str, record: IdempotencyRecord) -> None:
        """保存幂等记录。"""
        with self._lock:
            self._idempotency[key] = replace(record, body=dict(record.body))

    def get_resource(self, resource_id: str) -> Resource | None:
        """读取资源，返回副本（调用方不会意外改到内部状态）。"""
        with self._lock:
            resource = self._resources.get(resource_id)
            return replace(resource) if resource is not None else None

    def create_resource(self, resource_id: str, payload: DocumentIn) -> Resource:
        """创建资源。重复创建视为再次写入冲突，由调用方先做存在性检查。"""
        with self._lock:
            resource = Resource(
                id=resource_id,
                title=payload.title,
                content=payload.content,
                version=1,
                update_count=1,
            )
            self._resources[resource_id] = resource
            return replace(resource)

    def update_resource(
        self, resource_id: str, payload: DocumentIn, expected_version: int
    ) -> Resource:
        """按期望版本更新资源。

        资源不存在抛 ``NotFoundError``；期望版本与当前版本不一致抛
        ``InvalidVersionError``。检查与推进版本在同一把全局锁内完成。
        """
        with self._lock:
            resource = self._resources.get(resource_id)
            if resource is None:
                raise NotFoundError(resource_id)
            if resource.version != expected_version:
                raise InvalidVersionError(
                    expected=resource.version, provided=expected_version
                )
            resource.title = payload.title
            resource.content = payload.content
            resource.version += 1
            resource.update_count += 1
            return replace(resource)


# 全局单例，v1/v2 路由共享，保证跨版本状态一致。
store = Store()
