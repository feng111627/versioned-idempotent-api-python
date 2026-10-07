"""场景组：资源版本与乐观并发控制（OCC）。"""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.scenario(
    "版本与乐观并发",
    "读取带版本；写入校验 If-Match；冲突/缺失/不存在可区分；版本单调推进",
)


def _make(client, key="seed", body=None):
    body = body or {"title": "doc", "content": "init"}
    r = client.post(
        "/api/v2/documents",
        content=json.dumps(body),
        headers={"Idempotency-Key": key, "Content-Type": "application/json"},
    )
    assert r.status_code == 201
    return r.json()


def test_read_carries_version(client):
    """读取结果带有可用的版本标识，创建后初始版本为 1。"""
    doc = _make(client)
    got = client.get(f"/api/v2/documents/{doc['id']}")
    assert got.status_code == 200
    body = got.json()
    assert body["version"] == 1
    assert isinstance(body["version"], int)


def test_update_advances_version_monotonically(client):
    """携带当前版本的更新成功且版本单调推进，返回新版本。"""
    doc = _make(client)
    r = client.put(
        f"/api/v2/documents/{doc['id']}",
        json={"title": "doc", "content": "second"},
        headers={"Idempotency-Key": "u1", "If-Match": "1"},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2

    r2 = client.put(
        f"/api/v2/documents/{doc['id']}",
        json={"title": "doc", "content": "third"},
        headers={"Idempotency-Key": "u2", "If-Match": "2"},
    )
    assert r2.status_code == 200
    assert r2.json()["version"] == 3


def test_stale_version_rejected_with_distinct_error(client):
    """过期版本必须拒绝而不是静默覆盖：409 version_conflict。"""
    doc = _make(client)
    client.put(
        f"/api/v2/documents/{doc['id']}",
        json={"title": "doc", "content": "second"},
        headers={"Idempotency-Key": "u1", "If-Match": "1"},
    )
    stale = client.put(
        f"/api/v2/documents/{doc['id']}",
        json={"title": "doc", "content": "late-write"},
        headers={"Idempotency-Key": "u-late", "If-Match": "1"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    # 被拒绝的写入没有落盘
    got = client.get(f"/api/v2/documents/{doc['id']}").json()
    assert got["content"] == "second"
    assert got["version"] == 2


def test_missing_version_distinct_from_conflict(client):
    """未携带版本：428 version_required，与版本冲突、不存在明确区分。"""
    doc = _make(client)
    r = client.put(
        f"/api/v2/documents/{doc['id']}",
        json={"title": "doc", "content": "x"},
        headers={"Idempotency-Key": "u-noversion"},
    )
    assert r.status_code == 428
    assert r.json()["error"]["code"] == "version_required"


def test_not_found_distinct(client):
    """更新或读取不存在的资源：404 not_found。"""
    r = client.put(
        "/api/v2/documents/ghost",
        json={"title": "x", "content": "y"},
        headers={"Idempotency-Key": "ghost-k", "If-Match": "1"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"

    g = client.get("/api/v2/documents/ghost")
    assert g.status_code == 404
    assert g.json()["error"]["code"] == "not_found"


def test_concurrent_competing_updates_only_one_wins(client):
    """两个并发的竞争更新：版本只允许一个成功，另一个收到冲突而非覆盖。"""
    doc = _make(client)
    doc_id = doc["id"]
    results: dict = {}

    # 两个不同幂等键、相同基准版本的竞争写入，使用屏障同时发出
    import threading

    barrier = threading.Barrier(2)

    def attempt(name, key, content):
        barrier.wait()
        r = client.put(
            f"/api/v2/documents/{doc_id}",
            content=json.dumps({"title": "doc", "content": content}),
            headers={
                "Idempotency-Key": key,
                "If-Match": "1",
                "Content-Type": "application/json",
            },
        )
        results[name] = r

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(attempt, "A", "race-a", "from-A")
        f2 = pool.submit(attempt, "B", "race-b", "from-B")
        f1.result(); f2.result()

    statuses = sorted(results[n].status_code for n in results)
    assert statuses == [200, 409]
    winner = next(n for n in results if results[n].status_code == 200)
    assert results[winner].json()["version"] == 2
    final = client.get(f"/api/v2/documents/{doc_id}").json()
    assert final["version"] == 2
    assert final["content"] == f"from-{winner}"
