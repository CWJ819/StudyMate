"""Phase 4 集成测试：跨 section 概念对齐、别名锁与读取层去重。

mock 大纲用 PDF 书签，section 抽取用自定义 adapter；两个 section 故意返回
只差空白的同一概念，验证 Stage C 合并、别名、决策行与锁定生效。
"""

import asyncio
import uuid
from pathlib import Path

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
from app.db.models.knowledge import (
    KnowledgeFrameworkVersion,
    KnowledgeNode,
    KnowledgeNodeRelation,
    KnowledgeNodeVersion,
)
from app.db.session import session_scope
from app.llm.schemas import (
    KnowledgeSectionExtractionV5,
    LLMRunSummary,
    LLMStructuredResult,
)
from app.main import app
from app.repositories.knowledge_repository import KnowledgeRepository


def _create_pdf(path: Path) -> None:
    document = fitz.open()
    texts = [
        "第1章 传输层",
        "TCP 拥塞控制通过慢启动和拥塞避免调整发送速率。",
        "发送方维护拥塞窗口，避免网络过载。",
        "TCP拥塞控制还依赖快速重传与快速恢复。",
    ]
    for text in texts:
        page = document.new_page()
        page.insert_text((72, 72), text, fontname="china-s")
        page.insert_text(
            (72, 110),
            "本页补充正文内容，用于生成足够长度的文本块。",
            fontname="china-s",
        )
    document.set_toc(
        [
            [1, "第1章 传输层", 1],
            [2, "1.1 拥塞控制窗口", 2],
            [2, "1.2 拥塞控制算法", 4],
        ]
    )
    document.save(path)
    document.close()


async def _wait_for_job(client: AsyncClient, job_id: str) -> dict:
    last_body: dict | None = None
    for _ in range(200):
        response = await client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        last_body = response.json()
        if last_body["status"] in {"succeeded", "failed", "cancelled"}:
            return last_body
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {last_body}")


async def _create_course(client: AsyncClient, name: str) -> str:
    response = await client.post("/api/courses", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_pdf(client: AsyncClient, course_id: str, path: Path) -> None:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/courses/{course_id}/materials",
            files={"file": (path.name, handle, "application/pdf")},
        )
    assert response.status_code == 201
    job = await _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"


async def _build(client: AsyncClient, course_id: str) -> dict:
    response = await client.post(f"/api/courses/{course_id}/knowledge/build", json={})
    assert response.status_code == 202
    body = response.json()
    job = await _wait_for_job(client, body["job_id"])
    assert job["status"] == "succeeded"
    return body


def _collect_leaves(nodes: list[dict]) -> list[dict]:
    leaves: list[dict] = []
    for node in nodes:
        if node["is_leaf"]:
            leaves.append(node)
        else:
            leaves.extend(_collect_leaves(node.get("children", [])))
    return leaves


