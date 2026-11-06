from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> None:
    global _engine, _sessionmaker

    # Postgres-only. Pool sizing assumes N replicas × pool_size stays
    # below Postgres's max_connections; pool_recycle runs before
    # Postgres's idle timeout can drop a connection out from under us.
    _engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        pool_timeout=30,
    )

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    assert _sessionmaker is not None, "init_engine() not called"
    async with _sessionmaker() as session:
        yield session


def get_engine():
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    assert _sessionmaker is not None, "init_engine() not called"
    return _sessionmaker