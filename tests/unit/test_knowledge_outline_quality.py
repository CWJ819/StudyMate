"""Stage A 结构质量闸门回归测试。

覆盖：
- 逐页书签 / 逐页大标题不能直接变成章节；
- 三条解析路径（书签、字号启发、LLM 兜底）共用同一判定；
- LLM 输出同样过闸，最多一次带反馈的修复，仍不合格则显式失败；
- 页码式标题被拒绝；
- 预算不足时不发请求直接 JOB_DEADLINE_EXCEEDED。
"""

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from app.core.config import reset_settings_cache
from app.core.errors import AppError
from app.llm.schemas import (
    KnowledgeOutlineSectionV5,
    KnowledgeOutlineV5,
    LLMRunSummary,
    LLMStructuredResult,
)
from app.services.knowledge_outline_service import (
    KnowledgeOutlineService,
    OutlineSection,
    absorb_chapter_lead_in,
    is_meaningful_outline_title,
    outline_top_level_limit,
    umbrella_title_from_filename,
    validate_outline_quality,
    wrap_document_outline,
)
from app.services.knowledge_pipeline import BuildBudget


class _StaticStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve_path(self, storage_key: str) -> Path:
        return self.path


def _document(document_id: str, filename: str, suffix: str, page_texts: list[str], path: Path):
    return SimpleNamespace(
        id=document_id,
        filename=filename,
        storage_key=f"{document_id}{suffix}",
        pages=[
            SimpleNamespace(
                page_number=index,
                extracted_text=text,
                extraction_status="extracted",
            )
            for index, text in enumerate(page_texts, start=1)
        ],
        chunks=[],
    )


def _create_pdf(path: Path, pages: list[tuple[str, str]], toc: list[list] | None = None) -> None:
    document = fitz.open()
    for title, body in pages:
        page = document.new_page()
        page.insert_text((72, 72), title, fontname="china-s")
        page.insert_text((72, 110), body, fontname="china-s")
    if toc:
        document.set_toc(toc)
    document.save(path)
    document.close()


def _create_pdf_with_large_titles(path: Path, titles: list[str]) -> None:
    document = fitz.open()
    for title in titles:
        page = document.new_page()
        page.insert_text((72, 72), title, fontsize=22, fontname="china-s")
        page.insert_text((72, 130), "这一页的正文内容，字号明显小于标题。", fontsize=10, fontname="china-s")
    document.save(path)
    document.close()


class _OutlineAdapter:
    """按顺序返回预置大纲，并记录 payload。"""

    def __init__(self, outlines: list[KnowledgeOutlineV5]) -> None:
        self.outlines = list(outlines)
        self.payloads: list[dict] = []

    def ensure_available(self) -> None:
        return None

    def generate_structured_output(self, **kwargs) -> LLMStructuredResult:
        self.payloads.append(kwargs["user_payload"])
        data = self.outlines.pop(0)
        return LLMStructuredResult(
            summary=LLMRunSummary(
                model_name="fake-model",
                prompt_version=kwargs["prompt_version"],
                provider="fake",
            ),
            data=data,
        )


def _chapters(specs: list[tuple[str, int, int]]) -> KnowledgeOutlineV5:
    return KnowledgeOutlineV5(
        root_title="课程",
        sections=[
            KnowledgeOutlineSectionV5(
                ref=f"c{index}",
                title=title,
                level=1,
                parent_ref=None,
                page_start=start,
                page_end=end,
                evidence_page_numbers=[start],
            )
            for index, (title, start, end) in enumerate(specs, start=1)
        ],
    )


# --------------------------------------------------------------------------
# 纯判定
# --------------------------------------------------------------------------


def test_one_section_per_page_is_rejected() -> None:
    sections = [OutlineSection("doc", f"性能分析（{index}）", 1, index, index) for index in range(1, 121)]

    quality = validate_outline_quality(sections, 120)

    assert not quality.ok
    assert "too_many_top_level" in quality.reasons
    assert "per_page_headings" in quality.reasons
    assert "no_hierarchy" in quality.reasons
    assert quality.limit == 20  # max(20, ceil(120 / 12))


