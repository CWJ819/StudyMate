"""Phase 4 跨文档对齐单测：精确/模糊、canonical 确定性、锁、来源并集、关系重映射。"""

from __future__ import annotations

from types import SimpleNamespace

from app.llm.schemas import KnowledgeSourceCandidate
from app.services.knowledge_alignment import (
    AlignmentLeaf,
    align_leaves,
    dedupe_relations,
    remap_relation_keys,
)


def _leaf(
    title: str,
    *,
    document_id: str = "doc-1",
    page_number: int = 1,
    content: str = "内容",
    origin: int = 0,
) -> AlignmentLeaf:
    return AlignmentLeaf(
        title=title,
        content=content,
        section_label="1.1",
        sources=(KnowledgeSourceCandidate(document_id=document_id, page_number=page_number),),
        section_path=("第一章", "1.1"),
        origin=origin,
    )


def _titles(result) -> list[str]:
    return [leaf.title for leaf in result.leaves]


def test_exact_whitespace_title_merges_and_unions_sources() -> None:
    first = _leaf("拥塞控制", document_id="doc-1", page_number=10, content="短", origin=0)
    second = _leaf("拥塞 控制", document_id="doc-2", page_number=20, content="更长的内容", origin=1)

    result = align_leaves([first, second])

    assert len(result.leaves) == 1
    merged = result.leaves[0]
    assert merged.title == "拥塞控制"
    assert merged.content == "更长的内容"
    assert merged.aliases == ("拥塞 控制",)
    assert merged.distinct_documents == 2
    assert merged.merge_method == "exact"
    assert merged.similarity is None
    assert [(source.document_id, source.page_number) for source in merged.sources] == [
        ("doc-1", 10),
        ("doc-2", 20),
    ]
    assert len(result.decisions) == 1
    assert result.decisions[0].method == "exact"
    assert result.decisions[0].members == ("拥塞 控制", "拥塞控制")
    assert result.decisions[0].distinct_documents == 2


def test_canonical_is_deterministic_and_prefers_more_sources() -> None:
    # 第一次出现带两条来源，第二次只有一条来源：来源多的 occurrence 胜出。
    first = AlignmentLeaf(
        title="慢启动",
        content="内容",
        section_label=None,
        sources=(
            KnowledgeSourceCandidate(document_id="doc-1", page_number=3),
            KnowledgeSourceCandidate(document_id="doc-2", page_number=4),
        ),
        section_path=("第一章",),
        origin=0,
    )
    second = _leaf("慢 启 动", document_id="doc-3", page_number=2, origin=1)

    result = align_leaves([first, second])

    assert len(result.leaves) == 1
    assert result.leaves[0].title == "慢启动"
    assert result.leaves[0].distinct_documents == 3
    assert result.leaves[0].aliases == ("慢 启 动",)


def test_short_substring_guard_does_not_merge_generic_terms() -> None:
    generic = _leaf("网络", document_id="doc-1", page_number=1, origin=0)
    specific = _leaf("计算机网络", document_id="doc-2", page_number=2, origin=1)

    result = align_leaves([generic, specific])

    assert sorted(_titles(result)) == ["网络", "计算机网络"]
    assert result.decisions == ()


def test_generic_layer_titles_are_not_fuzzy_merged() -> None:
    leaves = [
        _leaf("物理层", document_id="doc-1", page_number=1, origin=0),
        _leaf("物理层机械特性", document_id="doc-1", page_number=2, origin=1),
        _leaf("物理层电气特性", document_id="doc-1", page_number=3, origin=2),
        _leaf("数据链路层", document_id="doc-1", page_number=4, origin=3),
        _leaf("数据链路层服务类型", document_id="doc-1", page_number=5, origin=4),
    ]

    result = align_leaves(leaves)

    assert len(result.leaves) == 5
    assert result.decisions == ()


def test_fuzzy_ratio_0_9_merges_satellite_title() -> None:
    first = _leaf("卫星通信传播特点与局限", document_id="doc-1", page_number=1, origin=0)
    second = _leaf("卫星通信特点与局限", document_id="doc-2", page_number=2, origin=1)

    result = align_leaves([first, second])

    assert len(result.leaves) == 1
    assert result.leaves[0].merge_method == "fuzzy"
    assert result.leaves[0].similarity == 0.9
    assert result.leaves[0].aliases == ("卫星通信特点与局限",)


