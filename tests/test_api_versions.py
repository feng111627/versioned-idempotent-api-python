"""场景：对外 API 版本演进与跨版本一致性（骨架）。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="骨架阶段，待实现")


def test_v1_marked_deprecated_but_usable():
    ...


def test_v2_full_shape():
    ...


def test_cross_version_state_consistent():
    ...


def test_unknown_version_explicit_error():
    ...
