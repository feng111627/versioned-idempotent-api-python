"""场景组：对外 API 版本的演进。"""

import json

import pytest

pytestmark = pytest.mark.scenario(
    "API版本演进",
    "v1 弃用但可用；新旧版本状态一致；未识别版本明确报错不回落",
)


def _create(client, base, key, body=None):
    body = body or {"title": "shared", "content": "hello"}
    return client.post(
        f"{base}/documents",
        content=json.dumps(body),
        headers={"Idempotency-Key": key, "Content-Type": "application/json"},
    )


def test_v1_marked_deprecated_but_functional(client):
    """v1 入口继续可用，并通过响应头明确标记弃用。"""
    r = _create(client, "/api/v1", "v1-create")
    assert r.status_code == 201
    assert r.headers.get("Deprecation") == "true"
    assert "v2" in r.headers.get("X-Api-Deprecated", "")

    doc_id = r.json()["id"]
    g = client.get(f"/api/v1/documents/{doc_id}")
    assert g.status_code == 200
    assert g.headers.get("Deprecation") == "true"
    # v1 响应字段集合保持稳定
    assert set(g.json().keys()) == {"id", "title", "content", "version"}


def test_v2_is_not_marked_deprecated(client):
    """v2 不带弃用标记，且在兼容前提下扩展字段。"""
    r = _create(client, "/api/v2", "v2-create")
    assert r.headers.get("Deprecation") is None
    body = r.json()
    assert set(body.keys()) == {"id", "title", "content", "version", "update_count"}


def test_cross_version_state_consistency(client):
    """在 v2 写入后，v1 读到同一资源、同一版本；v1 写入后 v2 也立即可见。"""
    r = _create(client, "/api/v2", "cross-1", {"title": "s", "content": "v2-made"})
    doc_id = r.json()["id"]

    g1 = client.get(f"/api/v1/documents/{doc_id}")
    g2 = client.get(f"/api/v2/documents/{doc_id}")
    assert g1.status_code == g2.status_code == 200
    assert g1.json()["id"] == g2.json()["id"] == doc_id
    assert g1.json()["version"] == g2.json()["version"] == 1
    assert g1.json()["content"] == g2.json()["content"] == "v2-made"

    # 经 v1 推进版本
    u1 = client.put(
        f"/api/v1/documents/{doc_id}",
        content=json.dumps({"title": "s", "content": "v1-made"}),
        headers={"Idempotency-Key": "cross-u1", "If-Match": "1",
                 "Content-Type": "application/json"},
    )
    assert u1.status_code == 200
    assert u1.headers.get("Deprecation") == "true"

    g2_after = client.get(f"/api/v2/documents/{doc_id}").json()
    assert g2_after["content"] == "v1-made"
    assert g2_after["version"] == 2  # 版本号跨版本共享、单调推进


def test_same_version_replay_is_consistent(client):
    """同一版本内重复提交只产生一次效果（幂等键在服务端全局唯一）。"""
    key = "shared-key-x"
    body = {"title": "s", "content": "payload"}
    headers = {"Idempotency-Key": key, "Content-Type": "application/json"}

    r_v2 = client.post("/api/v2/documents", content=json.dumps(body), headers=headers)
    r_v2_again = client.post(
        "/api/v2/documents", content=json.dumps(body), headers=headers
    )
    # v2 内重复回放
    assert r_v2.status_code == 201
    assert r_v2_again.headers["Idempotency-Replayed"] == "true"
    assert r_v2_again.json()["id"] == r_v2.json()["id"]


def test_unknown_version_explicit_error_no_fallback(client):
    """未识别/不受支持的版本返回明确错误，绝不默认落到某个版本。"""
    r = client.get("/api/v3/documents/anything")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "version_not_supported"
    assert "v3" in r.json()["error"]["message"]


def test_versionless_api_path_rejected(client):
    """/api 与 /api/ 未指定版本时明确报错。"""
    for path in ("/api", "/api/"):
        r = client.get(path)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "version_not_supported"


def test_unknown_version_rejects_writes_too(client):
    """向不受支持的版本写入也不会被静默处理。"""
    r = client.post(
        "/api/v9/documents",
        content=json.dumps({"title": "x", "content": "y"}),
        headers={"Idempotency-Key": "k", "Content-Type": "application/json"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "version_not_supported"
