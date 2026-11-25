"""FastAPI application entry point for the Employee Management module.

Run locally from the repository root:
    python -m uvicorn employee_mgmt.app:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import (
    attendance,
    complaints,
    health,
    leave,
    policies,
    tickets,
    training,
)
from .core.config import settings
from .db.base import Base
from .db.session import engine
from .services import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceError,
    ValidationError,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize database tables on application startup."""
    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    application = FastAPI(
        title=getattr(settings, "APP_NAME", "Employee Management API"),
        version=getattr(settings, "APP_VERSION", "1.0.0"),
        lifespan=lifespan,
    )

    # Allow local Vite frontend to communicate with the FastAPI backend.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Map domain service exceptions to HTTP responses.
    @application.exception_handler(NotFoundError)
    async def handle_not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": exc.detail, "code": exc.code})

    @application.exception_handler(ForbiddenError)
    async def handle_forbidden(_request: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": exc.detail, "code": exc.code})

    @application.exception_handler(ConflictError)
    async def handle_conflict(_request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": exc.detail, "code": exc.code})

    @application.exception_handler(ValidationError)
    async def handle_validation(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.detail, "code": exc.code})

    @application.exception_handler(ServiceError)
    async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": exc.detail, "code": exc.code})

    # Register API v1 routers.
    api_prefix = "/api/v1"
    application.include_router(health.router, prefix=api_prefix)
    application.include_router(policies.router, prefix=api_prefix)
    application.include_router(leave.router, prefix=api_prefix)
    application.include_router(attendance.router, prefix=api_prefix)
    application.include_router(tickets.router, prefix=api_prefix)
    application.include_router(training.router, prefix=api_prefix)
    application.include_router(complaints.router, prefix=api_prefix)

    @application.get("/", tags=["root"])
    def root() -> dict[str, str]:
        return {
            "service": "employee_mgmt",
            "status": "running",
            "docs": "/docs",
        }

    return application


app = create_app()