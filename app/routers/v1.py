"""v1 接口（已弃用，但继续可用）。

弃用通过 RFC 8594 的 ``Deprecation`` 等响应头明确标记；响应体字段集合
保持稳定（id/title/content/version），不随 v2 增加字段，避免破坏旧客户端。
v1 与 v2 共用同一存储，状态与版本号始终一致。
"""

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.errors import NotFoundError
from app.idempotency import handle_with_idempotency
from app.schemas import DocumentIn
from app.services import create_document, update_document
from app.store import store
from app.versions import v1_deprecation_headers

router = APIRouter(prefix="/api/v1", tags=["v1-deprecated"])


def _serialize(resource) -> dict:  # noqa: ANN001
    """v1 固定字段集合：新增字段永远不会出现在 v1 响应中。"""
    return {
        "id": resource.id,
        "title": resource.title,
        "content": resource.content,
        "version": resource.version,
    }


def _with_deprecation(response: JSONResponse) -> JSONResponse:
    response.headers.update(v1_deprecation_headers())
    return response


@router.post("/documents")
async def create_document_v1(
    request: Request,
    payload: DocumentIn,
    idempotency_key: str | None = Header(default=None),
) -> JSONResponse:
    """创建文档（v1，已弃用）。"""

    def do_create() -> tuple[int, dict]:
        status_code, resource = create_document(None, payload)
        return status_code, _serialize(resource)

    response = await handle_with_idempotency(request, payload, do_create)
    return _with_deprecation(response)


@router.put("/documents/{doc_id}")
async def update_document_v1(
    request: Request,
    doc_id: str,
    payload: DocumentIn,
    idempotency_key: str | None = Header(default=None),
    if_match: str | None = Header(default=None),
) -> JSONResponse:
    """更新文档（v1，已弃用）。"""

    def do_update() -> tuple[int, dict]:
        status_code, resource = update_document(doc_id, payload, if_match)
        return status_code, _serialize(resource)

    response = await handle_with_idempotency(request, payload, do_update)
    return _with_deprecation(response)


@router.get("/documents/{doc_id}")
def get_document_v1(doc_id: str) -> JSONResponse:
    """读取文档（v1，已弃用）；不存在返回 404 ``not_found``。"""
    resource = store.get_resource(doc_id)
    if resource is None:
        raise NotFoundError(doc_id)
    return _with_deprecation(
        JSONResponse(status_code=200, content=_serialize(resource))
    )
