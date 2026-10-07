"""请求内容指纹工具。

指纹覆盖 HTTP 方法、路径与规范化后的请求体（JSON 键排序、
去除无意义空白），保证：

* 字节层面不同但语义相同的 JSON（键序、空格差异）得到相同指纹；
* 同键但任意字段不同的请求得到不同指纹；
* 不同入口（如 ``/api/v1/...`` 与 ``/api/v2/...``）天然区分。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_payload(raw: bytes) -> bytes:
    """把 JSON 请求体规范化为字节串；非 JSON 原样返回。"""
    if not raw:
        return b""
    try:
        value: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return raw
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def request_fingerprint(method: str, path: str, payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(method.upper().encode("ascii"))
    digest.update(b"\x00")
    digest.update(path.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical_payload(payload))
    return digest.hexdigest()