def test_ascii_near_duplicate_is_not_merged() -> None:
    first = _leaf("NRZ编码", document_id="doc-1", page_number=1, origin=0)
    second = _leaf("NRZI编码", document_id="doc-1", page_number=2, origin=1)

    result = align_leaves([first, second])

    assert sorted(_titles(result)) == ["NRZI编码", "NRZ编码"]
    assert result.decisions == ()


def test_alias_lock_keeps_conflicting_leaves_apart() -> None:
    first = _leaf("滑动窗口", document_id="doc-1", page_number=1, origin=0)
    second = _leaf("滑动窗口", document_id="doc-2", page_number=2, origin=1)

    result = align_leaves([first, second], locked_pairs={("滑动窗口", "滑动窗口")})

    assert len(result.leaves) == 2
    assert result.decisions == ()
    assert result.canonical_by_title == {}


def test_canonical_by_title_maps_all_aliases_for_remapping() -> None:
    first = _leaf("拥塞窗口", document_id="doc-1", page_number=1, origin=0)
    second = _leaf("拥塞 窗口", document_id="doc-2", page_number=2, origin=1)

    result = align_leaves([first, second])

    assert result.canonical_by_title == {"拥塞窗口": "拥塞窗口", "拥塞 窗口": "拥塞窗口"}

    relations = [
        SimpleNamespace(
            source_key="拥塞 窗口",
            target_key="慢启动",
            relation_type="prerequisite",
            confidence=0.8,
            evidence=None,
        )
    ]
    remapped = remap_relation_keys(
        relations,
        result.canonical_by_title,
        normalize_key=lambda title: "".join(title.casefold().split()),
    )

    assert remapped[0].source_key == "拥塞窗口"
    assert remapped[0].target_key == "慢启动"


def test_remap_relation_keys_handles_spaced_canonical_title() -> None:
    first = _leaf("拥塞 窗口", document_id="doc-1", page_number=1, origin=0)
    second = _leaf("拥塞窗口", document_id="doc-2", page_number=2, origin=1)

    result = align_leaves([first, second])

    # 页码更小的带空格标题胜出；关系 key 的规范化保留词间空格，因此
    # 必须用去空白键查表，否则别名 ref 会漏掉。
    assert result.canonical_by_title["拥塞窗口"] == "拥塞 窗口"
    relations = [
        SimpleNamespace(
            source_key="拥塞窗口",
            target_key="慢启动",
            relation_type="prerequisite",
            confidence=0.8,
            evidence=None,
        )
    ]
    remapped = remap_relation_keys(
        relations,
        result.canonical_by_title,
        normalize_key=lambda title: " ".join(title.casefold().split()),
    )

    assert remapped[0].source_key == "拥塞 窗口"


def test_dedupe_relations_is_unordered_and_keeps_highest_confidence() -> None:
    relations = [
        SimpleNamespace(
            source_key="a", target_key="b", relation_type="causes", confidence=0.6, evidence="x"
        ),
        SimpleNamespace(
            source_key="b", target_key="a", relation_type="causes", confidence=0.9, evidence="y"
        ),
        SimpleNamespace(
            source_key="a", target_key="b", relation_type="derives", confidence=0.7, evidence="z"
        ),
    ]

    result = dedupe_relations(relations)

    assert len(result) == 2
    by_type = {relation.relation_type: relation for relation in result}
    assert by_type["causes"].source_key == "b"
    assert by_type["causes"].target_key == "a"
    assert by_type["causes"].evidence == "y"
    assert by_type["derives"].confidence == 0.7


def test_self_relations_and_max_sources_are_handled() -> None:
    leaf = _leaf(
        "窗口",
        document_id="doc-1",
        page_number=1,
        origin=0,
    )
    many_sources = AlignmentLeaf(
        title="窗口",
        content="内容",
        section_label=None,
        sources=tuple(
            KnowledgeSourceCandidate(document_id=f"doc-{index}", page_number=index)
            for index in range(1, 9)
        ),
        section_path=("第一章",),
        origin=0,
    )

    result = align_leaves([leaf, many_sources], max_sources=6)

    assert len(result.leaves[0].sources) == 6
    assert [source.page_number for source in result.leaves[0].sources] == [1, 2, 3, 4, 5, 6]

    relation = SimpleNamespace(
        source_key="窗口", target_key="窗口", relation_type="causes", confidence=0.5, evidence=None
    )
    assert dedupe_relations([relation]) == []
