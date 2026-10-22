from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from app.core.errors import AppError
from app.llm.schemas import LLMStructuredResult


class LLMTemporaryError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class LLMConfiguredError(AppError):
    pass


class LLMAdapter(ABC):
    @abstractmethod
    def ensure_available(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def generate_structured_output(
        self,
        *,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[BaseModel],
        timeout_seconds: int | None = None,
    ) -> LLMStructuredResult:
        raise NotImplementedError
