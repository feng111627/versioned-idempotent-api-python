"""API 版本相关常量与工具：弃用标记、不受支持版本处理。

版本通过 URL 前缀区分（``/api/v1``、``/api/v2``）。未出现在
``SUPPORTED_VERSIONS`` 中的版本一律返回 ``version_not_supported``，
不会默认回落到任一版本。
"""

from app.errors import error_body

V1_PREFIX = "/api/v1"
V2_PREFIX = "/api/v2"
SUPPORTED_VERSIONS = ("1", "2")

_DEPRECATION_LINK = (
    '</api/v2/documents/{id}>; rel="successor-version"'
)


def v1_deprecation_headers() -> dict[str, str]:
    """v1 入口的弃用标记响应头。

    使用 RFC 8594 的 ``Deprecation`` 头，并通过 ``Sunset``/``Link``
    指明继任版本，客户端可以程序化地感知弃用。
    """
    return {
        "Deprecation": "true",
        "Sunset": 'Sat, 31 Dec 2026 23:59:59 GMT',
        "Link": _DEPRECATION_LINK,
        "X-Api-Deprecated": "v1; successor=v2",
    }


def unsupported_version_body(version: str) -> dict[str, dict[str, str]]:
    """不受支持版本的统一错误体。"""
    return error_body(
        "version_not_supported",
        f"API 版本 {version!r} 不受支持；支持的版本：1（已弃用）、2",
    )
