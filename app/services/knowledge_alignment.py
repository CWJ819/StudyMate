"""跨文档叶子概念对齐（Stage C 纯函数）。

Stage B 按 section 独立抽取，教材的两份同一章文件会让同一概念在两个 section
各出现一次。这里在落库前把“同类概念”收成一个 canonical 叶：

1. **精确桶**：标题做 NFKC、casefold、删除全部空白（与大纲合并键同款）；
2. **模糊合并**：difflib 相似度 ≥ 0.90，且两侧 ASCII 字母数字骨架相同。
   不做子串合并：线上实测 "物理层" 会吞掉 "物理层机械特性/电气特性/编码违例"
   等不同概念；"NRZ编码" 与 "NRZI编码" 相似度高但骨架不同，也必须分开。

合并在 occurrence 级别进行；canonical 按“来源最多 → 最小主来源页 → 标题字典
序”确定性选取，sources 取并集，content 取最长。锁定对（用户显式指定“这两个
不是同一个概念”）会让整个候选簇退回为单叶，绝不合并。

本模块不读写数据库、不调 LLM，输出只由输入决定；别名锁由调用方读出后传入。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from unicodedata import normalize

from app.llm.schemas import KnowledgeSourceCandidate

DEFAULT_MAX_SOURCES = 6
FUZZY_RATIO_THRESHOLD = 0.90


@dataclass(frozen=True)
class AlignmentLeaf:
    """参与对齐的一片叶子；``origin`` 是它在调用方扁平序列里的下标。"""

    title: str
    content: str
    section_label: str | None
    sources: tuple[KnowledgeSourceCandidate, ...]
    section_path: tuple[str, ...]
    origin: int


@dataclass(frozen=True)
class AlignedLeaf:
    """对齐后保留的一片 canonical 叶。"""

    title: str
    content: str
    section_label: str | None
    sources: tuple[KnowledgeSourceCandidate, ...]
    section_path: tuple[str, ...]
    origin: int
    aliases: tuple[str, ...]
    distinct_documents: int
    merge_method: str | None = None
    similarity: float | None = None


@dataclass(frozen=True)
class MergeDecision:
    """一次真实发生的簇合并（只记录 >1 个 occurrence 的簇）。"""

    canonical_title: str
    aliases: tuple[str, ...]
    members: tuple[str, ...]
    distinct_documents: int
    method: str
    similarity: float | None
    section_path: tuple[str, ...]


@dataclass(frozen=True)
class AlignmentResult:
    leaves: tuple[AlignedLeaf, ...]
    decisions: tuple[MergeDecision, ...]
    # 原始标题 → canonical 标题；同一标题出现在两个不同簇时视为歧义、不写入。
    canonical_by_title: dict[str, str]


def align_leaves(
    leaves: list[AlignmentLeaf],
    *,
    locked_pairs: set[tuple[str, str]] | None = None,
    max_sources: int = DEFAULT_MAX_SOURCES,
) -> AlignmentResult:
    """把全部叶子 occurrence 收成 canonical 叶并返回合并决策。"""
    if not leaves:
        return AlignmentResult(leaves=(), decisions=(), canonical_by_title={})

    locked = {_pair_key(a, b) for a, b in (locked_pairs or set()) if a and b}
    groups: dict[str, list[int]] = {}
    for index, leaf in enumerate(leaves):
        groups.setdefault(_squash_title(leaf.title), []).append(index)
    group_items = sorted(groups.items(), key=lambda item: item[0])

    parent = list(range(len(group_items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    # 先按精确桶分组，再只在“没有锁定对”的桶之间做模糊合并。
    for left_index in range(len(group_items)):
        for right_index in range(left_index + 1, len(group_items)):
            left_key, left_members = group_items[left_index]
            right_key, right_members = group_items[right_index]
            if _groups_locked(left_members, right_members, leaves, locked):
                continue
            if not _fuzzy_match(left_key, right_key):
                continue
            union(left_index, right_index)

    clusters: dict[int, list[int]] = {}
    for group_index, (_, members) in enumerate(group_items):
        clusters.setdefault(find(group_index), []).extend(members)

    aligned: list[AlignedLeaf] = []
    decisions: list[MergeDecision] = []
    canonical_by_title: dict[str, str] = {}
    for members in sorted(clusters.values(), key=lambda values: min(values)):
        member_leaves = [leaves[index] for index in members]
        # 传递闭包可能把锁定对重新连到一起；此时整簇退回单叶，锁优先。
        if _cluster_locked(member_leaves, locked):
            for leaf in member_leaves:
                aligned.append(_singleton(leaf))
            continue
        if len(member_leaves) == 1:
            aligned.append(_singleton(member_leaves[0]))
            continue

        canonical = min(member_leaves, key=_canonical_sort_key)
        merged_sources = _merge_sources(member_leaves, max_sources=max_sources)
        longest = max(
            member_leaves,
            key=lambda leaf: (len(leaf.content or ""), leaf is canonical, -leaf.origin),
        )
        aliases = _unique_sorted(
            [leaf.title for leaf in member_leaves if leaf.title != canonical.title]
        )
        members_titles = _unique_sorted([leaf.title for leaf in member_leaves])
        exact = len({_squash_title(leaf.title) for leaf in member_leaves}) == 1
        similarity = None if exact else _max_similarity(member_leaves)
        method = "exact" if exact else "fuzzy"
        aligned.append(
            AlignedLeaf(
                title=canonical.title,
                content=longest.content,
                section_label=canonical.section_label,
                sources=tuple(merged_sources),
                section_path=canonical.section_path,
                origin=canonical.origin,
                aliases=tuple(aliases),
                distinct_documents=len({source.document_id for source in merged_sources}),
                merge_method=method,
                similarity=similarity,
            )
        )
        decisions.append(
            MergeDecision(
                canonical_title=canonical.title,
                aliases=tuple(aliases),
                members=tuple(members_titles),
                distinct_documents=len(
                    {source.document_id for source in merged_sources}
                ),
                method=method,
                similarity=similarity,
                section_path=canonical.section_path,
            )
        )
        for title in members_titles:
            previous = canonical_by_title.get(title)
            if previous is not None and previous != canonical.title:
                canonical_by_title.pop(title, None)
            else:
                canonical_by_title[title] = canonical.title

    # 同一原始标题若在两个簇里都是 canonical（锁定导致的歧义），不写入映射。
    counts: dict[str, set[str]] = {}
    for title, canonical in canonical_by_title.items():
        counts.setdefault(title, set()).add(canonical)
    canonical_by_title = {
        title: next(iter(canonicals))
        for title, canonicals in counts.items()
        if len(canonicals) == 1
    }
    aligned.sort(key=lambda leaf: leaf.origin)
    return AlignmentResult(
        leaves=tuple(aligned),
        decisions=tuple(decisions),
        canonical_by_title=canonical_by_title,
    )


def remap_relation_keys(
    relations: list,
    canonical_by_title: dict[str, str],
    *,
    normalize_key,
) -> list:
    """把关系的原始标题 key 改指 canonical；歧义端点保持原样（随后会丢边）。"""
    if not canonical_by_title:
        return relations
    # 关系 key 走 pipeline 的 normalize_key（保留词间空格），而对齐键是
    # “去全部空白”。用去空白键查表、用 normalize_key(canonical) 作值，
    # 否则 canonical 标题本身带空格时（如“拥塞 窗口”），别名 ref 会查不到。
    title_map = {
        _squash_title(title): normalize_key(canonical)
        for title, canonical in canonical_by_title.items()
    }
    remapped = []
    for relation in relations:
        source_key = title_map.get(
            _squash_title(relation.source_key), relation.source_key
        )
        target_key = title_map.get(
            _squash_title(relation.target_key), relation.target_key
        )
        remapped.append(
            type(relation)(
                source_key=source_key,
                target_key=target_key,
                relation_type=relation.relation_type,
                confidence=relation.confidence,
                evidence=relation.evidence,
            )
        )
    return remapped


def dedupe_relations(relations: list, *, diagnostics=None) -> list:
    """版本级按无序 (source,target,type) 去重，保留置信度最高的方向。"""
    best: dict[tuple[str, str, str], object] = {}
    dropped = 0
    for relation in relations:
        if relation.source_key == relation.target_key:
            dropped += 1
            continue
        key = (
            min(relation.source_key, relation.target_key),
            max(relation.source_key, relation.target_key),
            relation.relation_type,
        )
        existing = best.get(key)
        if existing is not None:
            dropped += 1
            if relation.confidence <= existing.confidence:
                continue
        best[key] = relation
    if diagnostics is not None:
        diagnostics.relations_dropped += dropped
    return list(best.values())


def _singleton(leaf: AlignmentLeaf) -> AlignedLeaf:
    return AlignedLeaf(
        title=leaf.title,
        content=leaf.content,
        section_label=leaf.section_label,
        sources=tuple(leaf.sources),
        section_path=leaf.section_path,
        origin=leaf.origin,
        aliases=(),
        distinct_documents=len({source.document_id for source in leaf.sources}),
    )


def _canonical_sort_key(leaf: AlignmentLeaf) -> tuple:
    unique_sources = _unique_sources(leaf.sources)
    primary = min(
        (
            (source.page_number, source.document_id, source.chunk_id or "")
            for source in unique_sources
        ),
        default=(0, "", ""),
    )
    return (
        -len(unique_sources),
        primary[0],
        primary[1],
        leaf.title.casefold(),
        leaf.title,
        leaf.origin,
    )


def _merge_sources(
    leaves: list[AlignmentLeaf], *, max_sources: int
) -> list[KnowledgeSourceCandidate]:
    merged: list[KnowledgeSourceCandidate] = []
    seen: set[tuple[str, int, str | None]] = set()
    for leaf in leaves:
        for source in leaf.sources:
            key = (source.document_id, source.page_number, source.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            merged.append(source)
    merged.sort(key=lambda source: (source.page_number, source.document_id))
    return merged[:max_sources]


def _unique_sources(
    sources: tuple[KnowledgeSourceCandidate, ...] | list[KnowledgeSourceCandidate],
) -> list[KnowledgeSourceCandidate]:
    seen: set[tuple[str, int, str | None]] = set()
    unique: list[KnowledgeSourceCandidate] = []
    for source in sources:
        key = (source.document_id, source.page_number, source.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def _groups_locked(
    left_members: list[int],
    right_members: list[int],
    leaves: list[AlignmentLeaf],
    locked: set[tuple[str, str]],
) -> bool:
    for left_index in left_members:
        for right_index in right_members:
            if _pair_key(leaves[left_index].title, leaves[right_index].title) in locked:
                return True
    return False


def _cluster_locked(
    leaves: list[AlignmentLeaf], locked: set[tuple[str, str]]
) -> bool:
    for index, left in enumerate(leaves):
        for right in leaves[index + 1 :]:
            if _pair_key(left.title, right.title) in locked:
                return True
    return False


def _fuzzy_match(left: str, right: str) -> bool:
    if not left or not right or left == right:
        return False
    ratio = SequenceMatcher(None, left, right).ratio()
    if ratio < FUZZY_RATIO_THRESHOLD:
        return False
    # NRZ编码 / NRZI编码 这类只差一个 ASCII 字符的标题相似度很高，但语义不同。
    left_ascii = _ascii_signature(left)
    right_ascii = _ascii_signature(right)
    if left_ascii and right_ascii and left_ascii != right_ascii:
        return False
    return True


def _ascii_signature(title: str) -> str:
    return "".join(
        character for character in title if character.isascii() and character.isalnum()
    ).casefold()


def _max_similarity(leaves: list[AlignmentLeaf]) -> float:
    best = 0.0
    for index, left in enumerate(leaves):
        for right in leaves[index + 1 :]:
            ratio = SequenceMatcher(
                None, _squash_title(left.title), _squash_title(right.title)
            ).ratio()
            if ratio > best:
                best = ratio
    return round(best, 4)


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted(set(values), key=lambda value: (value.casefold(), value))


def _squash_title(title: str) -> str:
    normalized = normalize("NFKC", title).casefold()
    return "".join(normalized.split())


def _pair_key(left: str, right: str) -> tuple[str, str]:
    first, second = _squash_title(left), _squash_title(right)
    return (first, second) if first <= second else (second, first)
