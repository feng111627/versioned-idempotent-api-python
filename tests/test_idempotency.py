"""场景：写入幂等与并发重复提交（骨架）。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="骨架阶段，待实现")


def test_same_key_same_content_applies_once():
    ...


def test_same_key_different_content_rejected():
    ...


def test_concurrent_duplicates_apply_once():
    ...


def test_replay_returns_consistent_result():
    ...
