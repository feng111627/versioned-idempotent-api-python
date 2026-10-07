"""请求/响应数据模型。"""

from pydantic import BaseModel, Field


class DocumentIn(BaseModel):
    """文档写入请求体（v1 与 v2 共用）。"""

    title: str = Field(default="")
    content: str = Field(default="")