def test_chapter_outline_passes_the_gate() -> None:
    sections = [
        OutlineSection("doc", f"第{index}章 主题{index}", 1, index * 10, index * 10 + 9)
        for index in range(1, 13)
    ]
    sections += [
        OutlineSection("doc", f"{index}.1 小节", 2, index * 10, index * 10 + 4)
        for index in range(1, 13)
    ]

    quality = validate_outline_quality(sections, 184)

    assert quality.ok, quality.reasons
    assert quality.limit == outline_top_level_limit(184) == 20


def test_page_number_titles_are_rejected() -> None:
    sections = [OutlineSection("doc", str(index), 1, index, index) for index in range(1, 11)]

    quality = validate_outline_quality(sections, 10)

    assert not quality.ok
    assert "invalid_titles" in quality.reasons
    assert not is_meaningful_outline_title("4.2")
    assert not is_meaningful_outline_title("第 3 章")
    assert not is_meaningful_outline_title("12")
    # 保守规则：缩写与两字标题仍然有效
    assert is_meaningful_outline_title("TCP")
    assert is_meaningful_outline_title("概述")


# --------------------------------------------------------------------------
# 逐页书签 → 必须走 LLM fallback
# --------------------------------------------------------------------------


def test_per_page_bookmarks_fall_back_to_llm_outline(tmp_path: Path) -> None:
    pages = [(f"幻灯片 {index} 标题", "这一页的正文内容用于占位。") for index in range(1, 31)]
    pdf_path = tmp_path / "slides.pdf"
    _create_pdf(pdf_path, pages, toc=[[1, f"幻灯片 {index} 标题", index] for index in range(1, 31)])

    adapter = _OutlineAdapter(
        [
            _chapters(
                [
                    ("第1章 引言", 1, 10),
                    ("第2章 原理", 11, 20),
                    ("第3章 应用", 21, 30),
                ]
            )
        ]
    )
    document = _document("doc-1", "slides.pdf", ".pdf", [title for title, _ in pages], pdf_path)

    merged = KnowledgeOutlineService(storage=_StaticStorage(pdf_path)).build_course_outline(
        [document], adapter=adapter, course_name="Demo"
    )

    assert [chapter.title for chapter in merged] == ["第1章 引言", "第2章 原理", "第3章 应用"]
    assert len(adapter.payloads) == 1
    assert adapter.payloads[0]["constraints"]["max_chapters"] == 20
    assert adapter.payloads[0]["inventory_truncated"] is False


def test_llm_outline_is_rejected_after_one_repair_attempt(tmp_path: Path) -> None:
    pages = [(f"幻灯片 {index} 标题", "这一页的正文内容用于占位。") for index in range(1, 31)]
    pdf_path = tmp_path / "slides.pdf"
    _create_pdf(pdf_path, pages, toc=[[1, f"幻灯片 {index} 标题", index] for index in range(1, 31)])

    bad_outline = _chapters([(f"主题 {index}", index, index) for index in range(1, 41)])
    adapter = _OutlineAdapter([bad_outline, bad_outline])
    document = _document("doc-2", "slides.pdf", ".pdf", [title for title, _ in pages], pdf_path)

    with pytest.raises(AppError) as excinfo:
        KnowledgeOutlineService(storage=_StaticStorage(pdf_path)).build_course_outline(
            [document], adapter=adapter, course_name="Demo"
        )

    assert excinfo.value.code == "KNOWLEDGE_OUTLINE_FAILED"
    assert excinfo.value.details["top_level"] == 40
    assert len(adapter.payloads) == 2
    assert any(
        "A previous outline attempt was rejected" in rule
        for rule in adapter.payloads[1]["rules"]
    )


