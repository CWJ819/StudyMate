"""知识点重要性 / 难度评分（读取时纯计算）。

对应设计文档公式的落地版：

    重要性 I = w1·E + w2·C + w3·F + w4·R
    难度   D = 0.5·前置链深度 + 0.3·前置入度 + 0.2·F

- **E 出处**（``source_pages``）：该叶 distinct 来源页数（document_id + page_number），
  即课件为它花了多少页。
- **C 关系中心性**（``relation_centrality``）：出边 ``prerequisite`` 记 2
  （“被依赖 = 基础性”），其余关联边（含入边与其他类型）记 1。
- **F 篇幅**（``content_length``）：content 字符数，教学投入的代理。
- **R 测验强化**（``quiz_reinforcement``）：``question_knowledge`` 中映射到该叶的
  题目数；还没有测验时全 0，公式优雅退化。

I 的四个分量各自除以全体叶子的最大值（该列全零则整列置 0）再加权，因此 I、D 都落在
[0, 1]。D 复用同一个归一化后的 F；前置链深度沿 ``prerequisite`` 边反向（从依赖者走向
被依赖者）取最长链，用记忆化 DFS + on-stack 集合防环——遇到环时按当前路径长度截断，
不会无限递归。

评分**只在读取时计算**：不写库、不调 LLM、不读构建缓存，所以与已冻结的构建结构完全
解耦；权重是模块常量，改权重不需要迁移或重建，下一次请求就生效。分数是工程估计值，
不是对课程内容的精确测量。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SCORING_VERSION = "scoring-v1"

# 重要性四分量权重（设计文档 I = w1E + w2C + w3F + w4R 的落地值）。
IMPORTANCE_WEIGHTS: dict[str, float] = {
    "source_pages": 0.3,
    "relation_centrality": 0.3,
    "content_length": 0.2,
    "quiz_reinforcement": 0.2,
}

# 难度三分量权重（0.5 前置链深度 + 0.3 前置入度 + 0.2 篇幅）。
DIFFICULTY_WEIGHTS: dict[str, float] = {
    "prerequisite_depth": 0.5,
    "prerequisite_in_degree": 0.3,
    "content_length": 0.2,
}

# 出边 prerequisite 的“基础性”加成；其余关联边记 1。
PREREQUISITE_EDGE_WEIGHT = 2

MAX_REASONS = 2

HIGHLIGHT_ORDERS = ("importance", "difficulty", "gap")
HIGHLIGHT_LIMIT_DEFAULT = 20
HIGHLIGHT_LIMIT_MAX = 50


@dataclass(frozen=True)
class LeafScoringInput:
    """一片叶子参与评分的最小事实集（由 service 从 active 版本聚合）。"""

    node_version_id: str
    content_length: int = 0
    source_pages: int = 0
    question_count: int = 0


@dataclass(frozen=True)
class RelationEdge:
    """版本作用域内的一条关系边（source 为 prerequisite 时表示“source 先于 target”）。"""

    source_node_version_id: str
    target_node_version_id: str
    relation_type: str


@dataclass(frozen=True)
class LeafScore:
    importance: float
    difficulty: float
    # 四分量原值（未归一化），供前端解释分数来源。
    components: dict[str, int]
    # 贡献最大的前两个分量（含原值、归一化值与加权贡献）。
    reasons: list[dict[str, int | float | str]]


@dataclass(frozen=True)
class HighlightCandidate:
    knowledge_node_id: str
    title: str
    section_path: list[str]
    importance: float
    difficulty: float
    mastery_estimate: float | None
    evidence_count: int
    reasons: list[dict[str, int | float | str]]


def score_leaves(
    leaves: Sequence[LeafScoringInput],
    relations: Sequence[RelationEdge],
) -> dict[str, LeafScore]:
    """给一片叶子算 importance / difficulty；输入为空时返回空字典。"""
    ordered: list[LeafScoringInput] = []
    seen: set[str] = set()
    for leaf in leaves:
        if leaf.node_version_id in seen:
            continue
        seen.add(leaf.node_version_id)
        ordered.append(leaf)
    if not ordered:
        return {}

    node_ids = [leaf.node_version_id for leaf in ordered]
    known = set(node_ids)

    source_pages = {leaf.node_version_id: max(0, int(leaf.source_pages)) for leaf in ordered}
    content_length = {leaf.node_version_id: max(0, int(leaf.content_length)) for leaf in ordered}
    question_count = {leaf.node_version_id: max(0, int(leaf.question_count)) for leaf in ordered}
    centrality = {node_id: 0 for node_id in node_ids}
    prerequisite_in_degree = {node_id: 0 for node_id in node_ids}

    for edge in relations:
        source = edge.source_node_version_id
        target = edge.target_node_version_id
        if source == target or source not in known or target not in known:
            continue
        if edge.relation_type == "prerequisite":
            centrality[source] += PREREQUISITE_EDGE_WEIGHT
            centrality[target] += 1
            prerequisite_in_degree[target] += 1
        else:
            centrality[source] += 1
            centrality[target] += 1

    depths = prerequisite_chain_depths(node_ids, relations)

    source_norm = _normalize(source_pages)
    centrality_norm = _normalize(centrality)
    length_norm = _normalize(content_length)
    quiz_norm = _normalize(question_count)
    depth_norm = _normalize(depths)
    in_degree_norm = _normalize(prerequisite_in_degree)

    scores: dict[str, LeafScore] = {}
    for leaf in ordered:
        node_id = leaf.node_version_id
        raw_components = {
            "source_pages": source_pages[node_id],
            "relation_centrality": centrality[node_id],
            "content_length": content_length[node_id],
            "quiz_reinforcement": question_count[node_id],
        }
        normalized = {
            "source_pages": source_norm[node_id],
            "relation_centrality": centrality_norm[node_id],
            "content_length": length_norm[node_id],
            "quiz_reinforcement": quiz_norm[node_id],
        }
        contributions = {
            name: IMPORTANCE_WEIGHTS[name] * normalized[name] for name in IMPORTANCE_WEIGHTS
        }
        importance = _clamp_unit(sum(contributions.values()))
        difficulty = _clamp_unit(
            DIFFICULTY_WEIGHTS["prerequisite_depth"] * depth_norm[node_id]
            + DIFFICULTY_WEIGHTS["prerequisite_in_degree"] * in_degree_norm[node_id]
            + DIFFICULTY_WEIGHTS["content_length"] * length_norm[node_id]
        )
        scores[node_id] = LeafScore(
            importance=round(importance, 4),
            difficulty=round(difficulty, 4),
            components=raw_components,
            reasons=_top_reasons(raw_components, normalized, contributions),
        )
    return scores


def prerequisite_chain_depths(
    leaf_ids: Sequence[str],
    relations: Sequence[RelationEdge],
) -> dict[str, int]:
    """沿 prerequisite 边反向的最长前置链长度。

    只统计两端都在 ``leaf_ids`` 里的 prerequisite 边。用记忆化 DFS；遇到指回当前
    DFS 栈上的节点的边（环）时，按当前路径长度截断，不继续递归。节点与前置边都按
    id 排序后遍历，因此同样的图一定得到同样的深度。
    """
    known = set(leaf_ids)
    parents: dict[str, list[str]] = {node_id: [] for node_id in sorted(known)}
    for edge in relations:
        if edge.relation_type != "prerequisite":
            continue
        source = edge.source_node_version_id
        target = edge.target_node_version_id
        if source == target or source not in known or target not in known:
            continue
        parents[target].append(source)
    for values in parents.values():
        values[:] = sorted(set(values))

    depths: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()

    def visit(node_id: str) -> int:
        if node_id in depths:
            return depths[node_id]
        if node_id in on_stack:
            # 兜底：环按当前路径长度计，不递归。
            return len(stack)
        on_stack.add(node_id)
        stack.append(node_id)
        best = 0
        for parent_id in parents[node_id]:
            if parent_id in on_stack:
                # 环：当前路径本身就是这条链的长度，不再往下走。
                candidate = len(stack)
            else:
                candidate = 1 + visit(parent_id)
            if candidate > best:
                best = candidate
        stack.pop()
        on_stack.discard(node_id)
        depths[node_id] = best
        return best

    for node_id in sorted(known):
        visit(node_id)
    return depths


def highlight_gap(importance: float, mastery_estimate: float | None) -> float | None:
    """gap = importance × (1 − mastery)；未测验没有 gap（不是 0）。"""
    if mastery_estimate is None:
        return None
    return round(importance * (1.0 - mastery_estimate), 6)


def rank_highlights(
    candidates: Sequence[HighlightCandidate],
    *,
    order: str = "importance",
    limit: int = HIGHLIGHT_LIMIT_DEFAULT,
) -> list[HighlightCandidate]:
    """排序并截断重难点候选。

    - importance / difficulty：降序，平手按另一维降序、标题、node id。
    - gap：有掌握度的在前且按 gap 降序；未测验的排后并保持 importance 降序
      （沿用“未测验 ≠ 薄弱”口径，不让未学过的叶子冒充最薄弱）。
    """
    if order not in HIGHLIGHT_ORDERS:
        raise ValueError(f"Unsupported highlight order: {order}")
    capped = max(0, min(int(limit), HIGHLIGHT_LIMIT_MAX))

    if order == "importance":
        ordered = sorted(
            candidates,
            key=lambda item: (
                -item.importance,
                -item.difficulty,
                item.title,
                item.knowledge_node_id,
            ),
        )
    elif order == "difficulty":
        ordered = sorted(
            candidates,
            key=lambda item: (
                -item.difficulty,
                -item.importance,
                item.title,
                item.knowledge_node_id,
            ),
        )
    else:
        tested = [item for item in candidates if item.mastery_estimate is not None]
        untested = [item for item in candidates if item.mastery_estimate is None]
        tested.sort(
            key=lambda item: (
                -(highlight_gap(item.importance, item.mastery_estimate) or 0.0),
                -item.importance,
                item.title,
                item.knowledge_node_id,
            )
        )
        untested.sort(
            key=lambda item: (
                -item.importance,
                -item.difficulty,
                item.title,
                item.knowledge_node_id,
            )
        )
        ordered = tested + untested
    return ordered[:capped]


def _normalize(values: Mapping[str, float]) -> dict[str, float]:
    """按最大值归一化；最大值不大于 0 时整列置 0（避免除零、全零分量不贡献）。"""
    if not values:
        return {}
    maximum = max(max(0.0, float(value)) for value in values.values())
    if maximum <= 0:
        return {key: 0.0 for key in values}
    return {
        key: _clamp_unit(float(value) / maximum) if float(value) > 0 else 0.0
        for key, value in values.items()
    }


def _top_reasons(
    raw: Mapping[str, int],
    normalized: Mapping[str, float],
    contributions: Mapping[str, float],
) -> list[dict[str, int | float | str]]:
    weights_order = list(IMPORTANCE_WEIGHTS)
    ranked = sorted(
        range(len(weights_order)),
        key=lambda index: (-contributions[weights_order[index]], index),
    )
    reasons: list[dict[str, int | float | str]] = []
    for index in ranked[:MAX_REASONS]:
        name = weights_order[index]
        reasons.append(
            {
                "component": name,
                "value": int(raw[name]),
                "normalized": round(normalized[name], 4),
                "contribution": round(contributions[name], 4),
            }
        )
    return reasons


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
