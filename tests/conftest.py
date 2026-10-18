from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import reset_settings_cache
from app.db.session import reset_session_state


@pytest.fixture
def migrated_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    database_path = tmp_path / "test.db"
    database_url = f"sqlite:///{database_path}"

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "uploads"))
    reset_settings_cache()
    reset_session_state()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    yield database_url

    reset_session_state()
    reset_settings_cache()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
