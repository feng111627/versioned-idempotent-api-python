"""统一的应用错误类型（骨架）。"""
from __future__ import annotations


class APIError(Exception):
    """所有可返回给客户端的错误的基类。"""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str = "", *, details: dict | None = None) -> None:
        ...


class IdempotencyConflict(APIError):
    ...


class ResourceVersionMissing(APIError):
    ...


class ResourceVersionConflict(APIError):
    ...


class ResourceNotFound(APIError):
    ...


class UnsupportedAPIVersion(APIError):
    ...
