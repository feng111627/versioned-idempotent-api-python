"""统一的应用错误类型。

每种错误都带有稳定的机器可读 ``code``，以及对应的 HTTP 状态码，
便于客户端区分：幂等冲突 / 资源版本缺失 / 资源版本冲突 /
资源不存在 / 不支持的对外 API 版本。
"""
from __future__ import annotations

from typing import Any


class APIError(Exception):
    """所有可返回给客户端的错误的基类。"""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details: dict[str, Any] = dict(details or {})

    def to_body(self) -> dict[str, Any]:
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details or None,
        }


class ResourceNotFound(APIError):
    """资源不存在（404，错误码 resource_not_found）。"""

    status_code = 404
    code = "resource_not_found"


class ResourceVersionMissing(APIError):
    """更新已存在资源时未携带版本（428，错误码 version_required）。"""

    status_code = 428
    code = "version_required"


class ResourceVersionConflict(APIError):
    """携带的版本已过期（409，错误码 version_conflict），并回传当前版本。"""

    status_code = 409
    code = "version_conflict"


class IdempotencyConflict(APIError):
    """同一幂等键但请求内容不同（409，错误码 idempotency_conflict）。"""

    status_code = 409
    code = "idempotency_conflict"


class UnsupportedAPIVersion(APIError):
    """路径中的对外版本不被支持（400，错误码 unsupported_api_version）。"""

    status_code = 400
    code = "unsupported_api_version"
