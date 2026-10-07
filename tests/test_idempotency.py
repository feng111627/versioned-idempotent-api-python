"""场景组：写入请求的幂等保障。"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.scenario(
    "写入幂等",
    "Idempotency-Key 重复提交只生效一次；同键不同内容明确拒绝；并发安全",
)


def _create(client, key, body, path="/api/v2/documents"):
    return client.post(
        path,
        content=json.dumps(body),
        headers={"Idempotency-Key": key, "Content-Type": "application/json"},
    )


def test_duplicate_request_applies_once_and_replays(client):
    """相同幂等键 + 相同内容：只创建一份资源，第二次回放一致结果。"""
    r1 = _create(client, "order-1001", {"title": "t", "content": "a"})
    r2 = _create(client, "order-1001", {"title": "t", "content": "a"})

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.headers["Idempotency-Replayed"] == "false"
    assert r2.headers["Idempotency-Replayed"] == "true"
    # 两次返回完全一致的资源
    assert r1.json() == r2.json()
    # 存储中确实只有一份资源（只生效一次）
    docs = client.get(f"/api/v2/documents/{r1.json()['id']}")
    assert docs.status_code == 200


def test_same_key_different_payload_rejected(client):
    """同一幂等键但内容不同：409 idempotency_conflict，且不产生副作用。"""
    r1 = _create(client, "order-1002", {"title": "t", "content": "original"})
    assert r1.status_code == 201
    created_id = r1.json()["id"]

    r2 = _create(client, "order-1002", {"title": "t", "content": "TAMPERED"})
    assert r2.status_code == 409
    err = r2.json()["error"]
    assert err["code"] == "idempotency_conflict"
    assert "幂等" in err["message"]

    # 原资源未被改动，且没有产生第二份资源
    got = client.get(f"/api/v2/documents/{created_id}").json()
    assert got["content"] == "original"


def test_concurrent_duplicates_single_effect(client):
    """并发到达的相同请求：恰好生效一次，所有调用拿到同一结果。"""
    barrier = threading.Barrier(8)

    def fire():
        barrier.wait()  # 尽量放大同时进入的竞态窗口
        return _create(client, "order-concurrent-1", {"title": "c", "content": "x"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: fire(), range(8)))

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] * 8
    ids = {r.json()["id"] for r in responses}
    assert ids == {next(iter(ids))}  # 全部指向同一资源
    replays = sum(
        1 for r in responses if r.headers.get("Idempotency-Replayed") == "true"
    )
    assert replays == 7  # 首次执行 1 次，其余 7 次全部回放

    # 用同一键再串行提交，结果依旧一致
    again = _create(client, "order-concurrent-1", {"title": "c", "content": "x"})
    assert again.status_code == 201
    assert again.json()["id"] == next(iter(ids))


def test_concurrent_duplicate_updates_apply_once(client):
    """并发重复的 PUT：版本只推进一次，不会出现部分生效。"""
    created = _create(client, "upd-seed", {"title": "t", "content": "v0"}).json()
    doc_id = created["id"]

    barrier = threading.Barrier(6)

    def fire():
        barrier.wait()
        return client.put(
            f"/api/v2/documents/{doc_id}",
            content=json.dumps({"title": "t", "content": "v1"}),
            headers={
                "Idempotency-Key": "upd-once",
                "If-Match": "1",
                "Content-Type": "application/json",
            },
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: fire(), range(6)))

    oks = [r for r in responses if r.status_code == 200]
    assert len(oks) == 6
    assert {r.json()["version"] for r in oks} == {2}
    # update_count 只增长一次（恰好一次生效）
    got = client.get(f"/api/v2/documents/{doc_id}").json()
    assert got["version"] == 2
    assert got["update_count"] == 2


def test_missing_idempotency_key_rejected(client):
    """写请求缺少 Idempotency-Key 时被明确拒绝。"""
    r = client.post("/api/v2/documents", json={"title": "t", "content": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "idempotency_key_required"
