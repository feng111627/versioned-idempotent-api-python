"""场景2：资源版本与乐观并发控制。

覆盖：
* 读取结果携带可用版本标识（响应体 + X-Resource-Version 头）；
* 携带正确版本写入后版本严格 +1 推进；
* 过期版本被拒绝（version_conflict）而非静默覆盖，响应回传当前版本；
* 版本缺失（version_required / 428）与资源不存在（resource_not_found / 404）
  彼此可区分；
* 版本推进后，旧版本号下曾读到的读取结果不会“变味”：
  重放幂等键仍返回旧快照，最新读取另行返回新状态。
"""
from __future__ import annotations

import logging

scenario_logger = logging.getLogger("scenarios")

PATH = "/api/v2/items/doc"


def test_read_carries_version(client):
    scenario_logger.info("用例: 读取结果携带版本标识 —— 期望响应体与 X-Resource-Version 头一致")
    client.put(PATH, json={"name": "v", "data": {}}, headers={"Idempotency-Key": "create"})
    r = client.get(PATH)

    assert r.status_code == 200
    assert r.json()["version"] == 1
    assert r.headers["X-Resource-Version"] == "1"
    scenario_logger.info("结果: body.version=%s, X-Resource-Version=%s",
                         r.json()["version"], r.headers["X-Resource-Version"])


def test_write_advances_version(client):
    scenario_logger.info("用例: 携带正确版本连续写入 —— 期望版本严格 1->2->3")
    client.put(PATH, json={"name": "a"}, headers={"Idempotency-Key": "k1"})
    r2 = client.put(PATH, json={"name": "b", "expected_version": 1}, headers={"Idempotency-Key": "k2"})
    r3 = client.put(PATH, json={"name": "c", "expected_version": 2}, headers={"Idempotency-Key": "k3"})

    assert r2.status_code == 200 and r2.json()["version"] == 2
    assert r3.status_code == 200 and r3.json()["version"] == 3
    assert client.get(PATH).json()["version"] == 3
    scenario_logger.info("结果: 三次写入后版本序列为 1 -> 2 -> 3")


def test_stale_version_rejected_not_overwritten(client, service):
    scenario_logger.info("用例: 两个客户端都基于版本1写入 —— 期望后者收到 409 且内容不被覆盖")
    client.put(PATH, json={"name": "first"}, headers={"Idempotency-Key": "k1"})
    client.put(PATH, json={"name": "second", "expected_version": 1}, headers={"Idempotency-Key": "k2"})
    stale = client.put(PATH, json={"name": "stale-writer", "expected_version": 1},
                       headers={"Idempotency-Key": "k3"})

    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "version_conflict"
    assert body["details"] == {"resource_id": "doc", "expected_version": 1, "current_version": 2}
    # 过期写入绝不能静默覆盖：资源仍是第二次写入的内容。
    current = service.read("doc")
    assert current.name == "second" and current.version == 2
    scenario_logger.info("结果: 过期写入被拒（当前版本=%s），资源保持 name=second/version=2",
                         body["details"]["current_version"])


def test_missing_version_distinguishable(client):
    scenario_logger.info("用例: 更新已存在资源但不带版本 —— 期望 428 version_required")
    client.put(PATH, json={"name": "seed"}, headers={"Idempotency-Key": "k1"})
    r = client.put(PATH, json={"name": "no-version"}, headers={"Idempotency-Key": "k2"})

    assert r.status_code == 428
    assert r.json()["code"] == "version_required"
    assert r.json()["details"]["current_version"] == 1
    scenario_logger.info("结果: 状态码 428，错误码 %s", r.json()["code"])


def test_not_found_distinguishable(client):
    scenario_logger.info("用例: 读取/更新不存在的资源 —— 期望 404 resource_not_found，与版本缺失区分")
    r_get = client.get("/api/v2/items/ghost")
    r_put = client.put("/api/v2/items/ghost", json={"name": "x", "expected_version": 9})

    assert r_get.status_code == 404 and r_get.json()["code"] == "resource_not_found"
    assert r_put.status_code == 404 and r_put.json()["code"] == "resource_not_found"
    assert r_put.json()["details"]["current_version"] is None
    scenario_logger.info("结果: 读/写不存在资源均为 404 resource_not_found（不同于 428/409）")


def test_stale_read_snapshot_remains_compatible(client):
    scenario_logger.info("用例: 版本推进后旧读取结果兼容 —— 期望旧键重放旧快照、新读取得新状态")
    created = client.put(PATH, json={"name": "old", "data": {"x": 1}},
                         headers={"Idempotency-Key": "snap"})
    old_snapshot = created.json()
    client.put(PATH, json={"name": "new", "data": {"x": 2}, "expected_version": 1},
               headers={"Idempotency-Key": "next"})

    replay = client.put(PATH, json={"name": "old", "data": {"x": 1}},
                        headers={"Idempotency-Key": "snap"})
    fresh = client.get(PATH)

    # 旧版本上的结果形态（id/name/data/version）仍可被老客户端解析，且值保持为当时快照。
    assert replay.json() == old_snapshot
    assert set(old_snapshot) == {"id", "name", "data", "version"}
    assert replay.json()["version"] == 1
    # 新读取看到推进后的状态，两者互不污染。
    assert fresh.json()["version"] == 2 and fresh.json()["name"] == "new"
    scenario_logger.info("结果: 旧快照仍为 version=1/name=old，最新读取为 version=2/name=new")
