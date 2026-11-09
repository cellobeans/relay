from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# One engine per process: it owns the connection pool shared by all requests.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)

# expire_on_commit=False so objects stay readable after commit (we often return them in responses).
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    async with SessionLocal() as session:
        yield session


# Shorthand used in route signatures: `session: SessionDep`.
SessionDep = Annotated[AsyncSession, Depends(get_session)]
