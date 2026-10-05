"""Lazy database construction with application-scoped, injectable sessions."""

import ssl
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Construct a runtime engine without connecting, DDL, or parameter logging."""
    return _create_engine_for_url(settings.database_url, settings.database_ssl_ca_file)


def _create_engine_for_url(database_url: str, ssl_ca_file: str = "") -> AsyncEngine:
    if database_url.startswith("sqlite"):
        return create_async_engine(
            database_url, echo=False, hide_parameters=True, pool_pre_ping=True
        )
    return create_async_engine(
        database_url,
        echo=False,
        hide_parameters=True,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={"ssl": ssl.create_default_context(cafile=ssl_ca_file)} if ssl_ca_file else {},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@lru_cache
def _cached_engine(database_url: str, ssl_ca_file: str = "") -> AsyncEngine:
    return _create_engine_for_url(database_url, ssl_ca_file)


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Lazy default runtime for explicit tooling; HTTP apps own their own engine."""
    configuration = settings or get_settings()
    return _cached_engine(configuration.database_url, configuration.database_ssl_ca_file)


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(get_engine(settings))


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Use injected app state; each request has one commit/rollback boundary."""
    engine = getattr(request.app.state, "database_engine", None)
    if engine is None:
        engine = create_database_engine(request.app.state.settings)
        request.app.state.database_engine = engine
        request.app.state.owns_database_engine = True
    factory = create_session_factory(engine)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
