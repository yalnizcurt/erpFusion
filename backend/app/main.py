"""Application construction and read-only process health endpoints.

Schema migrations and fixture loading are explicit administration commands.
Starting an API process never creates tables, upgrades data, or publishes profiles.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api import (
    artifacts,
    clients,
    connections,
    erp_profiles,
    executions,
    feedback,
    generation,
    identity,
    identity_admin,
    integration_patterns,
    packages,
    projects,
    requirements,
    reviews,
)
from app.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.readiness import ReadinessCheck, check_readiness
from app.database import create_database_engine, get_db

logger = logging.getLogger("erpfusion")
APPLICATION_VERSION = "0.1.0"


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    session_dependency: Callable[..., Any] | None = None,
) -> FastAPI:
    """Create an isolated application, with optional test-owned database resources.

    Database engines are lazy: process startup and liveness do not connect to a
    database. An externally supplied engine belongs to its caller and is never
    disposed by the application.
    """
    configuration = settings if settings is not None else get_settings()
    configure_logging(configuration)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if configuration.is_production and configuration.configuration_issues():
            raise RuntimeError(
                "Production configuration is not ready; inspect safe readiness codes"
            )
        logger.info("HighStudio backend started")
        try:
            yield
        finally:
            runtime_engine = application.state.database_engine
            if runtime_engine is not None and application.state.owns_database_engine:
                await runtime_engine.dispose()
            logger.info("HighStudio backend shutdown")

    application = FastAPI(
        title="HighStudio API",
        description=(
            "AI ERP Integration Engineering Agent — Converts business integration "
            "requirements and ERP schema/context into a reviewable, versioned "
            "integration engineering package."
        ),
        version=APPLICATION_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    application.state.settings = configuration
    application.state.database_engine = engine
    application.state.owns_database_engine = engine is None
    application.dependency_overrides[get_settings] = lambda: configuration
    if session_dependency is not None:
        application.dependency_overrides[get_db] = session_dependency

    application.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        projects.router,
        artifacts.router,
        reviews.router,
        generation.router,
        erp_profiles.router,
        feedback.router,
        clients.router,
        identity.router,
        identity_admin.router,
        connections.router,
        requirements.router,
        packages.router,
        executions.router,
        integration_patterns.router,
    ):
        application.include_router(router)

    @application.get("/health", tags=["System"])
    @application.get("/health/live", tags=["System"])
    async def liveness() -> dict[str, str]:
        """Process liveness is independent of external service availability."""
        return {
            "status": "alive",
            "service": "erpfusion-backend",
            "version": APPLICATION_VERSION,
        }

    @application.get("/health/ready", tags=["System"])
    async def readiness() -> JSONResponse:
        """Check configuration, database/schema, and provisioned artifact storage."""
        # Invalid configuration is reported before trying to create an engine.
        runtime_engine = application.state.database_engine
        try:
            if runtime_engine is None and not configuration.configuration_issues():
                runtime_engine = create_database_engine(configuration)
                application.state.database_engine = runtime_engine
        except (SQLAlchemyError, ImportError, ValueError, OSError):
            result = await check_readiness(configuration, None)
            result.checks["database"] = ReadinessCheck(
                status="fail", codes=["database_runtime_invalid"]
            )
        else:
            result = await check_readiness(configuration, runtime_engine)
        return JSONResponse(
            content=result.model_dump(),
            status_code=200 if result.status == "ready" else 503,
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/", tags=["System"])
    async def root() -> dict[str, str]:
        return {
            "service": "HighStudio API",
            "version": APPLICATION_VERSION,
            "docs": "/docs",
            "health": "/health/live",
            "readiness": "/health/ready",
        }

    return application


app = create_app()
