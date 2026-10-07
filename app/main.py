"""FastAPI 应用入口。"""

from fastapi import FastAPI

from app.errors import register_exception_handlers
from app.routers import v1, v2, version_guard


def create_app() -> FastAPI:
    app = FastAPI(
        title="Versioned Idempotent API",
        version="2.0.0",
        description="带版本演进与幂等保障的写入示例服务。",
    )
    app.include_router(v2.router)
    app.include_router(v1.router)
    app.include_router(version_guard.router)
    register_exception_handlers(app)
    return app


app = create_app()
