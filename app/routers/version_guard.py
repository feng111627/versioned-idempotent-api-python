"""兜底路由：未识别/不受支持的 API 版本给出明确错误。

不会默认落到 v1 或 v2；任何未精确匹配受支持前缀的版本化路径都返回
404 ``version_not_supported``，并在 ``Link`` 头中列出受支持的文档入口。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.versions import unsupported_version_body

router = APIRouter()

_SUPPORT_LINK = '</api/v2/documents>; rel="current", </api/v1/documents>; rel="deprecation"'


def _unsupported(version: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=unsupported_version_body(version),
        headers={"Link": _SUPPORT_LINK},
    )


def _versioned(method: str):
    def endpoint(version: str, rest: str) -> JSONResponse:
        return _unsupported(version)

    endpoint.__name__ = f"unknown_version_{method.lower()}"
    endpoint.__doc__ = f"不受支持版本路径的 {method} 兜底。"
    return router.api_route(
        "/api/{version}/{rest:path}", methods=[method]
    )(endpoint)


def _root(method: str):
    def endpoint() -> JSONResponse:
        return _unsupported("")

    endpoint.__name__ = f"version_missing_{method.lower()}"
    endpoint.__doc__ = f"未指定版本入口（/api）的 {method} 兜底。"
    return endpoint


for _m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
    _versioned(_m)
    router.api_route("/api", methods=[_m])(_root(_m))
    router.api_route("/api/", methods=[_m])(_root(_m))
