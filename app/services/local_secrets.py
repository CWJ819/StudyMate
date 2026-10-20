"""本机保存的 LLM 凭据（单用户本地产品）。

产品最终在用户自己的机器上运行，所以设置页允许输入 API Key。密钥有意不放进
SQLite 的 settings 普通设置表，也不经接口或日志返回：

* 存放在 SQLite 数据库同目录的 ``local_secrets.json``（尽量收紧到 0600）；
* 只有 LLM 适配器和“是否已配置”的判断会读它；
* ``GET /api/settings`` 只返回 ``llm_auth_configured`` / ``llm_api_key_source``。

环境变量 ``LLM_API_KEY`` 仍然支持，作为兜底；设置页保存的 Key 优先。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SECRETS_FILENAME = "local_secrets.json"
_API_KEY_FIELD = "llm_api_key"
_SQLITE_PREFIXES = ("sqlite+pysqlite:///", "sqlite:///")


def _database_directory() -> Path | None:
    """SQLite 数据库所在目录；非文件型数据库返回 None。"""
    database_url = get_settings().database_url
    for prefix in _SQLITE_PREFIXES:
        if not database_url.startswith(prefix):
            continue
        raw_path = database_url[len(prefix) :].split("?", 1)[0]
        if not raw_path or raw_path == ":memory:":
            return None
        database_path = Path(raw_path)
        if not database_path.is_absolute():
            database_path = Path.cwd() / database_path
        return database_path.parent
    return None


def local_secrets_path() -> Path:
    """密钥文件路径：默认跟数据库同目录，便于随 ``data/`` 一起持久化。"""
    override = os.environ.get("LOCAL_SECRETS_PATH")
    if override:
        return Path(override).expanduser()
    directory = _database_directory()
    if directory is not None:
        return directory / SECRETS_FILENAME
    return Path.cwd() / "data" / SECRETS_FILENAME


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        logger.warning("Local secrets file is not readable; ignoring it.")
        return {}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Local secrets file is not valid JSON; ignoring it.")
        return {}
    return payload if isinstance(payload, dict) else {}


def read_local_api_key() -> str | None:
    value = _read_payload(local_secrets_path()).get(_API_KEY_FIELD)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def write_local_api_key(api_key: str | None) -> None:
    """保存或清除本机 Key；空值表示清除。文件内容不会写日志。"""
    path = local_secrets_path()
    payload = _read_payload(path)
    value = (api_key or "").strip()
    if value:
        payload[_API_KEY_FIELD] = value
    else:
        payload.pop(_API_KEY_FIELD, None)

    if not payload:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".local-secrets-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
