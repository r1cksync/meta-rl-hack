"""SQLAlchemy async database setup for payments-api."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/acmecorp",
)
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))

engine = create_async_engine(
    DATABASE_URL,
    pool_size=DB_POOL_SIZE,
    echo=os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG",
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create tables if they don't exist."""
    from .models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
