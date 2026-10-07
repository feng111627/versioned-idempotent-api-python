"""HTTP 路由：v1（弃用）与 v2，以及未识别版本的显式报错（骨架）。"""
from __future__ import annotations

from fastapi import FastAPI

from app.errors import APIError
from app.service import ItemService


def create_app(service: ItemService | None = None) -> FastAPI:
    ...
