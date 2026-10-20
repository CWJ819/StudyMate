"""多批次知识框架合并保留「文档 → 知识点」层级（真实模型验收 2026-10-20 D3）。"""

from types import SimpleNamespace

from app.llm.schemas import (
    KnowledgeFrameworkCandidate,
    KnowledgeNodeCandidate,
    KnowledgeSourceCandidate,
)
from app.services.knowledge_service import KnowledgeService


def _topic(ref: str, title: str, document_id: str, page: int) -> KnowledgeNodeCandidate:
    # 内容需超过 MIN_KNOWLEDGE_CONTENT_CHARS(24) 才能通过质量过滤
    return KnowledgeNodeCandidate(
        ref=ref,
        title=title,
        content=f"{title}：本知识点描述对应课件内容的定义、工作机制与典型应用场景，供复习参考。",
        sources=[
            KnowledgeSourceCandidate(
                document_id=document_id, page_number=page, evidence_type="chunk"
            )
        ],
        children=[],
    )


def test_merge_preserves_document_hierarchy_and_per_doc_dedupe() -> None:
    doc_a = SimpleNamespace(id="doc-a", filename="ch4_MAC子层.pdf")
    doc_b = SimpleNamespace(id="doc-b", filename="运输层课件示例.pdf")
    # 两个批次候选：批次1 携带 doc-a 的两个 topic（嵌在文档节点下），批次2 携带 doc-a 的
    # 重复标题 topic + doc-b 的一个 topic —— 模拟跨批次重叠
    candidates = [
        KnowledgeFrameworkCandidate(
            root_title="ignored-in-merge",
            nodes=[
                KnowledgeNodeCandidate(
                    ref="b1_doc_a",
                    title="ch4_MAC子层.pdf",
                    sources=[],
                    children=[_topic("b1_t1", "4.2.1 随机访问协议", "doc-a", 30)],
                )
            ],
        ),
        KnowledgeFrameworkCandidate(
            root_title="ignored-in-merge",
            nodes=[
                KnowledgeNodeCandidate(
                    ref="b2_doc_a",
                    title="ch4_MAC子层.pdf",
                    sources=[],
                    children=[
                        _topic("b2_t1", "4.2.1 随机访问协议", "doc-a", 30),  # 跨批次重复
                        _topic("b2_t2", "4.1 信道分配问题", "doc-a", 6),  # 页码更小，应排前
                    ],
                ),
                KnowledgeNodeCandidate(
                    ref="b2_doc_b",
                    title="运输层课件示例.pdf",
                    sources=[],
                    children=[_topic("b2_t3", "慢启动与拥塞避免", "doc-b", 1)],
                ),
            ],
        ),
    ]

    merged = KnowledgeService()._merge_batch_candidates(
        course_name="计算机网络",
        documents=[doc_a, doc_b],
        candidates=candidates,
        batch_count=2,
    )

    # 根 → 文档父节点 → 知识点
    assert [node.title for node in merged.nodes] == ["ch4_MAC子层.pdf", "运输层课件示例.pdf"]
    doc_a_children = merged.nodes[0].children
    doc_b_children = merged.nodes[1].children
    assert [t.title for t in doc_a_children] == ["4.1 信道分配问题", "4.2.1 随机访问协议"]  # 按页码排序 + 去重
    assert [t.title for t in doc_b_children] == ["慢启动与拥塞避免"]

    # section_label 从标题推断；文档父节点不挂来源；无编号标题留空
    assert doc_a_children[0].section_label == "4.1"
    assert doc_a_children[1].section_label == "4.2.1"
    assert doc_b_children[0].section_label is None
    assert merged.nodes[0].sources == []

    # relations 只连文档内相邻：doc-a 2 个 topic → 1 条；doc-b 1 个 → 0 条
    refs = {r.source_ref for r in merged.relations} | {r.target_ref for r in merged.relations}
    all_topic_refs = {t.ref for node in merged.nodes for t in node.children}
    assert refs <= all_topic_refs
    assert len(merged.relations) == 1


def test_infer_section_label_ignores_standard_numbers_and_years() -> None:
    service = KnowledgeService()
    assert service._infer_section_label("4.2.1 随机访问协议的特点") == "4.2.1"
    assert service._infer_section_label("Chapter 4 介质访问子层") == "Chapter 4"
    assert service._infer_section_label("IEEE 802.3by 25G/100G 标准") is None  # 标准号
    assert service._infer_section_label("2014 年发布的规范") is None  # 年份
