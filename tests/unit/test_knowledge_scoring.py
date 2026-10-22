"""Phase 3 评分单测：归一化、空数据退化、前置链深度（链/分叉/环）、排序与 untested。"""

import pytest

from app.services.knowledge_scoring import (
    DIFFICULTY_WEIGHTS,
    HIGHLIGHT_LIMIT_MAX,
    HIGHLIGHT_ORDERS,
    IMPORTANCE_WEIGHTS,
    SCORING_VERSION,
    HighlightCandidate,
    LeafScoringInput,
    RelationEdge,
    highlight_gap,
    prerequisite_chain_depths,
    rank_highlights,
    score_leaves,
)


def _leaf(
    node_id: str,
    *,
    pages: int = 1,
    content: int = 100,
    questions: int = 0,
) -> LeafScoringInput:
    return LeafScoringInput(
        node_version_id=node_id,
        content_length=content,
        source_pages=pages,
        question_count=questions,
    )


def _candidate(
    node_id: str,
    *,
    importance: float,
    difficulty: float = 0.5,
    mastery: float | None = None,
    title: str | None = None,
) -> HighlightCandidate:
    return HighlightCandidate(
        knowledge_node_id=node_id,
        title=title or node_id,
        section_path=["第1章 基础"],
        importance=importance,
        difficulty=difficulty,
        mastery_estimate=mastery,
        evidence_count=0 if mastery is None else 2,
        reasons=[],
    )


# --------------------------------------------------------------------------
# 权重与版本
# --------------------------------------------------------------------------


def test_weights_sum_to_one_and_scoring_version_is_pinned() -> None:
    assert sum(IMPORTANCE_WEIGHTS.values()) == pytest.approx(1.0)
    assert sum(DIFFICULTY_WEIGHTS.values()) == pytest.approx(1.0)
    assert set(IMPORTANCE_WEIGHTS) == {
        "source_pages",
        "relation_centrality",
        "content_length",
        "quiz_reinforcement",
    }
    assert set(DIFFICULTY_WEIGHTS) == {
        "prerequisite_depth",
        "prerequisite_in_degree",
        "content_length",
    }
    assert SCORING_VERSION == "scoring-v1"
    assert HIGHLIGHT_ORDERS == ("importance", "difficulty", "gap")


# --------------------------------------------------------------------------
# 归一化与退化
# --------------------------------------------------------------------------


def test_components_are_normalized_by_leaf_maximum() -> None:
    scores = score_leaves(
        [_leaf("a", pages=10, content=100), _leaf("b", pages=4, content=100)],
        [],
    )

    assert scores["a"].components == {
        "source_pages": 10,
        "relation_centrality": 0,
        "content_length": 100,
        "quiz_reinforcement": 0,
    }
    # a: 0.3·1 + 0.2·1 = 0.5；b: 0.3·0.4 + 0.2·1 = 0.32（篇幅相同，都拿满分）
    assert scores["a"].importance == pytest.approx(0.5)
    assert scores["b"].importance == pytest.approx(0.32)
    # 没有关系时难度只剩篇幅项
    assert scores["a"].difficulty == pytest.approx(0.2)
    assert scores["b"].difficulty == pytest.approx(0.2)


def test_all_zero_component_does_not_divide_by_zero() -> None:
    scores = score_leaves(
        [_leaf("a", pages=0, content=0), _leaf("b", pages=0, content=5)],
        [],
    )

    assert scores["a"].importance == 0.0
    assert scores["a"].difficulty == 0.0
    assert scores["b"].components["source_pages"] == 0
    assert scores["b"].importance == pytest.approx(0.2)


def test_empty_inputs_degrade_to_empty_scores() -> None:
    assert score_leaves([], []) == {}
    assert prerequisite_chain_depths([], []) == {}


def test_quiz_reinforcement_boosts_importance() -> None:
    scores = score_leaves(
        [
            _leaf("tested", questions=3),
            _leaf("untested", questions=0),
        ],
        [],
    )

    assert scores["tested"].importance > scores["untested"].importance
    assert scores["tested"].components["quiz_reinforcement"] == 3
    # 未测验不是负分：untested 仍有出处与篇幅贡献
    assert scores["untested"].importance == pytest.approx(0.5)


# --------------------------------------------------------------------------
# 关系中心性与前置链
# --------------------------------------------------------------------------


def test_prerequisite_out_edges_make_a_leaf_foundational() -> None:
    scores = score_leaves(
        [_leaf("a"), _leaf("b")],
        [RelationEdge("a", "b", "prerequisite")],
    )

    assert scores["a"].components["relation_centrality"] == 2
    assert scores["b"].components["relation_centrality"] == 1
    assert scores["a"].importance > scores["b"].importance
    # b 有一个前置 → 难度更高；a 的前置链与入度都是 0
    assert scores["b"].difficulty > scores["a"].difficulty


def test_chain_depths_follow_prerequisite_edges_backwards() -> None:
    edges = [
        RelationEdge("a", "b", "prerequisite"),
        RelationEdge("b", "c", "prerequisite"),
    ]

    depths = prerequisite_chain_depths(["a", "b", "c"], edges)

    assert depths == {"a": 0, "b": 1, "c": 2}