def test_page_inventory_includes_large_font_titles(tmp_path: Path) -> None:
    pdf_path = tmp_path / "deck.pdf"
    _create_pdf_with_large_titles(
        pdf_path, ["第4章 介质访问子层", "4.1 信道分配", "4.2 多路访问协议"]
    )
    document = _document(
        "doc-3",
        "deck.pdf",
        ".pdf",
        ["第4章 介质访问子层", "4.1 信道分配", "4.2 多路访问协议"],
        pdf_path,
    )

    entries, truncated = KnowledgeOutlineService(
        storage=_StaticStorage(pdf_path)
    )._page_inventory(document)

    assert truncated is False
    headings = [heading for entry in entries for heading in entry["headings"]]
    assert "第4章 介质访问子层" in headings
    assert "4.1 信道分配" in headings


# --------------------------------------------------------------------------
# 预算模型
# --------------------------------------------------------------------------


def test_budget_refuses_to_start_a_call_without_a_full_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")
    reset_settings_cache()
    try:
        # 50s 截止 - 10s 收尾预留 = 40s 可用 < max(30, 3 * 15) = 45s
        budget = BuildBudget(deadline_seconds=50, clock=lambda: 0.0)

        with pytest.raises(AppError) as excinfo:
            budget.ensure_call_possible()
        assert excinfo.value.code == "JOB_DEADLINE_EXCEEDED"
    finally:
        reset_settings_cache()


def test_budget_call_timeout_never_drops_below_min_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")
    reset_settings_cache()
    now = [0.0]
    try:
        budget = BuildBudget(deadline_seconds=270, clock=lambda: now[0])
        assert budget.call_timeout() == 60

        # 剩余 55s → 可用 45s → 每次尝试 15s（下限，而不是 5s）
        now[0] = 215.0
        assert budget.call_timeout() == 15

        # 剩余 54s → 可用 44s < 45s → 不再发起调用
        now[0] = 216.0
        with pytest.raises(AppError):
            budget.ensure_call_possible()
    finally:
        reset_settings_cache()


class _DictOutlineCache:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get(self, cache_key: str) -> dict | None:
        return self.rows.get(cache_key)

    def put(
        self,
        cache_key: str,
        *,
        document_id: str,
        content_hash: str,
        prompt_version: str,
        model_name: str,
        payload: dict,
    ) -> None:
        self.rows[cache_key] = payload


def test_outline_cache_avoids_second_llm_call(tmp_path: Path) -> None:
    pages = [(f"幻灯片 {index} 标题", "这一页的正文内容用于占位。") for index in range(1, 31)]
    pdf_path = tmp_path / "slides.pdf"
    _create_pdf(pdf_path, pages, toc=[[1, f"幻灯片 {index} 标题", index] for index in range(1, 31)])
    document = _document("doc-cache", "slides.pdf", ".pdf", [title for title, _ in pages], pdf_path)
    cache = _DictOutlineCache()

    first_adapter = _OutlineAdapter([_chapters([("第1章 引言", 1, 10), ("第2章 原理", 11, 30)])])
    first = KnowledgeOutlineService(
        storage=_StaticStorage(pdf_path), cache=cache
    ).build_course_outline([document], adapter=first_adapter, course_name="Demo")

    # 第二次用空适配器：若仍调用模型会直接 IndexError
    second_adapter = _OutlineAdapter([])
    second = KnowledgeOutlineService(
        storage=_StaticStorage(pdf_path), cache=cache
    ).build_course_outline([document], adapter=second_adapter, course_name="Demo")

    assert len(first_adapter.payloads) == 1
    assert second_adapter.payloads == []
    assert [chapter.title for chapter in second] == [chapter.title for chapter in first]
    assert cache.rows  # 大纲已落缓存

