from app.core.config import get_settings


def test_settings_default_to_local_bind_friendly_configuration() -> None:
    settings = get_settings()
    assert settings.database_url.startswith("sqlite")
    assert str(settings.storage_root).startswith("data/")

