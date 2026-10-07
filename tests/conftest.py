"""测试基础设施：

* 每个用例通过 ``@pytest.mark.scenario(...)`` 归属一个“场景”；
* 运行结束后打印「场景覆盖清单」，列出场景、用例与各自结果；
* 每个用例执行时实时输出用例与结果行（``-s`` 已在 pytest.ini 默认开启）。
"""

from collections import OrderedDict

import pytest

# nodeid -> (场景名, 场景说明, 用例名)
_SCENARIO_INDEX: dict[str, tuple[str, str, str]] = {}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "scenario(name, desc): 用例所属场景名称与说明"
    )


def _scenario_of(item: pytest.Item) -> tuple[str, str]:
    marker = item.get_closest_marker("scenario")
    if marker is None:
        return "未分类", ""
    name = marker.args[0] if marker.args else marker.kwargs.get("name", "未分类")
    desc = marker.kwargs.get("desc", "")
    if not desc and len(marker.args) > 1:
        desc = marker.args[1]
    return name, desc


def pytest_runtest_setup(item: pytest.Item) -> None:
    name, desc = _scenario_of(item)
    _SCENARIO_INDEX[item.nodeid] = (name, desc, item.name)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or (
        report.when in ("setup", "teardown") and report.failed
    ):
        name, _, _ = _SCENARIO_INDEX.get(report.nodeid, ("未分类", "", report.nodeid))
        print(f"[{report.outcome.upper():<7}] 场景[{name}] {report.nodeid}")


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    scenarios: "OrderedDict[str, dict]" = OrderedDict()
    for key, outcome in (
        ("passed", "PASSED"),
        ("failed", "FAILED"),
        ("error", "ERROR"),
        ("skipped", "SKIPPED"),
    ):
        for report in terminalreporter.stats.get(key, []):
            name, desc, case_name = _SCENARIO_INDEX.get(
                report.nodeid, ("未分类", "", report.nodeid)
            )
            bucket = scenarios.setdefault(
                name, {"desc": desc, "cases": []}
            )
            if desc and not bucket["desc"]:
                bucket["desc"] = desc
            bucket["cases"].append((case_name, outcome))

    write = terminalreporter.write_line
    write("")
    write("=" * 78)
    write("场景覆盖清单（Scenario Coverage）")
    write("=" * 78)
    total = 0
    for idx, (name, data) in enumerate(scenarios.items(), start=1):
        total += len(data["cases"])
        write(f"{idx:>2}. 场景: {name}")
        if data["desc"]:
            write(f"    说明: {data['desc']}")
        for case_name, outcome in data["cases"]:
            write(f"      - [{outcome:<7}] {case_name}")
    write("-" * 78)
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    write(
        f"共覆盖 {len(scenarios)} 个场景、{total} 个用例；"
        f"通过 {passed}，失败 {failed}"
    )
    write("=" * 78)


@pytest.fixture()
def client():
    """每个用例使用全新存储，避免用例间状态泄漏。"""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.store import store

    store._resources.clear()
    store._idempotency.clear()
    store._key_locks.clear()
    with TestClient(app) as c:
        yield c
