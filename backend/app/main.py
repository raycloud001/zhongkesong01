import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.routes import router as auth_router
from app.auth.service import AuthError
from app.assessment.routes import router as assessment_router
from app.reports.routes import router as reports_router
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.seed.official import import_official_evidence


request_logger = logging.getLogger("career_assessment.requests")


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "requestId": request_id,
                "details": details or {},
            }
        },
        headers={"X-Request-ID": request_id},
    )


def default_static_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(static_dir: str | Path | None = None, api_router: APIRouter | None = None) -> FastAPI:
    app = FastAPI(title="Career Assessment API", version="0.1.0")

    @app.on_event("startup")
    async def initialize_local_database() -> None:
        # Keep a fresh local checkout runnable without a separate seed command.
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            from sqlalchemy import select
            from app.models import VersionPointer
            if db.scalar(select(VersionPointer).where(VersionPointer.kind == "question")) is None:
                root = Path(__file__).resolve().parents[1]
                asset = root / "seed" / "official-questionnaire.json"
                source = root / "seed" / "sources" / "题目与AI报告生成规则.md"
                if asset.is_file() and source.is_file():
                    import json
                    import_official_evidence(db, json.loads(asset.read_text()), source_path=source, activate=True)
                    db.commit()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            request_logger.error(
                json.dumps(
                    {"event": "request.failed", "method": request.method, "path": request.url.path, "requestId": request_id},
                    separators=(",", ":"),
                )
            )
            response = error_response(
                request,
                status_code=500,
                code="INTERNAL_ERROR",
                message="Internal server error",
            )
        response.headers["X-Request-ID"] = request_id
        request_logger.info(
            json.dumps(
                {
                    "event": "request.completed",
                    "method": request.method,
                    "path": request.url.path,
                    "statusCode": response.status_code,
                    "requestId": request_id,
                },
                separators=(",", ":"),
            )
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"location": list(error["loc"]), "type": error["type"]}
            for error in exc.errors()
        ]
        return error_response(
            request,
            status_code=422,
            code="INPUT_INVALID",
            message="Input validation failed",
            details={"fields": fields},
        )

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return error_response(
                request,
                status_code=404,
                code="NOT_FOUND",
                message="Resource not found",
            )
        return error_response(
            request,
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message="Request failed",
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(assessment_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")

    if api_router is not None:
        app.include_router(api_router, prefix="/api/v1")

    resolved_static_dir = Path(static_dir) if static_dir is not None else default_static_dir()
    resolved_static_dir = resolved_static_dir.resolve()
    assets_dir = resolved_static_dir / "assets"

    @app.get("/assets/{asset_path:path}", include_in_schema=False)
    async def static_asset(asset_path: str, request: Request):
        candidate = (assets_dir / asset_path).resolve()
        if not candidate.is_relative_to(assets_dir) or not candidate.is_file():
            return error_response(request, status_code=404, code="NOT_FOUND", message="Resource not found")
        return FileResponse(candidate)

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa(spa_path: str, request: Request):
        if spa_path == "api" or spa_path.startswith("api/"):
            return error_response(request, status_code=404, code="NOT_FOUND", message="Resource not found")
        index = resolved_static_dir / "index.html"
        if not index.is_file():
            return error_response(request, status_code=404, code="NOT_FOUND", message="Resource not found")
        return FileResponse(index)

    return app

app = create_app()
