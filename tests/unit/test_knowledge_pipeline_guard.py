"""Stage C 版本级唯一守卫与关系版本级去重的单测。"""

from __future__ import annotations

from types import SimpleNamespace

from app.llm.schemas import KnowledgeSourceCandidate
from app.services.knowledge_alignment import MergeDecision
from app.services.knowledge_pipeline import (
    BuildDiagnostics,
    IdentityResolver,
    KnowledgeBuildPipeline,
    PendingLeaf,
    PendingRelation,
)


class _FakeSession:
    def get(self, model, node_id):  # pragma: no cover - 守卫路径不会用到复用
        return None


class _FakeRepository:
    def __init__(self) -> None:
        self.nodes_by_key: dict[str, SimpleNamespace] = {}
        self.versions: list[SimpleNamespace] = []
        self.sources: list[dict] = []
        self.relations: list[dict] = []
        self.decisions: list[dict] = []
        self._node_counter = 0
        self._version_counter = 0

    def find_node_by_stable_key(self, session, *, course_id, stable_key):
        return self.nodes_by_key.get(stable_key)

    def get_or_create_node(self, session, *, course_id, stable_key):
        node = self.nodes_by_key.get(stable_key)
        if node is None:
            self._node_counter += 1
            node = SimpleNamespace(id=f"node-{self._node_counter}", stable_key=stable_key)
            self.nodes_by_key[stable_key] = node
        return node

    def update_node_stable_key(self, session, *, knowledge_node, stable_key):
        knowledge_node.stable_key = stable_key

    def add_node_version(self, session, **kwargs):
        self._version_counter += 1
        version = SimpleNamespace(id=f"version-{self._version_counter}", **kwargs)
        self.versions.append(version)
        return version

    def add_source(self, session, **kwargs):
        self.sources.append(kwargs)

    def add_relation(self, session, **kwargs):
        self.relations.append(kwargs)

    def add_merge_decision(self, session, **kwargs):
        self.decisions.append(kwargs)


def _leaf(title: str, *, page: int = 10) -> PendingLeaf:
    return PendingLeaf(
        title=title,
        content="拥塞控制通过调整发送速率避免网络过载。",
        section_label=None,
        sources=[KnowledgeSourceCandidate(document_id="doc-1", page_number=page)],
    )


def _persist(repository: _FakeRepository, leaves: list[PendingLeaf], **kwargs):
    pipeline = KnowledgeBuildPipeline(repository=repository)
    diagnostics = BuildDiagnostics()
    node_version_ids: dict[str, str] = {}
    node_version_by_node_id: dict[str, str] = {}
    persisted: set[str] = set()
    pipeline._persist_leaves(
        _FakeSession(),
        course=SimpleNamespace(id="course-1"),
        version=SimpleNamespace(id="framework-1"),
        parent_id=kwargs.get("parent_id", "parent-1"),
        level=3,
        leaves=leaves,
        resolver=IdentityResolver([]),
        diagnostics=diagnostics,
        node_version_ids=node_version_ids,
        node_version_by_node_id=node_version_by_node_id,
        persisted_leaf_node_ids=persisted,
    )
    return diagnostics, node_version_ids, persisted


def test_same_stable_key_is_persisted_only_once_per_version() -> None:
    repository = _FakeRepository()
    pipeline = KnowledgeBuildPipeline(repository=repository)
    diagnostics = BuildDiagnostics()
    node_version_ids: dict[str, str] = {}
    node_version_by_node_id: dict[str, str] = {}
    persisted: set[str] = set()

    def persist_once(parent_id: str) -> None:
        pipeline._persist_leaves(
            _FakeSession(),
            course=SimpleNamespace(id="course-1"),
            version=SimpleNamespace(id="framework-1"),
            parent_id=parent_id,
            level=3,
            leaves=[_leaf("拥塞控制")],
            resolver=IdentityResolver([]),
            diagnostics=diagnostics,
            node_version_ids=node_version_ids,
            node_version_by_node_id=node_version_by_node_id,
            persisted_leaf_node_ids=persisted,
        )

    persist_once("parent-1")
    assert diagnostics.duplicate_leaf_occurrences == 0
    assert len(repository.versions) == 1
    first_version_id = next(iter(node_version_ids.values()))

    persist_once("parent-2")

    assert len(repository.versions) == 1
    assert diagnostics.duplicate_leaf_occurrences == 1
    assert node_version_ids["拥塞控制"] == first_version_id
    assert len(persisted) == 1
    assert len(repository.sources) == 1


def test_different_source_page_keeps_same_title_as_distinct_nodes() -> None:
    repository = _FakeRepository()

    _persist(repository, [_leaf("拥塞控制", page=10)])
    diagnostics, mapping, _ = _persist(repository, [_leaf("拥塞控制", page=20)])

    assert len(repository.versions) == 2
    assert diagnostics.duplicate_leaf_occurrences == 0
    assert mapping["拥塞控制"] == next(iter(mapping.values()))


def test_version_level_relations_dedupe_unordered_endpoints() -> None:
    repository = _FakeRepository()
    pipeline = KnowledgeBuildPipeline(repository=repository)
    diagnostics = BuildDiagnostics()
    relations = [
        PendingRelation("a", "b", "causes", 0.6),
        PendingRelation("b", "a", "causes", 0.9, evidence="更高置信度"),
        PendingRelation("a", "b", "derives", 0.7),
        PendingRelation("a", "ghost", "causes", 0.8),
        PendingRelation("a", "a", "causes", 0.8),
    ]

    pipeline._persist_relations(
        _FakeSession(),
        version=SimpleNamespace(id="framework-1"),
        relations=relations,
        node_version_ids={"a": "va", "b": "vb"},
        diagnostics=diagnostics,
    )

    assert diagnostics.relations_kept == 2
    assert diagnostics.relations_dropped == 3
    assert len(repository.relations) == 2
    causes = next(row for row in repository.relations if row["relation_type"] == "causes")
    assert causes["source_node_version_id"] == "vb"
    assert causes["target_node_version_id"] == "va"
    assert causes["confidence"] == 0.9


def test_merge_decisions_are_persisted() -> None:
    repository = _FakeRepository()
    pipeline = KnowledgeBuildPipeline(repository=repository)
    diagnostics = BuildDiagnostics(
        merge_decisions=[
            MergeDecision(
                canonical_title="拥塞控制",
                aliases=("拥塞 控制",),
                members=("拥塞 控制", "拥塞控制"),
                distinct_documents=2,
                method="exact",
                similarity=None,
                section_path=("第一章", "1.2"),
            )
        ]
    )

    pipeline._persist_merge_decisions(
        _FakeSession(),
        version=SimpleNamespace(id="framework-1"),
        diagnostics=diagnostics,
    )

    assert repository.decisions == [
        {
            "framework_version_id": "framework-1",
            "canonical_title": "拥塞控制",
            "aliases": ["拥塞 控制"],
            "members": ["拥塞 控制", "拥塞控制"],
            "distinct_documents": 2,
            "method": "exact",
            "similarity": None,
        }
    ]
