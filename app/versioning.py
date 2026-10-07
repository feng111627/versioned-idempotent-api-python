"""对外 API 版本定义。

* ``v1``：已弃用（响应带 RFC 9745 的 ``Warning`` 头，OpenAPI 标记 deprecated），
  但仍继续可用；
* ``v2``：当前版本。

未识别 / 不受支持的版本不会回落到任何默认版本，
而是由路由层返回 ``unsupported_api_version``。
"""
from __future__ import annotations

from enum import Enum


class APIVersion(str, Enum):
    V1 = "v1"
    V2 = "v2"


SUPPORTED_VERSIONS: tuple[str, ...] = tuple(v.value for v in APIVersion)
DEPRECATED_VERSIONS: frozenset[str] = frozenset({APIVersion.V1.value})
LATEST_VERSION = APIVersion.V2.value


def parse_api_version(raw: str) -> APIVersion | None:
    """严格解析版本标识；无法识别时返回 ``None`` 由路由层显式报错。"""
    try:
        return APIVersion(raw)
    except ValueError:
        return None  # type: ignore[return-value]


def is_deprecated(version: APIVersion) -> bool:
    return version.value in DEPRECATED_VERSIONS