def test_budget_uses_the_adapter_effective_settings() -> None:
    """设置页的 DB 覆盖优先于环境变量；预算必须按同一份设置计算。"""
    from types import SimpleNamespace

    settings = SimpleNamespace(llm_max_retries=1, llm_timeout_seconds=10)
    budget = BuildBudget(deadline_seconds=60, clock=lambda: 0.0, settings=settings)

    assert budget.inner_attempts == 2
    assert budget.min_request_window == 30  # max(30, 2 * 15)
    assert budget.call_timeout() == 10  # min(provider 10, available 50 / 2)


# --------------------------------------------------------------------------
# 章首/章尾过渡页吸收
# --------------------------------------------------------------------------


def _chapter(title: str, start: int, end: int, document: str = "doc") -> OutlineSection:
    return OutlineSection(document, title, 1, start, end)


def _section(title: str, start: int, end: int, document: str = "doc") -> OutlineSection:
    return OutlineSection(document, title, 2, start, end)


def test_chapter_lead_in_moves_to_the_first_section() -> None:
    sections = [
        _chapter("第1章 概述", 1, 10),
        _section("1.1 背景", 7, 10),
        _chapter("第2章 原理", 11, 46),
        _section("2.1 模型", 13, 20),
        _section("2.2 推导", 21, 46),
    ]

    adjusted = absorb_chapter_lead_in(sections, 46)

    ranges = [(item.title, item.page_start, item.page_end) for item in adjusted]
    assert ranges == [
        ("第1章 概述", 1, 10),
        ("1.1 背景", 1, 10),
        ("第2章 原理", 11, 46),
        ("2.1 模型", 11, 20),
        ("2.2 推导", 21, 46),
    ]


def test_chapter_tail_pages_join_the_last_section() -> None:
    sections = [
        _chapter("第1章 概述", 1, 21),
        _section("1.1 背景", 4, 12),
        _section("1.2 现状", 13, 20),
        _chapter("第2章 原理", 22, 40),
        _section("2.1 模型", 23, 40),
    ]

    adjusted = absorb_chapter_lead_in(sections, 40)

    assert (adjusted[1].page_start, adjusted[1].page_end) == (1, 12)
    assert (adjusted[2].page_start, adjusted[2].page_end) == (13, 21)
    assert (adjusted[4].page_start, adjusted[4].page_end) == (22, 40)


def test_chapter_without_sections_is_left_alone() -> None:
    """整章一个窗口的章节本来就被完整覆盖，不能被"吸收"改动。"""
    sections = [
        _chapter("第1章 导论", 1, 11),
        _chapter("第2章 原理", 12, 36),
        _section("2.1 模型", 13, 36),
    ]

    adjusted = absorb_chapter_lead_in(sections, 36)

    assert (adjusted[0].page_start, adjusted[0].page_end) == (1, 11)
    assert (adjusted[1].page_start, adjusted[1].page_end) == (12, 36)
    assert (adjusted[2].page_start, adjusted[2].page_end) == (12, 36)


def test_absorbs_gaps_between_chapters_and_clamps_to_page_count() -> None:
    """LLM 给的章区间偏短时补齐空洞；越界的节区间收敛到章边界。"""
    sections = [
        _chapter("第1章 概述", 2, 9),
        _section("1.1 背景", 4, 15),
        _chapter("第2章 原理", 20, 28),
        _section("2.1 模型", 22, 40),
    ]

    adjusted = absorb_chapter_lead_in(sections, 30)

    # 第1章章尾补到 19（下一章起点 20 之前），唯一小节覆盖整章
    assert (adjusted[0].page_start, adjusted[0].page_end) == (2, 19)
    assert (adjusted[1].page_start, adjusted[1].page_end) == (2, 19)
    # 第2章补到文档末页 30，越界的节区间收敛到章末尾
    assert (adjusted[2].page_start, adjusted[2].page_end) == (20, 30)
    assert (adjusted[3].page_start, adjusted[3].page_end) == (20, 30)


