"""
Database module for Whop embedded app.

Provides async database connectivity using SQLAlchemy async engine.
This module is optional - the app can work without a database by
relying solely on Whop API for data.

When to use a database:
- Caching subscription status to reduce API calls
- Storing custom user data beyond Whop's scope
- Tracking usage metrics or analytics
- Implementing rate limiting or quotas
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


# Global engine and session factory
# Initialized lazily when database is first accessed
_engine = None
_async_session_factory = None


def get_engine():
    """
    Get or create the async database engine.

    Returns:
        AsyncEngine: SQLAlchemy async engine

    Raises:
        ValueError: If DATABASE_URL is not configured
    """
    global _engine

    if _engine is None:
        if not settings.DATABASE_URL:
            raise ValueError(
                "DATABASE_URL not configured. "
                "Set DATABASE_URL in .env or disable database features."
            )

        # Convert sync URL to async if needed
        # e.g., postgresql:// -> postgresql+asyncpg://
        db_url = settings.DATABASE_URL
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("sqlite://"):
            db_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)

        _engine = create_async_engine(
            db_url,
            echo=settings.DEV_MODE,  # Log SQL in dev mode
            pool_pre_ping=True,  # Verify connections before use
        )

        logger.info("Database engine created")

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get or create the async session factory.

    Returns:
        async_sessionmaker: Factory for creating async sessions
    """
    global _async_session_factory

    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # Allow access to objects after commit
        )

    return _async_session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session as an async context manager.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(query)

    Yields:
        AsyncSession: Database session

    Note:
        Session is automatically closed after context exits.
        Rollback is performed on exceptions.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Usage:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...

    Yields:
        AsyncSession: Database session
    """
    async with get_db_session() as session:
        yield session


async def init_db() -> None:
    """
    Initialize database tables.

    Creates all tables defined in models that inherit from Base.
    Should be called during application startup.
    """
    if not settings.DATABASE_URL:
        logger.info("DATABASE_URL not set, skipping database initialization")
        return

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables created")


async def close_db() -> None:
    """
    Close database connections.

    Should be called during application shutdown.
    """
    global _engine, _async_session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
        logger.info("Database connections closed")


def is_database_configured() -> bool:
    """
    Check if database is configured.

    Returns:
        bool: True if DATABASE_URL is set
    """
    return bool(settings.DATABASE_URL)
