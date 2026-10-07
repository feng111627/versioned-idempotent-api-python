"""领域异常与统一错误响应。

所有可预期的业务错误都抛出 ``APIError`` 子类，由统一的异常处理器转成
固定形状的 JSON 响应：

    {"error": {"code": "...", "message": "..."}}

不同错误使用不同的 ``code`` 与 HTTP 状态码，客户端可以明确区分
“版本冲突 / 版本缺失 / 资源不存在 / 幂等键内容冲突 / 版本不受支持”。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """所有可预期业务错误的基类。"""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code
        super().__init__(self.message)


class InvalidVersionError(APIError):
    """客户端提交的资源版本与服务端当前版本不一致（乐观并发冲突）。"""

    status_code = 409
    code = "version_conflict"

    def __init__(self, expected: int | None = None, provided: int | None = None) -> None:
        super().__init__(
            f"版本冲突：资源当前版本为 {expected}，请求携带的版本为 {provided}"
        )
        self.current_version = expected


class VersionRequiredError(APIError):
    """写入时未携带版本标识。"""

    status_code = 428
    code = "version_required"

    def __init__(self) -> None:
        super().__init__("更新已有资源时必须通过 If-Match 头携带版本标识")


class NotFoundError(APIError):
    """目标资源不存在。"""

    status_code = 404
    code = "not_found"

    def __init__(self, resource_id: str | None = None) -> None:
        detail = f"：{resource_id}" if resource_id is not None else ""
        super().__init__(f"资源不存在{detail}")


class IdempotencyConflictError(APIError):
    """同一幂等键携带了不同的请求内容。"""

    status_code = 409
    code = "idempotency_conflict"

    def __init__(self, key: str) -> None:
        super().__init__(
            f"幂等键 {key!r} 已被用于不同内容的请求；同一幂等键必须提交相同内容"
        )


class UnsupportedVersionError(APIError):
    """请求的 API 版本无法识别或不受支持。"""

    status_code = 404
    code = "version_not_supported"

    def __init__(self, version: str) -> None:
        super().__init__(
            f"API 版本 {version!r} 不受支持；支持的版本：1（已弃用）、2"
        )


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    """构造统一错误体。"""
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册异常处理器。"""

    @app.exception_handler(APIError)
    async def handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message),
        )
