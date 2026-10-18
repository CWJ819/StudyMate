from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import AppError


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    size_bytes: int
    absolute_path: Path


class LocalStorage:
    def __init__(self) -> None:
        self.root = Path(get_settings().storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp_root = self.root / ".tmp"
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, *, suffix: str, data: bytes) -> StoredFile:
        storage_key = f"documents/{uuid4().hex}{suffix.lower()}"
        destination = self.resolve_path(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        temp_path = self.temp_root / f"{uuid4().hex}.upload"
        temp_path.write_bytes(data)
        temp_path.replace(destination)
        return StoredFile(
            storage_key=storage_key,
            size_bytes=len(data),
            absolute_path=destination,
        )

    def delete(self, storage_key: str) -> None:
        path = self.resolve_path(storage_key)
        if path.exists():
            path.unlink()

    def resolve_path(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise AppError(
                code="INVALID_STORAGE_PATH",
                message="The requested storage path is invalid.",
                status_code=400,
            )
        return candidate
