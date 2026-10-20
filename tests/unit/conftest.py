import pytest


@pytest.fixture(autouse=True)
def _no_llm_runtime_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """单测不读数据库里的 settings 覆盖，也不读写真实的本机密钥文件。"""
    from app.llm import openai_compatible

    monkeypatch.setattr(openai_compatible, "read_llm_runtime_overrides", lambda: {})
    monkeypatch.setenv("LOCAL_SECRETS_PATH", str(tmp_path / "local_secrets.json"))
