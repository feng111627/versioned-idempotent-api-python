"""对外 API 版本定义（骨架）。"""
from __future__ import annotations

from enum import Enum


class APIVersion(str, Enum):
    V1 = "v1"
    V2 = "v2"


SUPPORTED_VERSIONS = tuple(v.value for v in APIVersion)
DEPRECATED_VERSIONS = frozenset({APIVersion.V1.value})


def parse_api_version(raw: str) -> APIVersion:
    ...


def is_deprecated(version: APIVersion) -> bool:
    ...
