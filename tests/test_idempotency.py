"""场景1：写入幂等与并发重复提交。

覆盖：
* 同键同内容重复提交只生效一次、返回一致结果；
* 同键不同内容被明确拒绝（idempotency_conflict）；
* 并发到达的重复请求只生效一次，不出现重复/部分生效；
* 并发中混入不同内容时，重复方重放、异内容方被拒。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

scenario_logger = logging.getLogger("scenarios")

PATH = "/api/v2/items/widget"
BODY = {"name": "hello", "data": {"k": "v"}}


def _put(client, key: str, body: dict, barrier: threading.Barrier | None = None):
    if barrier is not None:
        barrier.wait()
    return client.put(PATH, json=body, headers={"Idempotency-Key": key})


def test_same_key_same_content_applies_once(client, service):
    scenario_logger.info("用例: 同键同内容重复提交 —— 期望只创建一次、第二次被重放")
    r1 = _put(client, "key-once", BODY, None)
    r2 = _put(client, "key-once", dict(reversed(list(BODY.items()))), None)  # 键序不同但内容一致

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json() == r2.json() == {"id": "widget", "name": "hello", "data": {"k": "v"}, "version": 1}
    assert r2.headers["Idempotency-Replayed"] == "true"
    assert service.read("widget").version == 1
    scenario_logger.info("结果: 两次返回均为 201 且体完全一致，资源版本停留在 1")


def test_same_key_different_content_rejected(client, service):
    scenario_logger.info("用例: 同键不同内容 —— 期望 409 idempotency_conflict 且状态不变")
    r1 = _put(client, "key-clash", BODY, None)
    r2 = _put(client, "key-clash", {"name": "different"}, None)

    assert r1.status_code == 201
    assert r2.status_code == 409
    err = r2.json()
    assert err["code"] == "idempotency_conflict"
    assert err["details"]["idempotency_key"] == "key-clash"
    # 资源保持首次请求写入的内容与版本。
    assert service.read("widget").name == "hello"
    assert service.read("widget").version == 1
    scenario_logger.info("结果: 异内容请求被拒绝（%s），资源未被改动", err["code"])


def test_concurrent_duplicates_apply_once(make_client):
    scenario_logger.info("用例: 8 个线程同键同内容并发提交 —— 期望仅一次生效，其余全部重放")
    n = 8
    barrier = threading.Barrier(n)
    with ThreadPoolExecutor(max_workers=n) as pool:
        responses = list(pool.map(lambda _: _put(make_client(), "key-race", BODY, barrier), range(n)))

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] * n
    bodies = {r.text for r in responses}
    assert len(bodies) == 1  # 所有响应体逐字节一致
    replayed = sum(1 for r in responses if r.headers.get("Idempotency-Replayed") == "true")
    assert replayed == n - 1
    scenario_logger.info("结果: 8 个响应均为 201 且同体；首个生效 1 次，重放 %d 次", replayed)


def test_concurrent_mixed_content_same_key(make_client, service):
    scenario_logger.info("用例: 定调后 6 个相同 + 2 个不同内容同键并发 —— 期望相同方一致重放、异内容方拒绝")
    # 首个同内容请求先行“定调”（建立该幂等键的内容契约）。
    seed = _put(make_client(), "key-mixed", BODY, None)
    assert seed.status_code == 201

    same_n, diff_n = 6, 2
    barrier = threading.Barrier(same_n + diff_n)

    def job(kind: int):
        body = BODY if kind == 0 else {"name": f"intruder-{kind}"}
        return _put(make_client(), "key-mixed", body, barrier)

    with ThreadPoolExecutor(max_workers=same_n + diff_n) as pool:
        responses = list(pool.map(job, [0] * same_n + [1, 2]))

    ok = [r for r in responses if r.status_code == 201]
    rejected = [r for r in responses if r.status_code == 409]
    assert len(ok) == same_n
    assert len(rejected) == diff_n
    assert {r.json()["code"] for r in rejected} == {"idempotency_conflict"}
    assert len({r.text for r in ok}) == 1
    assert service.read("widget").version == 1
    assert service.read("widget").name == "hello"
    scenario_logger.info("结果: 6 个重复请求一致重放成功，2 个异内容请求被拒；连同定调请求资源仍只生效一次")


def test_replay_returns_consistent_result_after_state_advances(client, service):
    scenario_logger.info("用例: 首次创建后资源被其他请求推进，再重放旧键 —— 期望返回首次的冻结结果")
    r1 = _put(client, "key-history", BODY, None)
    # 另一个请求（不同幂等键）把资源推进到版本 2。
    client.put(PATH, json={"name": "later", "expected_version": 1}, headers={"Idempotency-Key": "other"})
    r3 = _put(client, "key-history", BODY, None)

    assert r1.status_code == r3.status_code == 201
    assert r1.json() == r3.json()
    assert r3.json()["version"] == 1
    assert r3.headers["Idempotency-Replayed"] == "true"
    scenario_logger.info("结果: 重放仍返回 201/version=1 的首次结果，与当前资源版本 %s 互不干扰",
                         service.read("widget").version)
