"""Phase 2 关系层单测：窗口叶子预算缩放、关系校验/去重/上限、落库映射。

关系是"可选装饰"：任何一条坏关系都只能被丢弃，不能影响叶子或整个构建。
"""

from types import SimpleNamespace

from app.llm.schemas import KnowledgeRelationV5, KnowledgeSectionExtractionV5
from app.services.knowledge_pipeline import (
    FrameworkSourceUnit,
    BuildDiagnostics,
    KnowledgeBuildPipeline,
    PendingRelation,
    SectionWindow,
    WindowCallMeta,
    WindowOutcome,
    _section_cache_key,
    compute_max_leaves_hint,
    count_window_pages,
    normalize_title_key,
)

LONG_CONTENT = "这一条解释足够长，可以通过叶子质量过滤，并且带有明确的适用条件。"


class _StubRepository:
    def chunk_belongs_to_document(self, session, *, chunk_id: str, document_id: str) -> bool:
        return True


class _RecordingRepository:
    def __init__(self) -> None:
        self.relations: list[dict] = []

    def add_relation(self, session, **kwargs) -> None:
        self.relations.append(kwargs)


def _pipeline() -> KnowledgeBuildPipeline:
    return KnowledgeBuildPipeline(repository=_StubRepository())


def _leaf(
    ref: str,
    title: str,
    *,
    page: int = 1,
    content: str = LONG_CONTENT,
    document_id: str = "doc-1",
) -> dict:
    return {
        "ref": ref,
        "title": title,
        "content": content,
        "sources": [
            {
                "document_id": document_id,
                "page_number": page,
                "chunk_id": None,
                "evidence_type": "page_excerpt",
            }
        ],
    }


def _outcome(index: int, leaves: list[dict], relations: list[dict]) -> WindowOutcome:
    window = SectionWindow(
        window_index=index,
        chapter_index=1,
        section_index=1,
        section_path=["第1章 基础", "1.1 概述"],
        page_ranges=[("doc-1", 1, 5)],
        units=[],
        content_hash=f"hash-{index}",
        cache_key=f"cache-{index}",
        payload={},
    )
    data = KnowledgeSectionExtractionV5.model_validate(
        {"section_ref": "section", "leaves": leaves, "relations": relations}
    )
    return WindowOutcome(window=window, ok=True, data=data, meta=WindowCallMeta())


def _collect(outcomes: list[WindowOutcome]):
    diagnostics = BuildDiagnostics()
    section = SimpleNamespace(title="1.1 概述", page_ranges=[("doc-1", 1, 5)])
    leaves, relations = _pipeline()._collect_leaves(
        None, section, outcomes, diagnostics
    )
    return leaves, relations, diagnostics


# --------------------------------------------------------------------------
# 叶子预算随窗口页数缩放
# --------------------------------------------------------------------------


def test_max_leaves_scales_with_window_pages_and_is_clamped() -> None:
    assert compute_max_leaves_hint(0) == 10
    assert compute_max_leaves_hint(1) == 10
    assert compute_max_leaves_hint(3) == 10
    assert compute_max_leaves_hint(20) == 10
    assert compute_max_leaves_hint(21) == 10
    assert compute_max_leaves_hint(22) == 11
    assert compute_max_leaves_hint(30) == 15
    assert compute_max_leaves_hint(46) == 20
    assert compute_max_leaves_hint(184) == 20


def test_count_window_pages_sums_document_spans() -> None:
    units = [
        FrameworkSourceUnit("doc-a", "a.pdf", 3, 5, "a1"),
        FrameworkSourceUnit("doc-a", "a.pdf", 6, 6, "a2"),
        FrameworkSourceUnit("doc-b", "b.pdf", 1, 12, "b1"),
    ]

    # doc-a 覆盖 3–6（4 页），doc-b 覆盖 1–12（12 页），多文档相加
    assert count_window_pages(units) == 16
    assert count_window_pages([]) == 0


def test_window_payload_injects_page_scaled_budget() -> None:
    pipeline = _pipeline()
    wide_unit = FrameworkSourceUnit(
        document_id="doc-1",
        filename="ch1.pdf",
        page_number=1,
        page_end=46,
        text="正" * 5000,
    )
    narrow_unit = FrameworkSourceUnit(
        document_id="doc-1",
        filename="ch1.pdf",
        page_number=1,
        page_end=3,
        text="正" * 5000,
    )

    wide_payload = pipeline._window_payload(["第1章 基础", "1.1 概述"], [wide_unit])
    narrow_payload = pipeline._window_payload(["第1章 基础", "1.1 概述"], [narrow_unit])

    assert wide_payload["max_leaves"] == 20  # 46 页 // 2 = 23 → 上限 20
    assert narrow_payload["max_leaves"] == 10  # 3 页 → 下限 10
    assert wide_payload["source_segments"][0]["text"] == "正" * 5000