def test_gaps_between_sibling_sections_are_filled() -> None:
    """LLM 常见的"节与节之间留洞"也要铺满：前节延伸，不改后节起点。"""
    sections = [
        _chapter("第3章 差错控制", 50, 66),
        _section("3.1 检错", 51, 55),
        _section("3.2 纠错", 60, 65),
        _chapter("第4章 介质访问", 67, 95),
        _section("4.1 信道分配", 68, 95),
    ]

    adjusted = absorb_chapter_lead_in(sections, 95)

    assert (adjusted[1].page_start, adjusted[1].page_end) == (50, 59)
    assert (adjusted[2].page_start, adjusted[2].page_end) == (60, 66)
    assert (adjusted[4].page_start, adjusted[4].page_end) == (67, 95)


def test_absorb_is_idempotent() -> None:
    sections = [
        _chapter("第1章 概述", 1, 10),
        _section("1.1 背景", 3, 5),
        _section("1.2 现状", 6, 8),
    ]

    once = absorb_chapter_lead_in(sections, 10)
    twice = absorb_chapter_lead_in(once, 10)

    assert [(s.page_start, s.page_end) for s in once] == [
        (s.page_start, s.page_end) for s in twice
    ]


def test_outline_build_absorbs_lead_in_for_bookmark_outlines(tmp_path: Path) -> None:
    """书签路径同样要补章首页：1.1 从第 3 页起，第 1 章从第 1 页起。"""
    pages = [(f"正文页 {index}", "这一页的正文内容用于占位。") for index in range(1, 41)]
    pdf_path = tmp_path / "bookmarks.pdf"
    _create_pdf(
        pdf_path,
        pages,
        toc=[
            [1, "第1章 概述", 1],
            [2, "1.1 背景", 3],
            [2, "1.2 现状", 6],
            [1, "第2章 原理", 11],
            [2, "2.1 模型", 12],
        ],
    )
    document = _document("doc-lead", "bookmarks.pdf", ".pdf", [text for text, _ in pages], pdf_path)

    merged = KnowledgeOutlineService(storage=_StaticStorage(pdf_path)).build_course_outline(
        [document], adapter=_OutlineAdapter([]), course_name="Demo"
    )

    first_chapter = merged[0]
    assert first_chapter.title == "第1章 概述"
    assert first_chapter.page_ranges == [("doc-lead", 1, 10)]
    assert first_chapter.children[0].title == "1.1 背景"
    assert first_chapter.children[0].page_ranges == [("doc-lead", 1, 5)]


# --------------------------------------------------------------------------
# 文档级伞形章
# --------------------------------------------------------------------------


def _doc(filename: str, document_id: str = "doc"):
    return SimpleNamespace(id=document_id, filename=filename)


def test_wrap_promotes_the_only_chapter_heading_to_umbrella() -> None:
    """ch4 形态：一个"第X章"+ 若干节级一级标题 → 收敛成 1 章 6 节。"""
    sections = [
        _chapter("第四章介质访问子层", 1, 11),
        _chapter("随机访问协议", 12, 36),
        _chapter("受控访问协议", 37, 42),
        _chapter("以太网", 47, 76),
        _section("以太网技术前沿", 78, 76),  # 越界/倒挂的子节点，应被收敛
    ]

    wrapped = wrap_document_outline(_doc("ch4_MAC子层_v2.0(5).pdf"), sections, page_count=184)

    assert [(s.title, s.level, s.page_start, s.page_end) for s in wrapped] == [
        ("第四章介质访问子层", 1, 1, 184),
        ("随机访问协议", 2, 12, 36),
        ("受控访问协议", 2, 37, 42),
        ("以太网", 2, 47, 76),
    ]


