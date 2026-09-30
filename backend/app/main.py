"""
erpFusion — FastAPI Application Entrypoint

Configures the FastAPI app with CORS, route registration,
lifespan events (DB table creation for dev), and health check.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import artifacts, erp_profiles, feedback, generation, projects, reviews
from app.config import get_settings
from app.database import engine
from app.models import Base
from app.services.erp_registry import ensure_seed_profiles

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("erpfusion")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events.

    On startup: create all tables if in development mode (for quick iteration).
    In production, tables are managed by Alembic migrations.
    """
    if settings.is_development:
        logger.info("Development mode — creating database tables if needed")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if engine.dialect.name == "sqlite":
                from app.dev_sqlite_migrations import migrate_legacy_sqlite
                await conn.run_sync(migrate_legacy_sqlite)
        from app.database import async_session_factory

        async with async_session_factory() as session:
            await ensure_seed_profiles(session)
            await session.commit()
        if engine.dialect.name == "sqlite":
            async with engine.begin() as conn:
                from app.dev_sqlite_migrations import migrate_legacy_sqlite
                await conn.run_sync(migrate_legacy_sqlite)

    logger.info("erpFusion backend started")
    yield

    await engine.dispose()
    logger.info("erpFusion backend shutdown")


# ── App Factory ───────────────────────────────────────────────

app = FastAPI(
    title="erpFusion API",
    description=(
        "AI ERP Integration Engineering Agent — "
        "Converts business integration requirements and ERP schema/context "
        "into a complete, reviewable, version-controlled integration engineering package."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register Routers ─────────────────────────────────────────

app.include_router(projects.router)
app.include_router(artifacts.router)
app.include_router(reviews.router)
app.include_router(generation.router)
app.include_router(erp_profiles.router)
app.include_router(feedback.router)


# ── Health Check ──────────────────────────────────────────────


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "erpfusion-backend",
        "version": "0.1.0",
    }


@app.get("/", tags=["System"])
async def root():
    """Root endpoint with API info."""
    return {
        "service": "erpFusion API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