def test_fork_keeps_both_branches() -> None:
    edges = [
        RelationEdge("a", "b", "prerequisite"),
        RelationEdge("a", "c", "prerequisite"),
    ]

    assert prerequisite_chain_depths(["a", "b", "c"], edges) == {
        "a": 0,
        "b": 1,
        "c": 1,
    }


def test_cycle_is_bounded_deterministic_and_order_independent() -> None:
    edges = [
        RelationEdge("a", "b", "prerequisite"),
        RelationEdge("b", "c", "prerequisite"),
        RelationEdge("c", "a", "prerequisite"),
    ]

    first = prerequisite_chain_depths(["a", "b", "c"], edges)
    second = prerequisite_chain_depths(["c", "b", "a"], edges)

    assert first == second  # 节点按 id 排序后遍历，与调用方顺序无关
    assert set(first) == {"a", "b", "c"}
    assert all(0 <= value <= 2 * len(edges) for value in first.values())
    assert max(first.values()) > 0  # 环被计成路径长度，而不是一律截成 0


def test_non_prerequisite_edges_do_not_affect_depth() -> None:
    edges = [
        RelationEdge("a", "b", "causes"),
        RelationEdge("b", "c", "derives"),
        RelationEdge("a", "c", "contrasts_with"),
    ]

    assert prerequisite_chain_depths(["a", "b", "c"], edges) == {
        "a": 0,
        "b": 0,
        "c": 0,
    }


def test_edges_with_unknown_endpoints_are_ignored() -> None:
    scores = score_leaves(
        [_leaf("a"), _leaf("b")],
        [
            RelationEdge("a", "ghost", "prerequisite"),
            RelationEdge("a", "a", "prerequisite"),
        ],
    )

    assert scores["a"].components["relation_centrality"] == 0
    assert scores["b"].components["relation_centrality"] == 0


# --------------------------------------------------------------------------
# 可解释性
# --------------------------------------------------------------------------


def test_reasons_report_top_two_components_with_raw_and_normalized_values() -> None:
    scores = score_leaves(
        [_leaf("a", pages=10, content=400), _leaf("b", pages=2, content=100)],
        [],
    )

    reasons = scores["a"].reasons
    assert [reason["component"] for reason in reasons] == [
        "source_pages",
        "content_length",
    ]
    assert reasons[0]["value"] == 10
    assert reasons[0]["normalized"] == pytest.approx(1.0)
    assert reasons[0]["contribution"] == pytest.approx(0.3)
    assert reasons[1]["value"] == 400
    assert reasons[1]["contribution"] == pytest.approx(0.2)


def test_reasons_fall_back_to_weight_order_when_everything_is_zero() -> None:
    scores = score_leaves([_leaf("a", pages=0, content=0)], [])

    assert [reason["component"] for reason in scores["a"].reasons] == [
        "source_pages",
        "relation_centrality",
    ]
    assert all(reason["contribution"] == 0.0 for reason in scores["a"].reasons)


# --------------------------------------------------------------------------
# 排序
# --------------------------------------------------------------------------


def test_importance_order_is_deterministic_with_title_tiebreak() -> None:
    candidates = [
        _candidate("b", importance=0.5, title="B"),
        _candidate("a", importance=0.5, title="A"),
        _candidate("c", importance=0.9, title="C"),
    ]

    ranked = rank_highlights(candidates, order="importance", limit=10)

    assert [item.knowledge_node_id for item in ranked] == ["c", "a", "b"]


def test_difficulty_order_uses_importance_as_tiebreak() -> None:
    candidates = [
        _candidate("low", importance=0.2, difficulty=0.9),
        _candidate("high", importance=0.9, difficulty=0.4),
        _candidate("tie", importance=0.5, difficulty=0.9),
    ]

    ranked = rank_highlights(candidates, order="difficulty", limit=10)

    assert [item.knowledge_node_id for item in ranked] == ["tie", "low", "high"]


def test_gap_order_puts_tested_first_and_untested_last() -> None:
    candidates = [
        _candidate("untested-high", importance=0.95),
        _candidate("weak", importance=0.5, mastery=0.1),  # gap 0.45
        _candidate("comfortable", importance=0.9, mastery=0.8),  # gap 0.18
        _candidate("untested-low", importance=0.3),
    ]

    ranked = rank_highlights(candidates, order="gap", limit=10)

    assert [item.knowledge_node_id for item in ranked] == [
        "weak",
        "comfortable",
        "untested-high",
        "untested-low",
    ]
    assert highlight_gap(0.5, 0.1) == pytest.approx(0.45)
    assert highlight_gap(0.5, None) is None


def test_gap_order_degrades_to_importance_when_nothing_is_tested() -> None:
    candidates = [
        _candidate("a", importance=0.2),
        _candidate("b", importance=0.8),
        _candidate("c", importance=0.5),
    ]

    by_gap = rank_highlights(candidates, order="gap", limit=10)
    by_importance = rank_highlights(candidates, order="importance", limit=10)

    assert [item.knowledge_node_id for item in by_gap] == [
        item.knowledge_node_id for item in by_importance
    ]


def test_limit_is_capped_and_invalid_order_is_rejected() -> None:
    candidates = [_candidate(f"node-{index}", importance=index / 100) for index in range(80)]

    assert len(rank_highlights(candidates, limit=999)) == HIGHLIGHT_LIMIT_MAX
    assert rank_highlights(candidates, limit=0) == []

    with pytest.raises(ValueError):
        rank_highlights(candidates, order="random")
