"""写入领域逻辑：v1/v2 共用，保证两个 API 版本看到同一份状态。"""

import uuid

from app.errors import InvalidVersionError, VersionRequiredError
from app.schemas import DocumentIn
from app.store import Resource, store


def create_document(doc_id: str | None, payload: DocumentIn) -> tuple[int, Resource]:
    """创建文档。

    ``doc_id`` 为 ``None`` 时由服务端生成标识。返回 ``(HTTP 状态码, 资源)``。
    幂等回放以外的重复创建（同 id 再次 POST）返回 200 而不重复创建。
    """
    resource_id = doc_id or uuid.uuid4().hex
    existing = store.get_resource(resource_id)
    if existing is not None:
        return 200, existing
    return 201, store.create_resource(resource_id, payload)


def _parse_if_match(if_match: str | None) -> int:
    """解析 If-Match 版本号；缺失或非正整数时给出明确错误。"""
    if if_match is None or if_match == "":
        raise VersionRequiredError()
    raw = if_match.strip().strip('"')
    try:
        version = int(raw)
    except (TypeError, ValueError):
        raise InvalidVersionError(expected=None, provided=None) from None
    if version < 1:
        raise InvalidVersionError(expected=None, provided=version)
    return version


def update_document(
    doc_id: str, payload: DocumentIn, if_match: str | None
) -> tuple[int, Resource]:
    """带乐观并发控制的更新，返回 ``(HTTP 状态码, 资源)``。

    * 未携带 ``If-Match`` -> 428 ``version_required``；
    * 资源不存在 -> 404 ``not_found``；
    * 版本不匹配 -> 409 ``version_conflict``；
    * 成功 -> 200，资源 ``version`` 单调递增。
    """
    expected_version = _parse_if_match(if_match)
    return 200, store.update_resource(doc_id, payload, expected_version)
