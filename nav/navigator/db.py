from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> None:
    global _engine, _sessionmaker

    engine_kwargs = {"pool_pre_ping": True}
    if not settings.database_url.startswith("sqlite"):
        # Postgres: explicit pool so N replicas × pool_size stays
        # below Postgres's max_connections. Recycle before Postgres's
        # idle timeout can drop a connection out from under us.
        engine_kwargs.update(
            pool_size=5,
            max_overflow=5,
            pool_recycle=1800,
            pool_timeout=30,
        )

    _engine = create_async_engine(settings.database_url, **engine_kwargs)

    if settings.database_url.startswith("sqlite"):
        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

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