def test_wrap_creates_umbrella_from_root_title() -> None:
    """ch3 形态：6 个节级一级、没有"第X章" → 用 LLM 的 root_title 造伞形章。"""
    sections = [
        _chapter("数据链路层的设计问题", 1, 21),
        _chapter("差错检测和纠正", 22, 49),
        _chapter("本章总结", 118, 120),
    ]

    wrapped = wrap_document_outline(
        _doc("ch3_数据链路层_v2.0(3).pdf"), sections, root_title="第三章 数据链路层基础", page_count=120
    )

    assert wrapped[0].title == "第三章 数据链路层基础"
    assert (wrapped[0].level, wrapped[0].page_start, wrapped[0].page_end) == (1, 1, 120)
    assert [s.title for s in wrapped[1:]] == ["数据链路层的设计问题", "差错检测和纠正", "本章总结"]
    assert all(s.level == 2 for s in wrapped[1:])


def test_wrap_falls_back_to_filename_title() -> None:
    """没有 root_title 时从 ch3_数据链路层_v2.0(3).pdf 里取章名。"""
    sections = [_chapter("数据链路层的设计问题", 1, 21), _chapter("差错检测和纠正", 22, 49)]

    wrapped = wrap_document_outline(_doc("ch3_数据链路层_v2.0(3).pdf"), sections, page_count=120)

    assert wrapped[0].title == "第三章 数据链路层"
    assert umbrella_title_from_filename("ch4-MAC子层.pptx") == "第四章 MAC子层"
    assert umbrella_title_from_filename("slides.pdf") is None


def test_wrap_keeps_document_without_any_umbrella_title() -> None:
    sections = [_chapter("性能分析", 1, 10), _chapter("可靠性", 11, 30)]

    wrapped = wrap_document_outline(_doc("slides.pdf"), sections, root_title="12", page_count=30)

    assert wrapped == sections


def test_wrap_keeps_multi_chapter_documents_untouched() -> None:
    sections = [
        _chapter("第1章 概述", 1, 20),
        _section("1.1 背景", 1, 20),
        _chapter("第2章 原理", 21, 40),
        _chapter("第3章 应用", 41, 60),
    ]

    wrapped = wrap_document_outline(_doc("book.pdf"), sections, page_count=60)

    assert wrapped == sections


def test_wrap_merges_demoted_child_ranges_to_avoid_losing_pages() -> None:
    sections = [
        _chapter("第一章引言", 10, 118),
        _chapter("课程的任务", 1, 9),
        _section("课程目标", 1, 5),
        _section("实验安排", 6, 12),
    ]

    wrapped = wrap_document_outline(_doc("ch1_引言.pdf"), sections, page_count=118)

    demoted = next(s for s in wrapped if s.title == "课程的任务")
    assert (demoted.level, demoted.page_start, demoted.page_end) == (2, 1, 12)
    assert [s.title for s in wrapped if s.level == 2] == ["课程的任务"]


def test_wrap_then_absorb_covers_document_head() -> None:
    """wrap 之后章首仍要靠吸收补：首节前移到章起始。"""
    sections = [
        _chapter("第四章介质访问子层", 1, 10),
        _chapter("多路访问协议", 11, 46),
        _chapter("以太网", 47, 76),
    ]

    wrapped = absorb_chapter_lead_in(
        wrap_document_outline(_doc("ch4.pdf"), sections, page_count=76), 76
    )

    assert [(s.title, s.page_start, s.page_end) for s in wrapped] == [
        ("第四章介质访问子层", 1, 76),
        ("多路访问协议", 1, 46),
        ("以太网", 47, 76),
    ]


def test_wrap_is_idempotent() -> None:
    sections = [
        _chapter("第四章介质访问子层", 1, 10),
        _chapter("多路访问协议", 11, 46),
        _chapter("以太网", 47, 76),
    ]

    once = wrap_document_outline(_doc("ch4.pdf"), sections, page_count=76)
    twice = wrap_document_outline(_doc("ch4.pdf"), once, page_count=76)

    assert [(s.title, s.level, s.page_start, s.page_end) for s in once] == [
        (s.title, s.level, s.page_start, s.page_end) for s in twice
    ]