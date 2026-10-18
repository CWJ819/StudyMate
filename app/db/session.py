from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import Engine as SAEngine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_ENGINES: dict[str, Engine] = {}


def _sqlite_connect_args(database_url: str) -> dict[str, bool]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


@lru_cache(maxsize=8)
def _build_engine(database_url: str) -> Engine:
    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=_sqlite_connect_args(database_url),
    )
    _ENGINES[database_url] = engine
    return engine


@event.listens_for(SAEngine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine() -> Engine:
    return _build_engine(get_settings().database_url)


@lru_cache(maxsize=8)
def _build_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=_build_engine(database_url),
        autoflush=False,
        autocommit=False,
        future=True,
    )


def get_session_factory() -> sessionmaker[Session]:
    return _build_session_factory(get_settings().database_url)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def dispose_engine() -> None:
    for engine in _ENGINES.values():
        engine.dispose()


def reset_session_state() -> None:
    dispose_engine()
    _ENGINES.clear()
    _build_session_factory.cache_clear()
    _build_engine.cache_clear()
