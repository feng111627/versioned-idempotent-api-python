"""场景：资源版本与乐观并发控制（骨架）。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="骨架阶段，待实现")


def test_read_carries_version():
    ...


def test_write_advances_version():
    ...


def test_stale_version_rejected_not_overwritten():
    ...


def test_missing_version_distinguishable():
    ...


def test_not_found_distinguishable():
    ...
