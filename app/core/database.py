"""
Database connection and session management.
Provides async session factory for SQLAlchemy operations.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# Convert sync URL to async (postgresql:// -> postgresql+asyncpg://)
async_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(async_url, echo=settings.debug)

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield database session for dependency injection."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
