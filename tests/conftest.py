"""共享夹具与场景日志（骨架）。"""
from __future__ import annotations

import logging

import pytest

from app.api import create_app
from app.service import ItemService


@pytest.fixture
def service() -> ItemService:
    return ItemService()


@pytest.fixture
def client(service):
    from fastapi.testclient import TestClient

    return TestClient(create_app(service))
