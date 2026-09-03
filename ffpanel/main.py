from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import router
from .auth import BasicAuthMiddleware
from .config import Settings, get_settings
from .db import Base, create_db_engine, create_session_factory
from .events import EventBus
from .process_lock import ProcessLock
from .scheduler import Scheduler
from .storage import ScanRegistry, StorageError, StorageService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_directories()
        lock = ProcessLock(settings.config_dir / "ffpanel.lock")
        lock.acquire()
        engine = create_db_engine(settings.db_url)
        Base.metadata.create_all(engine)
        sessions = create_session_factory(engine)
        events = EventBus()
        storage = StorageService(settings)
        scheduler = Scheduler(settings, sessions, storage, events)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessions = sessions
        app.state.events = events
        app.state.storage = storage
        app.state.scans = ScanRegistry(settings.scan_ttl_seconds)
        app.state.scheduler = scheduler
        await scheduler.start()
        try:
            yield
        finally:
            await scheduler.shutdown()
            engine.dispose()
            lock.release()

    app = FastAPI(
        title="FFPanel API",
        version=__version__,
        description="RK3588 批量视频转码控制面板",
        lifespan=lifespan,
    )
    app.add_middleware(BasicAuthMiddleware, settings=settings)
    app.include_router(router)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.exception_handler(StorageError)
    async def storage_error(request: Request, exc: StorageError) -> JSONResponse:
        return error_response(request, 409 if exc.code in {"output_conflict", "scan_mismatch", "scan_expired"} else 422, exc.code, str(exc), exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", "http_error"))
            message = str(exc.detail.get("message", "请求未完成"))
            details = exc.detail.get("details")
        else:
            code = "not_found" if exc.status_code == 404 else "http_error"
            message = str(exc.detail)
            details = None
        return error_response(request, exc.status_code, code, message, details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "validation_error", "请求参数不合法", exc.errors())

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logging.getLogger("ffpanel").exception("database operation failed")
        return error_response(request, 503, "database_unavailable", "任务数据库暂时不可用")

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            candidate = (static_dir / full_path).resolve()
            if candidate.is_file() and static_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response_headers = {"X-Request-ID": request_id, **(headers or {})}
    return JSONResponse(status_code=status, content={"code": code, "message": message, "details": details, "requestId": request_id}, headers=response_headers)


app = create_app()
