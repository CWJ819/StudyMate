"""v5 构建流水线单测：大纲解析三路（PDF 书签 / 编号标题启发 / PPTX 标题占位符）、
多文档大纲合并、身份裁决四分支、进度映射单调性、叶子质量过滤。"""

from pathlib import Path
from types import SimpleNamespace

import fitz
from pptx import Presentation

from app.services.knowledge_outline_service import (
    KnowledgeOutlineService,
    OutlineSection,
    classify_heading,
    merge_document_outlines,
)
from app.services.knowledge_pipeline import (
    IdentityDecision,
    IdentityResolver,
    OldLeafRef,
    compute_phase_progress,
    is_quality_topic,
)


class _StaticStorage:
    """测试用静态存储：resolve_path 直接返回预置文件路径。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve_path(self, storage_key: str) -> Path:
        return self.path


def _document(document_id: str, filename: str, suffix: str, total_pages: int, path: Path):
    return SimpleNamespace(
        id=document_id,
        filename=filename,
        storage_key=f"{document_id}{suffix}",
        pages=[
            SimpleNamespace(
                page_number=number,
                extracted_text=f"page {number} body text",
                extraction_status="extracted",
            )
            for number in range(1, total_pages + 1)
        ],
        chunks=[],
        _path=path,
    )


def _service_for(path: Path) -> KnowledgeOutlineService:
    return KnowledgeOutlineService(storage=_StaticStorage(path))


# --------------------------------------------------------------------------
# Stage A：PDF 书签（TOC）
# --------------------------------------------------------------------------


def test_pdf_outline_uses_bookmarks_and_page_ranges(tmp_path: Path) -> None:
    pdf_path = tmp_path / "toc.pdf"
    document = fitz.open()
    for index in range(6):
        page = document.new_page()
        page.insert_text((72, 72), f"body content {index}")
    document.set_toc(
        [
            [1, "Chapter 3 Transport", 1],
            [2, "3.1 UDP", 1],
            [2, "3.2 TCP", 3],
            [1, "Chapter 4 MAC", 5],
        ]
    )
    document.save(pdf_path)
    document.close()

    doc = _document("doc-1", "toc.pdf", ".pdf", 6, pdf_path)
    sections = _service_for(pdf_path)._pdf_outline(doc)

    assert [(s.title, s.level, s.page_start, s.page_end) for s in sections] == [
        ("Chapter 3 Transport", 1, 1, 4),
        ("3.1 UDP", 2, 1, 2),
        ("3.2 TCP", 2, 3, 4),
        ("Chapter 4 MAC", 1, 5, 6),
    ]


# --------------------------------------------------------------------------
# Stage A：无书签时的编号标题启发
# --------------------------------------------------------------------------


def test_pdf_outline_falls_back_to_numbered_heading_heuristic(tmp_path: Path) -> None:
    pdf_path = tmp_path / "no_toc.pdf"
    document = fitz.open()
    page_texts = [
        "第1章 网络基础概述",
        "1.1 计算机网络的定义与组成",
        "没有编号的正文内容页面",
        "第2章 物理层传输机制",
    ]
    for text in page_texts:
        page = document.new_page()
        # 中文必须用内建 china-s 字体，否则提取出的文本会退化为占位符
        page.insert_text((72, 72), text, fontname="china-s")
        page.insert_text((72, 110), "plain body sentence that carries no heading pattern.")
    document.save(pdf_path)
    document.close()

    doc = _document("doc-2", "no_toc.pdf", ".pdf", 4, pdf_path)
    sections = _service_for(pdf_path)._pdf_outline(doc)

    assert [(s.title, s.level, s.page_start, s.page_end) for s in sections] == [
        ("第1章 网络基础概述", 1, 1, 3),
        ("1.1 计算机网络的定义与组成", 2, 2, 3),
        ("第2章 物理层传输机制", 1, 4, 4),
    ]


# --------------------------------------------------------------------------
# Stage A：PPTX 标题占位符
# --------------------------------------------------------------------------


def test_pptx_outline_uses_title_placeholders(tmp_path: Path) -> None:
    pptx_path = tmp_path / "deck.pptx"
    presentation = Presentation()
    title_layout = presentation.slide_layouts[0]
    content_layout = presentation.slide_layouts[1]

    slide1 = presentation.slides.add_slide(title_layout)
    slide1.shapes.title.text = "Chapter 1 Intro"
    slide2 = presentation.slides.add_slide(content_layout)
    slide2.shapes.title.text = "1.1 Overview"
    slide3 = presentation.slides.add_slide(content_layout)
    slide3.shapes.title.text = "1.2 Details"
    presentation.save(pptx_path)

    doc = _document("doc-3", "deck.pptx", ".pptx", 3, pptx_path)
    sections = _service_for(pptx_path)._pptx_outline(doc)

    assert [(s.title, s.level, s.page_start, s.page_end) for s in sections] == [
        ("Chapter 1 Intro", 1, 1, 3),
        ("1.1 Overview", 2, 2, 2),
        ("1.2 Details", 2, 3, 3),
    ]


# --------------------------------------------------------------------------
# 多文档大纲合并
# --------------------------------------------------------------------------


def test_merge_document_outlines_dedupes_chapters_across_documents() -> None:
    doc_a = SimpleNamespace(id="doc-a", filename="a.pdf")
    doc_b = SimpleNamespace(id="doc-b", filename="b.pdf")
    doc_a_sections = [
        OutlineSection("doc-a", "第1章 概述", 1, 1, 3),
        OutlineSection("doc-a", "第2章 传输", 1, 4, 6),
    ]
    doc_b_sections = [
        OutlineSection("doc-b", "第1章 概述", 1, 1, 2),
        OutlineSection("doc-b", "第2章 传输", 1, 1, 1),
        OutlineSection("doc-b", "2.1 UDP", 2, 2, 3),
    ]

    merged = merge_document_outlines([(doc_a, doc_a_sections), (doc_b, doc_b_sections)])

    assert [chapter.title for chapter in merged] == ["第1章 概述", "第2章 传输"]
    first, second = merged
    assert first.page_ranges == [("doc-a", 1, 3), ("doc-b", 1, 2)]
    assert first.children == []
    assert second.page_ranges == [("doc-a", 4, 6), ("doc-b", 1, 1)]
    assert [child.title for child in second.children] == ["2.1 UDP"]
    assert second.children[0].page_ranges == [("doc-b", 2, 3)]


# --------------------------------------------------------------------------
# 身份裁决四分支
# --------------------------------------------------------------------------


def test_identity_resolver_branches() -> None:
    resolver = IdentityResolver(
        old_leaves=[
            OldLeafRef("node-udp", "UDP 协议", has_learning_data=False),
            OldLeafRef("node-tcp", "TCP 协议", has_learning_data=True),
            OldLeafRef("node-tcp-dup", "tcp 协议", has_learning_data=False),
            OldLeafRef("node-old", "旧 概念", has_learning_data=True),
            OldLeafRef("node-old-dup", "旧  概念", has_learning_data=True),
        ]
    )

    # 零匹配 → 新建、不算孤儿化
    assert resolver.resolve("全新概念") == IdentityDecision(None, False)

    # 唯一匹配 → 复用
    assert resolver.resolve("UDP 协议") == IdentityDecision("node-udp", False)

    # 多候选、恰一个有学习数据 → 复用那个
    assert resolver.resolve("TCP 协议") == IdentityDecision("node-tcp", False)

    # 多候选、多个有学习数据 → 新建 + 显式孤儿化（绝不合并两份掌握度）
    decision = resolver.resolve("旧 概念")
    assert decision.reuse_node_id is None
    assert decision.orphaned is True

    # 大小写/多重空白折叠后仍命中同一候选
    assert resolver.resolve("  TCP  协议 ").reuse_node_id == "node-tcp"


# --------------------------------------------------------------------------
# 进度映射与质量过滤
# --------------------------------------------------------------------------


def test_phase_progress_is_monotonic_and_bounded() -> None:
    values = [compute_phase_progress("outline", completed, total=3) for completed in range(4)]
    values += [compute_phase_progress("extract", completed, total=5) for completed in range(6)]
    values += [
        compute_phase_progress("merge", 1, 1),
        compute_phase_progress("validate", 1, 1),
        compute_phase_progress("activate", 1, 1),
    ]
    assert values == sorted(values)
    assert all(1 <= value < 100 for value in values)
    assert compute_phase_progress("extract", 0, 0) == 15


def test_is_quality_topic_filters_unusable_leaves() -> None:
    long_title = "超" * 200
    assert not is_quality_topic(long_title, "足够长的解释内容，超过二十四个字符以上。")
    assert not is_quality_topic("Agenda", "今天的议程内容包括三章内容安排，足够长。")
    assert not is_quality_topic("短内容", "太短")
    assert not is_quality_topic("标题", "")
    assert is_quality_topic("UDP 协议", "用户数据报协议是无连接的传输层协议，提供不可靠传输。")


def test_classify_heading_levels() -> None:
    assert classify_heading("第3章 运输层") == (1, "第3章")
    assert classify_heading("Chapter 4 Medium Access") == (1, "Chapter 4")
    assert classify_heading("3.2 TCP 拥塞控制") == (2, "3.2")
    assert classify_heading("12 设计问题") == (1, "12")
    assert classify_heading("普通句子没有编号") is None