def test_cache_key_includes_leaf_budget() -> None:
    common = dict(
        content_hash="hash-1",
        model_name="deepseek-flash",
        section_path=["第1章 基础", "1.1 概述"],
        page_ranges=[("doc-1", 1, 46)],
    )

    assert _section_cache_key(**common, max_leaves=10) != _section_cache_key(
        **common, max_leaves=20
    )
    assert _section_cache_key(**common, max_leaves=20) == _section_cache_key(
        **common, max_leaves=20
    )


# --------------------------------------------------------------------------
# 关系校验
# --------------------------------------------------------------------------


def test_invalid_relations_are_dropped_without_touching_leaves() -> None:
    leaves = [_leaf("leaf_1", "知识点 A"), _leaf("leaf_2", "知识点 B"), _leaf("leaf_3", "知识点 C")]
    relations = [
        {"source_ref": "leaf_1", "target_ref": "leaf_2", "relation_type": "prerequisite", "confidence": 0.6},
        # 反向重复：保留置信度更高的方向
        {"source_ref": "leaf_2", "target_ref": "leaf_1", "relation_type": "prerequisite", "confidence": 0.9},
        {"source_ref": "leaf_1", "target_ref": "leaf_3", "relation_type": "causes", "confidence": 0.7},
        # 以下全部非法
        {"source_ref": "leaf_1", "target_ref": "leaf_1", "relation_type": "causes", "confidence": 0.8},
        {"source_ref": "leaf_9", "target_ref": "leaf_2", "relation_type": "causes", "confidence": 0.8},
        {"source_ref": "leaf_1", "target_ref": "leaf_3", "relation_type": "causes", "confidence": 1.5},
        {"source_ref": "leaf_1", "target_ref": "leaf_2", "relation_type": "related", "confidence": 0.5},
        {"source_ref": "leaf_3", "target_ref": "leaf_2", "relation_type": "derives", "confidence": "0.4"},
    ]

    collected, edges, diagnostics = _collect([_outcome(1, leaves, relations)])

    assert len(collected) == 3
    assert {(edge.source_key, edge.target_key, edge.relation_type, edge.confidence) for edge in edges} == {
        (normalize_title_key("知识点 B"), normalize_title_key("知识点 A"), "prerequisite", 0.9),
        (normalize_title_key("知识点 A"), normalize_title_key("知识点 C"), "causes", 0.7),
        (normalize_title_key("知识点 C"), normalize_title_key("知识点 B"), "derives", 0.4),
    }
    assert diagnostics.relations_dropped == 5


def test_relations_referencing_dropped_leaf_are_discarded() -> None:
    leaves = [
        _leaf("leaf_1", "知识点 A"),
        _leaf("leaf_2", "太短", content="太短"),
        _leaf("leaf_3", "越界页", page=99),
    ]
    relations = [
        {"source_ref": "leaf_1", "target_ref": "leaf_2", "relation_type": "causes", "confidence": 0.8},
        {"source_ref": "leaf_1", "target_ref": "leaf_3", "relation_type": "causes", "confidence": 0.8},
    ]

    collected, edges, diagnostics = _collect([_outcome(1, leaves, relations)])

    assert [leaf.title for leaf in collected] == ["知识点 A"]
    assert edges == []
    assert diagnostics.dropped_leaves == 2
    assert diagnostics.relations_dropped == 2


def test_ambiguous_ref_is_discarded() -> None:
    leaves = [_leaf("leaf_1", "知识点 A"), _leaf("leaf_1", "知识点 B")]
    relations = [{"source_ref": "leaf_1", "target_ref": "leaf_1", "relation_type": "causes", "confidence": 0.8}]

    collected, edges, diagnostics = _collect([_outcome(1, leaves, relations)])

    assert len(collected) == 2
    assert edges == []
    # 自环先于 ref 解析被丢弃，只算一次
    assert diagnostics.relations_dropped == 1


def test_relations_are_capped_per_leaf() -> None:
    leaves = [_leaf(f"leaf_{index}", f"知识点 {index}") for index in range(1, 6)]
    relations = [
        {"source_ref": "leaf_1", "target_ref": f"leaf_{index}", "relation_type": "applies_to", "confidence": confidence}
        for index, confidence in ((2, 0.9), (3, 0.8), (4, 0.7), (5, 0.6))
    ]

    _, edges, diagnostics = _collect([_outcome(1, leaves, relations)])

    assert [edge.target_key for edge in edges] == [
        normalize_title_key("知识点 2"),
        normalize_title_key("知识点 3"),
        normalize_title_key("知识点 4"),
    ]
    assert all(edge.source_key == normalize_title_key("知识点 1") for edge in edges)
    assert diagnostics.relations_dropped == 1


def test_relation_evidence_is_trimmed() -> None:
    leaves = [_leaf("leaf_1", "知识点 A"), _leaf("leaf_2", "知识点 B")]
    relations = [
        {
            "source_ref": "leaf_1",
            "target_ref": "leaf_2",
            "relation_type": "causes",
            "confidence": 0.5,
            "evidence": "证据" * 300,
        }
    ]

    _, edges, _ = _collect([_outcome(1, leaves, relations)])

    assert len(edges) == 1
    assert len(edges[0].evidence or "") == 200


