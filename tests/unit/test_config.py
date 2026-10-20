from app.core.config import get_settings


def test_settings_default_to_local_bind_friendly_configuration() -> None:
    settings = get_settings()
    assert settings.database_url.startswith("sqlite")
    # 用 Path.parts 避免 Windows 的 "data\\uploads" 与 POSIX 的 "data/uploads" 断言差异。
    assert settings.storage_root.parts[0] == "data"

