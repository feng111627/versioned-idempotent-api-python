"""共享夹具与场景日志。

运行 ``pytest`` 时，日志按「场景文件 -> 用例 -> 结果」输出，
可以直接看出覆盖了哪些场景、每个场景有哪些用例以及结果如何。
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.service import ItemService

scenario_logger = logging.getLogger("scenarios")

_SCENE_TITLES = {
    "test_idempotency": "场景1 写入幂等与并发重复提交",
    "test_versioning": "场景2 资源版本与乐观并发控制",
    "test_api_versions": "场景3 对外版本演进与跨版本一致性",
}


@pytest.fixture
def service() -> ItemService:
    return ItemService()


@pytest.fixture
def app(service):
    return create_app(service)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def make_client(app):
    """每个并发线程使用各自的 TestClient，但共享同一个 ASGI app/服务。"""
    def _make() -> TestClient:
        return TestClient(app)
    return _make


def _scene(nodeid: str) -> str:
    module = nodeid.split("::", 1)[0].split("/")[-1].removesuffix(".py")
    return _SCENE_TITLES.get(module, module)


def pytest_runtest_logstart(nodeid, location):  # type: ignore[no-untyped-def]
    scenario_logger.info("【%s】开始用例: %s", _scene(nodeid), nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()
    if call.when == "call":
        if report.passed:
            scenario_logger.info("【%s】用例结果: %s -> PASS", _scene(item.nodeid), item.name)
        elif report.failed:
            reason = call.excinfo.exconly() if call.excinfo else "unknown"
            scenario_logger.error("【%s】用例结果: %s -> FAIL: %s",
                                  _scene(item.nodeid), item.name, reason)


def pytest_terminal_summary(terminalreporter):  # type: ignore[no-untyped-def]
    terminalreporter.write_sep("=", "场景覆盖汇总")
    for file_name, title in _SCENE_TITLES.items():
        stats = terminalreporter.stats
        cases = [
            r for key in ("passed", "failed", "error", "skipped")
            for r in stats.get(key, [])
            if r.nodeid.startswith(f"tests/{file_name}.py::")
        ]
        if not cases:
            continue
        passed = sum(1 for r in cases if r.passed)
        failed = sum(1 for r in cases if r.failed)
        skipped = sum(1 for r in cases if r.skipped)
        names = ", ".join(r.nodeid.split("::")[-1] for r in cases)
        terminalreporter.write_line(
            f"{title}: 共 {len(cases)} 个用例（通过 {passed}, 失败 {failed}, 跳过 {skipped}）"
        )
        terminalreporter.write_line(f"  用例: {names}")