def test_schema_tolerates_malformed_relations() -> None:
    """字段写成字符串/对象/越界值时，schema 只做降级，不抛校验错误。"""
    extraction = KnowledgeSectionExtractionV5.model_validate(
        {
            "section_ref": "section",
            "leaves": [_leaf("leaf_1", "知识点 A"), _leaf("leaf_2", "知识点 B")],
            "relations": [
                {"source": "leaf_1", "target": "leaf_2", "type": "causes", "confidence": "high"},
                "not-a-relation",
                {"source_ref": None, "target_ref": ["leaf_2"], "relation_type": 7, "confidence": True},
            ],
        }
    )

    assert len(extraction.relations) == 2  # 字符串项被丢掉，对象项保留为非法关系
    assert extraction.relations[0].source_ref == ""
    assert extraction.relations[0].confidence == -1.0
    assert extraction.relations[1].relation_type == ""
    assert extraction.relations[1].evidence is None


def test_malformed_relations_never_reach_persistence() -> None:
    extraction = KnowledgeSectionExtractionV5.model_validate(
        {
            "section_ref": "section",
            "leaves": [_leaf("leaf_1", "知识点 A"), _leaf("leaf_2", "知识点 B")],
            "relations": [
                {"source_ref": "leaf_1", "target_ref": "leaf_9", "relation_type": "causes", "confidence": "high"},
                {"source_ref": "leaf_1", "target_ref": "leaf_2", "relation_type": "unknown_type", "confidence": 0.5},
            ],
        }
    )
    window = SectionWindow(
        window_index=1,
        chapter_index=1,
        section_index=1,
        section_path=["第1章 基础", "1.1 概述"],
        page_ranges=[("doc-1", 1, 5)],
        units=[],
        content_hash="hash-1",
        cache_key="cache-1",
        payload={},
    )
    outcome = WindowOutcome(window=window, ok=True, data=extraction, meta=WindowCallMeta())

    _, edges, diagnostics = _collect([outcome])

    assert edges == []
    assert diagnostics.relations_dropped == 2


# --------------------------------------------------------------------------
# 落库映射
# --------------------------------------------------------------------------


def test_persist_relations_drops_missing_endpoints_and_duplicates() -> None:
    repository = _RecordingRepository()
    pipeline = KnowledgeBuildPipeline(repository=repository)
    diagnostics = BuildDiagnostics()
    relations = [
        PendingRelation("a", "b", "causes", 0.9),
        PendingRelation("a", "b", "causes", 0.7),  # 同一节点边重复
        PendingRelation("a", "missing", "causes", 0.8),  # 端点未落库
        PendingRelation("a", "a", "causes", 0.8),  # 两端映射到同一节点
        PendingRelation("b", "c", "derives", 0.4),
    ]

    pipeline._persist_relations(
        None,
        version=SimpleNamespace(id="version-1"),
        relations=relations,
        node_version_ids={"a": "nv-a", "b": "nv-b", "c": "nv-c"},
        diagnostics=diagnostics,
    )

    assert [(row["source_node_version_id"], row["target_node_version_id"]) for row in repository.relations] == [
        ("nv-a", "nv-b"),
        ("nv-b", "nv-c"),
    ]
    assert diagnostics.relations_kept == 2
    assert diagnostics.relations_dropped == 3


def test_reverse_relation_rows_keep_direction_of_highest_confidence() -> None:
    window = SectionWindow(
        window_index=2,
        chapter_index=1,
        section_index=1,
        section_path=["第1章 基础", "1.1 概述"],
        page_ranges=[("doc-1", 1, 5)],
        units=[],
        content_hash="hash-2",
        cache_key="cache-2",
        payload={},
    )
    extraction = KnowledgeSectionExtractionV5(
        section_ref="section",
        leaves=[
            {"ref": "leaf_1", "title": "知识点 A", "content": LONG_CONTENT, "sources": [{"document_id": "doc-1", "page_number": 1}]},
            {"ref": "leaf_2", "title": "知识点 B", "content": LONG_CONTENT, "sources": [{"document_id": "doc-1", "page_number": 2}]},
        ],
        relations=[
            KnowledgeRelationV5(
                source_ref="leaf_1", target_ref="leaf_2", relation_type="prerequisite", confidence=0.4
            ),
            KnowledgeRelationV5(
                source_ref="leaf_2", target_ref="leaf_1", relation_type="prerequisite", confidence=0.9
            ),
        ],
    )

    _, edges, _ = _collect(
        [WindowOutcome(window=window, ok=True, data=extraction, meta=WindowCallMeta())]
    )

    assert [(edge.source_key, edge.target_key, edge.confidence) for edge in edges] == [
        (normalize_title_key("知识点 B"), normalize_title_key("知识点 A"), 0.9)
    ]
