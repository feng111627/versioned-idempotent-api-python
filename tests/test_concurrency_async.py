"""场景组：真实并发下的幂等与乐观并发（直接并发调用异步核心）。

TestClient 的请求在单一 portal 线程内串行，无法制造真实并行；
这里用 asyncio 并发任务直接驱动 ``handle_with_idempotency``，
覆盖真实竞态窗口。
"""

import asyncio
import json

import pytest
from pydantic import TypeAdapter

from app.idempotency import handle_with_idempotency
from app.schemas import DocumentIn
from app.services import create_document, update_document
from app.store import store

pytestmark = pytest.mark.scenario(
    "真实并发安全",
    "并行任务下重复提交只生效一次、竞争更新恰好一方成功",
)


class _Headers(dict):
    """大小写不敏感的请求头容器（模拟真实 HTTP 头）。"""

    def get(self, key, default=None):  # type: ignore[override]
        return super().get(key.lower(), default)


class _FakeRequest:
    def __init__(self, method: str, path: str, headers: dict[str, str]):
        self.scope = {"method": method, "path": path}
        self.headers = _Headers({k.lower(): v for k, v in headers.items()})


_adapter = TypeAdapter(DocumentIn)
_PAYLOAD = json.dumps({"title": "c", "content": "x"})


@pytest.mark.asyncio
async def test_async_concurrent_creates_exactly_once():
    """8 个并发任务使用同一幂等键创建：恰好一次生效，其余回放同一结果。"""
    payloads = [_adapter.validate_json(_PAYLOAD) for _ in range(8)]

    async def one(_payload):
        req = _FakeRequest("POST", "/api/v2/documents",
                           {"Idempotency-Key": "async-key-1"})

        def handler():
            code, resource = create_document(None, _payload)
            return code, {"id": resource.id, "version": resource.version}

        return await handle_with_idempotency(req, _payload, handler)

    responses = await asyncio.gather(*(one(p) for p in payloads))
    assert len(responses) == 8
    # 仅一个首次执行
    firsts = [r for r in responses if r.headers.get("Idempotency-Replayed") == "false"]
    replays = [r for r in responses if r.headers.get("Idempotency-Replayed") == "true"]
    assert len(firsts) == 1
    assert len(replays) == 7
    # 全部回放同一个资源 id
    ids = {json.loads(r.body)["id"] for r in responses}
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_async_concurrent_conflicting_updates_one_wins():
    """并发的竞争更新（不同键、同基准版本）：一个成功、一个 409 版本冲突。"""
    code, resource = create_document(
        None, _adapter.validate_json(_PAYLOAD)
    )
    doc_id = resource.id
    store._idempotency.clear()  # 创建所用的键不影响更新用的两个键

    async def attempt(key: str, content: str):
        body = _adapter.validate_json(
            json.dumps({"title": "c", "content": content})
        )
        req = _FakeRequest(
            "PUT", f"/api/v2/documents/{doc_id}",
            {"Idempotency-Key": key, "If-Match": "1"},
        )

        def handler():
            c, res = update_document(doc_id, body, "1")
            return c, {"version": res.version, "content": res.content}

        return await handle_with_idempotency(req, body, handler)

    results = await asyncio.gather(
        attempt("race-a", "from-A"),
        attempt("race-b", "from-B"),
        return_exceptions=True,
    )
    from app.errors import InvalidVersionError

    errors = [r for r in results if isinstance(r, InvalidVersionError)]
    oks = [r for r in results if not isinstance(r, Exception)]
    assert len(errors) == 1
    assert len(oks) == 1
    assert json.loads(oks[0].body)["version"] == 2

    got = store.get_resource(doc_id)
    assert got.version == 2
