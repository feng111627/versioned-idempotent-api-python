"""场景3：对外 API 版本演进与跨版本一致性。

覆盖：
* v1 旧入口继续可用，且带明确弃用标记（OpenAPI deprecated + 弃用响应头）；
* v2 为当前形态（id/name/data/version），不带弃用头；
* v1 与 v2 读写同一份底层状态：任一版本写入，另一版本立即可见、版本号一致；
* 未识别 / 不受支持的版本返回 unsupported_api_version，绝不默认落到 v1 或 v2。
"""
from __future__ import annotations

import logging

scenario_logger = logging.getLogger("scenarios")


def test_v1_marked_deprecated_but_usable(client):
    scenario_logger.info("用例: v1 入口可读可写，但带弃用标记 —— 期望 200/201 + Deprecation/Sunset/Warning")
    created = client.put("/api/v1/items/a", json={"value": "alpha"}, headers={"Idempotency-Key": "c"})
    read = client.get("/api/v1/items/a")

    assert created.status_code == 201
    assert read.status_code == 200
    assert read.json() == {"id": "a", "value": "alpha", "version": 1}
    for header in ("Deprecation", "Sunset", "Warning"):
        assert read.headers.get(header), f"v1 响应缺少弃用头 {header}"
    assert "299" in read.headers["Warning"]

    # OpenAPI 中 v1 路由被标记 deprecated。
    spec = client.get("/openapi.json").json()
    v1_put = spec["paths"]["/api/v1/items/{item_id}"]["put"]
    assert v1_put["deprecated"] is True
    scenario_logger.info("结果: v1 功能正常，弃用头齐全，OpenAPI deprecated=true")


def test_v2_full_shape(client):
    scenario_logger.info("用例: v2 完整形态 —— 期望含 name/data，且不带弃用头")
    client.put("/api/v2/items/b", json={"name": "beta", "data": {"n": 1}},
               headers={"Idempotency-Key": "c"})
    r = client.get("/api/v2/items/b")

    assert r.status_code == 200
    assert r.json() == {"id": "b", "name": "beta", "data": {"n": 1}, "version": 1}
    assert "Deprecation" not in r.headers and "Warning" not in r.headers

    spec = client.get("/openapi.json").json()
    assert "deprecated" not in spec["paths"]["/api/v2/items/{item_id}"]["put"]
    scenario_logger.info("结果: v2 返回完整形态且无弃用标记")


def test_cross_version_state_consistent(client):
    scenario_logger.info("用例: v1 写 / v2 读 / v2 写 / v1 读 —— 期望同一状态、版本号联动")
    r1 = client.put("/api/v1/items/shared", json={"value": "from-v1"},
                    headers={"Idempotency-Key": "k1"})
    assert r1.status_code == 201

    v2_read = client.get("/api/v2/items/shared")
    assert v2_read.json()["name"] == "from-v1"
    assert v2_read.json()["version"] == 1

    r2 = client.put("/api/v2/items/shared",
                    json={"name": "from-v2", "data": {"via": "v2"}, "expected_version": 1},
                    headers={"Idempotency-Key": "k2"})
    assert r2.status_code == 200 and r2.json()["version"] == 2

    v1_read = client.get("/api/v1/items/shared")
    # v1 仅投影其认识的字段（id/value/version），底层状态与 v2 完全一致。
    assert v1_read.json() == {"id": "shared", "value": "from-v2", "version": 2}
    v2_again = client.get("/api/v2/items/shared")
    assert v2_again.json()["data"] == {"via": "v2"}
    assert v1_read.json()["version"] == v2_again.json()["version"] == 2
    scenario_logger.info("结果: 两版本读到同一资源与同一版本号 2，v1 旧字段映射保持稳定")


def test_unknown_version_explicit_error(client):
    scenario_logger.info("用例: 请求 v3/v0/absurd 等未知版本 —— 期望 400 unsupported_api_version，不回落")
    for bad in ("v3", "v0", "absurd", "V2"):
        r = client.get(f"/api/{bad}/items/x")
        assert r.status_code == 400, bad
        body = r.json()
        assert body["code"] == "unsupported_api_version"
        assert body["details"]["version"] == bad
        assert body["details"]["supported"] == ["v1", "v2"]

    # 写未知版本同样被拒绝。
    rw = client.put("/api/v3/items/x", json={"name": "x"})
    assert rw.status_code == 400 and rw.json()["code"] == "unsupported_api_version"
    scenario_logger.info("结果: v3/v0/absurd/V2（大小写敏感）均显式报错，支持列表为 ['v1','v2']")
