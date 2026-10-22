"""Stage B 调度回归测试：有界提交、预算不足不发请求、根因错误码、成功进度。

这些用例不连数据库（repository 用桩，进度 reporter 无 job_id），直接驱动
KnowledgeBuildPipeline._extract_windows。
"""

from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.llm.schemas import (
    KnowledgeSectionExtractionV5,
    LLMRunSummary,
    LLMStructuredResult,
)
from app.services.knowledge_pipeline import (
    SECTION_EXTRACT_CONCURRENCY,
    BuildBudget,
    BuildDiagnostics,
    KnowledgeBuildPipeline,
    ProgressReporter,
    SectionWindow,
)


class _StubRepository:
    def __init__(self, cached: dict[str, dict] | None = None) -> None:
        self.cached = cached or {}

    def get_section_cache_payloads(self, session, *, cache_keys):
        return {
            key: payload for key, payload in self.cached.items() if key in cache_keys
        }


def _window(index: int) -> SectionWindow:
    return SectionWindow(
        window_index=index,
        chapter_index=1,
        section_index=0,
        section_path=["第1章 数据结构基础"],
        page_ranges=[("doc", index, index)],
        units=[],
        content_hash=f"hash-{index}",
        cache_key=f"cache-{index}",
        payload={
            "section_path": ["第1章 数据结构基础"],
            "page_range": [index, index],
            "max_leaves": 10,
            "source_segments": [
                {
                    "document_id": "doc",
                    "chunk_id": None,
                    "page_start": index,
                    "page_end": index,
                    "text": f"第 {index} 页的正文内容，足够长以通过叶子质量过滤。",
                }
            ],
        },
    )


def _pipeline(cached: dict[str, dict] | None = None) -> KnowledgeBuildPipeline:
    pipeline = KnowledgeBuildPipeline(repository=_StubRepository(cached))
    pipeline._persist_section_cache = lambda outcome: None  # type: ignore[method-assign]
    pipeline._persist_window_call = lambda job_id, outcome: None  # type: ignore[method-assign]
    return pipeline


def _valid_extraction(payload: dict) -> KnowledgeSectionExtractionV5:
    segment = payload["source_segments"][0]
    return KnowledgeSectionExtractionV5(
        section_ref="section",
        leaves=[
            {
                "ref": "leaf_1",
                "title": "知识点一",
                "content": "足够长的解释内容，用于通过叶子质量过滤。",
                "sources": [
                    {
                        "document_id": segment["document_id"],
                        "page_number": segment["page_start"],
                        "chunk_id": segment["chunk_id"],
                        "evidence_type": "page_excerpt",
                    }
                ],
            }
        ],
    )


class _FailingAdapter:
    """每个调用都立即失败；用于验证有界提交与 fail-fast。"""

    def __init__(self, error: AppError) -> None:
        self.error = error
        self.calls = 0

    def ensure_available(self) -> None:
        return None

    def generate_structured_output(self, **kwargs) -> LLMStructuredResult:
        self.calls += 1
        raise self.error


class _NeverCalledAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def generate_structured_output(self, **kwargs) -> LLMStructuredResult:
        self.calls += 1
        raise AssertionError("no request may be started without budget")


class _CountingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def generate_structured_output(self, **kwargs) -> LLMStructuredResult:
        self.calls += 1
        return LLMStructuredResult(
            summary=LLMRunSummary(
                model_name="fake-model",
                prompt_version=kwargs["prompt_version"],
                provider="fake",
            ),
            data=_valid_extraction(kwargs["user_payload"]),
        )


def test_submission_is_bounded_and_fails_fast() -> None:
    windows = [_window(index) for index in range(1, 11)]
    adapter = _FailingAdapter(
        AppError(code="LLM_TIMEOUT", message="LLM request timed out.", status_code=502)
    )
    diagnostics = BuildDiagnostics()

    with pytest.raises(AppError) as excinfo:
        _pipeline()._extract_windows(
            None, adapter, windows, ProgressReporter(None), None, diagnostics
        )

    assert excinfo.value.code == "LLM_TIMEOUT"
    # 只提交一个并发窗口，不会把 10 个任务都塞进线程池
    assert adapter.calls == SECTION_EXTRACT_CONCURRENCY
    assert diagnostics.failed_units == SECTION_EXTRACT_CONCURRENCY
    assert diagnostics.skipped_units == 0
    assert diagnostics.cancelled_units == len(windows) - SECTION_EXTRACT_CONCURRENCY
    assert diagnostics.succeeded_units == 0
    assert diagnostics.terminal_reason == "LLM_TIMEOUT"


def test_exhausted_budget_stops_before_any_request() -> None:
    windows = [_window(index) for index in range(1, 11)]
    adapter = _NeverCalledAdapter()
    diagnostics = BuildDiagnostics()
    # 50s 截止 - 10s 收尾预留 = 40s < 45s 最小窗口
    budget = BuildBudget(deadline_seconds=50, clock=lambda: 0.0)

    with pytest.raises(AppError) as excinfo:
        _pipeline()._extract_windows(
            None,
            adapter,
            windows,
            ProgressReporter(None),
            None,
            diagnostics,
            budget=budget,
        )

    assert excinfo.value.code == "JOB_DEADLINE_EXCEEDED"
    assert adapter.calls == 0
    assert diagnostics.skipped_units == 1
    assert diagnostics.cancelled_units == len(windows) - 1
    assert diagnostics.terminal_reason == "JOB_DEADLINE_EXCEEDED"


def test_completed_units_count_only_successes() -> None:
    windows = [_window(index) for index in range(1, 7)]
    adapter = _CountingAdapter()
    diagnostics = BuildDiagnostics()

    outcomes = _pipeline()._extract_windows(
        None, adapter, windows, ProgressReporter(None), None, diagnostics
    )

    assert len(outcomes) == len(windows)
    assert all(outcome.ok for outcome in outcomes)
    assert diagnostics.succeeded_units == len(windows)
    assert diagnostics.failed_units == 0
    assert diagnostics.llm_calls == len(windows)


def test_cache_hits_count_as_completed_without_new_calls() -> None:
    windows = [_window(index) for index in range(1, 5)]
    cached_payload = _valid_extraction(windows[0].payload).model_dump()
    adapter = _CountingAdapter()
    diagnostics = BuildDiagnostics()

    outcomes = _pipeline({"cache-1": cached_payload})._extract_windows(
        None, adapter, windows, ProgressReporter(None), None, diagnostics
    )

    assert len(outcomes) == len(windows)
    assert sum(1 for outcome in outcomes if outcome.cached) == 1
    assert diagnostics.cached_windows == 1
    assert diagnostics.succeeded_units == len(windows)
    assert adapter.calls == len(windows) - 1


def test_secondary_deadline_errors_do_not_override_root_cause() -> None:
    """先发生的 provider 失败保持为终态原因，后续取消不覆盖它。"""
    windows = [_window(index) for index in range(1, 6)]
    adapter = _FailingAdapter(
        AppError(code="LLM_REQUEST_FAILED", message="bad request", status_code=502)
    )
    diagnostics = BuildDiagnostics()

    with pytest.raises(AppError) as excinfo:
        _pipeline()._extract_windows(
            None, adapter, windows, ProgressReporter(None), None, diagnostics
        )

    assert excinfo.value.code == "LLM_REQUEST_FAILED"
    assert diagnostics.terminal_reason == "LLM_REQUEST_FAILED"
