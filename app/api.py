"""HTTP 路由层。

* ``/api/v1/items/{id}``：旧版本入口，OpenAPI 标记 deprecated，
  响应带 ``Deprecation`` / ``Sunset`` / ``Warning`` 头，但继续可用；
* ``/api/v2/items/{id}``：当前版本；
* ``/api/{其他任意版本}/...``：不回落到任何默认版本，直接返回
  ``unsupported_api_version``（静态路由先注册、参数兜底路由后注册）；
* 写入通过 ``Idempotency-Key`` 头保证幂等；
* 读取/写入响应统一带 ``X-Resource-Version`` 头。

v1 与 v2 共享同一份领域状态，仅在表现层做投影：
v1 的 ``value`` 对应 v2 的规范字段 ``name``。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.errors import APIError, UnsupportedAPIVersion
from app.fingerprint import request_fingerprint
from app.service import ItemService
from app.versioning import APIVersion, is_deprecated

logger = logging.getLogger("versioned_api")

SUNSET_DATE = "Sat, 31 Dec 2026 23:59:59 GMT"


# ---------------------------------------------------------------- 模型
class V1ItemIn(BaseModel):
    value: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)


class V2ItemIn(BaseModel):
    name: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)


def _project_v1(canonical: dict[str, Any]) -> dict[str, Any]:
    return {"id": canonical["id"], "value": canonical["name"], "version": canonical["version"]}


def _project_v2(canonical: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": canonical["id"],
        "name": canonical["name"],
        "data": canonical["data"],
        "version": canonical["version"],
    }


def _deprecation_headers() -> dict[str, str]:
    return {
        "Deprecation": f'date="{SUNSET_DATE}"',
        "Sunset": SUNSET_DATE,
        # HTTP 头只能使用 latin-1，警告文案使用 ASCII（详见文档中文版说明）。
        "Warning": '299 - "API version v1 is deprecated; please migrate to /api/v2"',
    }


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise APIError("请求体必须是合法的 JSON 对象") from exc
    if not isinstance(value, dict):
        raise APIError("请求体必须是 JSON 对象")
    return value


# ------------------------------------------------------------ 应用工厂
def create_app(service: ItemService | None = None) -> FastAPI:
    app = FastAPI(title="版本化幂等写入示例 API")
    svc = service or ItemService()

    @app.exception_handler(APIError)
    async def _handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

    # ------------------------------------------------ 共享内部处理
    def _read(version: APIVersion, item_id: str) -> JSONResponse:
        item = svc.read(item_id)
        canonical = {
            "id": item.id, "name": item.name,
            "data": dict(item.data), "version": item.version,
        }
        body = _project_v1(canonical) if version is APIVersion.V1 else _project_v2(canonical)
        headers = {"X-Resource-Version": str(item.version)}
        if is_deprecated(version):
            headers.update(_deprecation_headers())
        return JSONResponse(status_code=200, content=body, headers=headers)

    async def _write(version: APIVersion, item_id: str, request: Request) -> JSONResponse:
        raw = await request.body()
        payload = _parse_json_object(raw)
        if version is APIVersion.V1:
            model = V1ItemIn.model_validate(payload)
            name, data = model.value, dict(model.data)
        else:
            model = V2ItemIn.model_validate(payload)
            name, data = model.name, dict(model.data)

        idem_key = request.headers.get("idempotency-key")
        fp = request_fingerprint(request.method, request.url.path, raw)
        try:
            result = svc.write(
                item_id,
                name=name,
                data=data,
                merge=False,
                expected_version=model.expected_version,
                idempotency_key=idem_key,
                fingerprint=fp,
            )
        except APIError as exc:
            logger.info(
                "场景日志 写入被拒绝 version=%s item=%s code=%s",
                version.value, item_id, exc.code,
            )
            raise

        body = _project_v1(result.body) if version is APIVersion.V1 else _project_v2(result.body)
        headers = {"X-Resource-Version": str(result.body["version"])}
        if result.replayed:
            headers["Idempotency-Replayed"] = "true"
        if is_deprecated(version):
            headers.update(_deprecation_headers())
        logger.info(
            "场景日志 写入成功 version=%s item=%s status=%s replayed=%s resource_version=%s",
            version.value, item_id, result.status_code, result.replayed, result.body["version"],
        )
        return JSONResponse(status_code=result.status_code, content=body, headers=headers)

    # ------------------------------------------------ v1（弃用但可用）
    @app.get("/api/v1/items/{item_id}", deprecated=True)
    async def read_v1(item_id: str) -> JSONResponse:
        return _read(APIVersion.V1, item_id)

    @app.put("/api/v1/items/{item_id}", deprecated=True)
    @app.post("/api/v1/items/{item_id}", deprecated=True)
    async def write_v1(item_id: str, request: Request) -> JSONResponse:
        return await _write(APIVersion.V1, item_id, request)

    # ------------------------------------------------ v2（当前版本）
    @app.get("/api/v2/items/{item_id}")
    async def read_v2(item_id: str) -> JSONResponse:
        return _read(APIVersion.V2, item_id)

    @app.put("/api/v2/items/{item_id}")
    @app.post("/api/v2/items/{item_id}")
    async def write_v2(item_id: str, request: Request) -> JSONResponse:
        return await _write(APIVersion.V2, item_id, request)

    # ------------------------------------------------ 未识别版本兜底
    @app.get("/api/{version}/items/{item_id}")
    async def read_unknown(version: str, item_id: str) -> JSONResponse:
        raise UnsupportedAPIVersion(
            f"不支持的 API 版本: {version!r}",
            details={"version": version, "supported": ["v1", "v2"]},
        )

    @app.put("/api/{version}/items/{item_id}")
    @app.post("/api/{version}/items/{item_id}")
    async def write_unknown(version: str, item_id: str, request: Request) -> JSONResponse:
        raise UnsupportedAPIVersion(
            f"不支持的 API 版本: {version!r}",
            details={"version": version, "supported": ["v1", "v2"]},
        )

    return app
