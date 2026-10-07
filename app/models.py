"""对外/内部使用的数据模型（骨架）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ItemWriteV1(BaseModel):
    value: str | None = None
    expected_version: int | None = Field(default=None, ge=1)


class ItemWriteV2(BaseModel):
    name: str | None = None
    data: dict = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)


class ItemReadV1(BaseModel):
    id: str
    value: str
    version: int


class ItemReadV2(BaseModel):
    id: str
    name: str
    data: dict
    version: int


class ErrorBody(BaseModel):
    error: str
    code: str
    message: str
    details: dict | None = None
