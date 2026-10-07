"""幂等支持：请求指纹与服务端结果回放。

语义（针对 POST/PUT 等写请求）：

* 请求必须携带 ``Idempotency-Key`` 头；
* 同一键 + 相同内容：只生效一次，后续请求原样回放首次的状态码与响应体，
  连响应头 ``Idempotency-Replayed: true`` 都保持一致；
* 同一键 + 不同内容：返回 409 ``idempotency_conflict``，明确拒绝；
* 并发到达的相同请求：按幂等键加锁串行化，后来者等待并回放，
  不会重复生效或部分生效。

“相同内容”由 :func:`fingerprint` 对方法、路径与规范化 JSON 体取哈希判定。
"""

import copy
import hashlib
import json
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from app.errors import APIError, IdempotencyConflictError
from app.store import IdempotencyRecord, store

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotency-Replayed"


class IdempotencyKeyRequiredError(APIError):
    """写请求未携带幂等键。"""

    status_code = 400
    code = "idempotency_key_required"

    def __init__(self) -> None:
        super().__init__("写请求必须携带 Idempotency-Key 头")


def fingerprint(request: Request, payload: object) -> str:
    """计算请求内容指纹（方法、路径、规范化 JSON 体）。"""
    method = request.scope.get("method", "")
    path = request.scope.get("path", "")
    canonical = json.dumps(
        {"m": method, "p": path, "b": _jsonable(payload)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _jsonable(payload: object) -> object:
    """把 pydantic 模型等转成可 JSON 化的普通结构。"""
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        return dump()
    return payload


async def handle_with_idempotency(
    request: Request,
    payload: object,
    handler: Callable[[], tuple[int, dict]],
) -> JSONResponse:
    """携带幂等键执行写操作。

    ``handler`` 完成真正的业务处理并返回 ``(状态码, 响应体)``；
    只有首次调用会执行它，重复请求回放已保存的结果。
    业务异常（404/409/428 等）不会落盘为幂等结果——失败可安全重试，
    客户端修正请求后用同一键仍可成功。
    """
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if not key:
        raise IdempotencyKeyRequiredError()

    request_hash = fingerprint(request, payload)
    key_lock = store.lock_for_key(key)

    with key_lock:
        existing = store.get_idempotency(key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyConflictError(key)
            return JSONResponse(
                status_code=existing.status_code,
                content=copy.deepcopy(existing.body),
                headers={REPLAY_HEADER: "true"},
            )

        status_code, body = handler()
        store.save_idempotency(
            key,
            IdempotencyRecord(
                request_hash=request_hash,
                status_code=status_code,
                body=copy.deepcopy(body),
            ),
        )
        return JSONResponse(
            status_code=status_code,
            content=body,
            headers={REPLAY_HEADER: "false"},
        )