class DuplicateConceptAdapter:
    """两个 section 返回只差空白的同一个概念。"""

    def ensure_available(self) -> None:
        return None

    def generate_structured_output(self, **kwargs) -> LLMStructuredResult:
        payload = kwargs["user_payload"]
        section_title = payload["section_path"][-1]
        segment = payload["source_segments"][0]
        title = "TCP 拥塞控制" if section_title.startswith("1.1") else "TCP拥塞控制"
        data = KnowledgeSectionExtractionV5.model_validate(
            {
                "section_ref": section_title,
                "leaves": [
                    {
                        "ref": "leaf_1",
                        "title": title,
                        "content": (
                            "TCP 拥塞控制通过慢启动、拥塞避免、快速重传和快速恢复"
                            "调整发送速率，避免网络过载。"
                        ),
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
                "relations": [],
            }
        )
        return LLMStructuredResult(
            summary=LLMRunSummary(
                model_name="test-model",
                prompt_version=kwargs["prompt_version"],
                provider="test",
            ),
            data=data,
        )


@pytest.mark.anyio
async def test_cross_section_whitespace_variants_align_to_one_leaf(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage8")
    monkeypatch.setattr(
        "app.services.knowledge_service.get_llm_adapter",
        lambda: DuplicateConceptAdapter(),
    )
    reset_settings_cache()

    pdf_path = tmp_path / "transport.pdf"
    _create_pdf(pdf_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, "Alignment")
        await _upload_pdf(client, course_id, pdf_path)
        await _build(client, course_id)

        framework = (await client.get(f"/api/courses/{course_id}/knowledge")).json()
        leaves = _collect_leaves(framework["tree"])
        assert len(leaves) == 1
        leaf = leaves[0]
        assert leaf["title"] == "TCP 拥塞控制"

        detail = (
            await client.get(f"/api/knowledge/{leaf['knowledge_node_id']}")
        ).json()
        assert detail["aliases"] == ["TCP拥塞控制"]

        decisions = (
            await client.get(f"/api/courses/{course_id}/knowledge/merge-decisions")
        ).json()
        assert len(decisions["decisions"]) == 1
        decision = decisions["decisions"][0]
        assert decision["canonical_title"] == "TCP 拥塞控制"
        assert decision["aliases"] == ["TCP拥塞控制"]
        assert decision["method"] == "exact"
        assert decision["distinct_documents"] == 1

    reset_settings_cache()


@pytest.mark.anyio
async def test_alias_lock_keeps_variants_separate(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage8")
    monkeypatch.setattr(
        "app.services.knowledge_service.get_llm_adapter",
        lambda: DuplicateConceptAdapter(),
    )
    reset_settings_cache()

    pdf_path = tmp_path / "transport.pdf"
    _create_pdf(pdf_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, "Locked")
        lock_payload = {"title_a": "TCP 拥塞控制", "title_b": "TCP拥塞控制"}
        first = await client.post(
            f"/api/courses/{course_id}/knowledge/alias-locks", json=lock_payload
        )
        second = await client.post(
            f"/api/courses/{course_id}/knowledge/alias-locks", json=lock_payload
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["title_a"] == "TCP 拥塞控制"

        await _upload_pdf(client, course_id, pdf_path)
        await _build(client, course_id)

        framework = (await client.get(f"/api/courses/{course_id}/knowledge")).json()
        assert len(_collect_leaves(framework["tree"])) == 2
        decisions = (
            await client.get(f"/api/courses/{course_id}/knowledge/merge-decisions")
        ).json()
        assert decisions["decisions"] == []

        deleted = await client.post(
            f"/api/courses/{course_id}/knowledge/alias-locks/delete",
            json=lock_payload,
        )
        assert deleted.status_code == 204
        deleted_again = await client.delete(
            f"/api/courses/{course_id}/knowledge/alias-locks",
            params={"title_a": "TCP 拥塞控制", "title_b": "TCP拥塞控制"},
        )
        assert deleted_again.status_code == 204

    reset_settings_cache()


@pytest.mark.anyio
async def test_read_layer_dedupes_legacy_duplicate_versions_and_edges(
    migrated_database_url: str,
) -> None:
    """旧数据可能同一版本里一个 node 多行 version、同一逻辑边多行。

    读取层必须按 knowledge_node_id 去重，边按 (source,target,type) 去重。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, "Legacy")

    first_node_id = str(uuid.uuid4())
    second_node_id = str(uuid.uuid4())
    with session_scope() as session:
        framework = KnowledgeFrameworkVersion(
            id=str(uuid.uuid4()),
            course_id=course_id,
            version_number=1,
            status="active",
        )
        framework_id = framework.id
        session.add(framework)
        session.flush()

        root_node_id = str(uuid.uuid4())
        session.add_all(
            [
                KnowledgeNode(
                    id=root_node_id,
                    course_id=course_id,
                    stable_key=f"v1:{uuid.uuid4()}",
                ),
                KnowledgeNode(
                    id=first_node_id,
                    course_id=course_id,
                    stable_key=f"v1:{uuid.uuid4()}",
                ),
                KnowledgeNode(
                    id=second_node_id,
                    course_id=course_id,
                    stable_key=f"v1:{uuid.uuid4()}",
                ),
            ]
        )
        session.flush()

        root_version = KnowledgeNodeVersion(
            id=str(uuid.uuid4()),
            framework_version_id=framework.id,
            knowledge_node_id=root_node_id,
            title="第一章",
            level=1,
            is_leaf=False,
            sort_order=0,
        )
        session.add(root_version)
        session.flush()

        versions = [
            KnowledgeNodeVersion(
                id=str(uuid.uuid4()),
                framework_version_id=framework.id,
                knowledge_node_id=first_node_id,
                parent_id=root_version.id,
                title="TCP 拥塞控制",
                aliases=["TCP拥塞控制"],
                level=2,
                is_leaf=True,
                sort_order=0,
            )
            for _ in range(2)
        ] + [
            KnowledgeNodeVersion(
                id=str(uuid.uuid4()),
                framework_version_id=framework.id,
                knowledge_node_id=second_node_id,
                parent_id=root_version.id,
                title="慢启动",
                level=2,
                is_leaf=True,
                sort_order=1,
            )
            for _ in range(2)
        ]
        session.add_all(versions)
        session.flush()

        first_versions = versions[:2]
        second_versions = versions[2:]
        for index, relation_type in enumerate(["prerequisite", "prerequisite"]):
            session.add(
                KnowledgeNodeRelation(
                    id=str(uuid.uuid4()),
                    framework_version_id=framework.id,
                    source_node_version_id=first_versions[index].id,
                    target_node_version_id=second_versions[index].id,
                    relation_type=relation_type,
                    confidence=0.9 - index * 0.1,
                )
            )
        session.commit()

    repository = KnowledgeRepository()
    with session_scope() as session:
        relation_rows = repository.list_version_relations(
            session, framework_version_id=framework_id
        )
        assert len(relation_rows) == 2
        # 读取层按版本内 node 关系去重后返回一条逻辑边
        from app.services.knowledge_service import KnowledgeService

        response = KnowledgeService().get_relation_graph(session, course_id)
        assert [node.knowledge_node_id for node in response.nodes].count(first_node_id) == 1
        assert len(response.edges) == 1
        assert response.edges[0].relation_type == "prerequisite"

        scored = KnowledgeService().get_scored_tree(session, course_id)
        scored_leaves = _collect_leaves(
            [node.model_dump(mode="json") for node in scored.tree]
        )
        ids = [leaf["knowledge_node_id"] for leaf in scored_leaves]
        assert ids.count(first_node_id) == 1
        assert ids.count(second_node_id) == 1

        detail = KnowledgeService().get_node_detail(session, first_node_id)
        assert detail.aliases == ["TCP拥塞控制"]

    reset_settings_cache()
