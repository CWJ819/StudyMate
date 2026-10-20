from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models.llm import LLMCallLog


class LLMRepository:
    def add_call_log(
        self,
        session: Session,
        *,
        operation: str,
        provider: str,
        model_name: str,
        prompt_version: str,
        status: str,
        attempt_count: int = 1,
        duration_ms: int | None = None,
        error_code: str | None = None,
        course_id: str | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
    ) -> LLMCallLog:
        log = LLMCallLog(
            course_id=course_id,
            operation=operation,
            provider=provider,
            model_name=model_name,
            prompt_version=prompt_version,
            status=status,
            attempt_count=attempt_count,
            duration_ms=duration_ms,
            error_code=error_code,
            input_summary_json=input_summary or {},
            output_summary_json=output_summary or {},
        )
        session.add(log)
        session.flush()
        return log
