"""v2 接口（当前推荐版本）。

读取结果在 v1 字段基础上兼容式扩展 ``update_count``；写入语义与 v1 完全
一致且共用同一存储，因此 v1、v2 看到的资源状态与版本号保持同步。
"""

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.idempotency import handle_with_idempotency
from app.schemas import DocumentIn
from app.services import create_document, update_document
from app.store import store

router = APIRouter(prefix="/api/v2", tags=["v2"])


def _serialize(resource) -> dict:  # noqa: ANN001
    return {
        "id": resource.id,
        "title": resource.title,
        "content": resource.content,
        "version": resource.version,
        "update_count": resource.update_count,
    }


@router.post("/documents")
async def create_document_v2(
    request: Request,
    payload: DocumentIn,
    idempotency_key: str | None = Header(default=None),
) -> JSONResponse:
    """创建文档。需要 ``Idempotency-Key``，重复提交只生效一次。"""

    def do_create() -> tuple[int, dict]:
        status_code, resource = create_document(None, payload)
        return status_code, _serialize(resource)

    return await handle_with_idempotency(request, payload, do_create)


@router.put("/documents/{doc_id}")
async def update_document_v2(
    request: Request,
    doc_id: str,
    payload: DocumentIn,
    idempotency_key: str | None = Header(default=None),
    if_match: str | None = Header(default=None),
) -> JSONResponse:
    """更新文档。需要 ``Idempotency-Key`` 与 ``If-Match`` 版本号。"""

    def do_update() -> tuple[int, dict]:
        status_code, resource = update_document(doc_id, payload, if_match)
        return status_code, _serialize(resource)

    return await handle_with_idempotency(request, payload, do_update)


@router.get("/documents/{doc_id}")
def get_document_v2(doc_id: str) -> JSONResponse:
    """读取文档；不存在返回 404 ``not_found``。"""
    from app.errors import NotFoundError

    resource = store.get_resource(doc_id)
    if resource is None:
        raise NotFoundError(doc_id)
    return JSONResponse(status_code=200, content=_serialize(resource))
