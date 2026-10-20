import asyncio
from pathlib import Path

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError
from app.core.config import reset_settings_cache
from app.llm.schemas import (
    KnowledgeFrameworkCandidate,
    KnowledgeNodeCandidate,
    KnowledgeSourceCandidate,
    LLMRunSummary,
    LLMStructuredResult,
)
from app.main import app


def _create_pdf(path: Path, page_texts: list[str]) -> None:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _collect_leaves(nodes: list[dict]) -> list[dict]:
    leaves: list[dict] = []
    for node in nodes:
        if node["is_leaf"]:
            leaves.append(node)
        else:
            leaves.extend(_collect_leaves(node.get("children", [])))
    return leaves


async def _wait_for_job(client: AsyncClient, job_id: str) -> dict:
    last_body: dict | None = None
    for _ in range(80):
        response = await client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        last_body = response.json()
        if last_body["status"] in {"succeeded", "failed", "cancelled"}:
            return last_body
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {last_body}")


async def _create_course(client: AsyncClient, name: str = "Biology") -> str:
    response = await client.post("/api/courses", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_pdf_material(client: AsyncClient, course_id: str, path: Path) -> None:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/courses/{course_id}/materials",
            files={"file": (path.name, handle, "application/pdf")},
        )
    assert response.status_code == 201
    body = response.json()
    job = await _wait_for_job(client, body["job_id"])
    assert job["status"] == "succeeded"


@pytest.mark.anyio
async def test_knowledge_build_requires_llm_configuration(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    reset_settings_cache()

    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(pdf_path, ["cells divide and specialize"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client)
        await _upload_pdf_material(client, course_id, pdf_path)

        response = await client.post(
            f"/api/courses/{course_id}/knowledge/build",
            json={},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
    reset_settings_cache()


@pytest.mark.anyio
async def test_knowledge_build_and_query_flow(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-knowledge-framework")
    reset_settings_cache()

    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(
        pdf_path,
        [
            "Photosynthesis converts light energy into chemical energy.",
            "Cellular respiration releases stored energy.",
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Biology Review")
        await _upload_pdf_material(client, course_id, pdf_path)

        build_response = await client.post(
            f"/api/courses/{course_id}/knowledge/build",
            json={"reference_outline": "Energy transfer in cells"},
        )
        assert build_response.status_code == 202
        build_body = build_response.json()
        assert build_body["framework_version_id"]

        build_job = await _wait_for_job(client, build_body["job_id"])
        assert build_job["status"] == "succeeded"

        versions_response = await client.get(f"/api/courses/{course_id}/knowledge/versions")
        assert versions_response.status_code == 200
        versions = versions_response.json()
        assert len(versions) == 1
        assert versions[0]["status"] == "active"

        framework_response = await client.get(f"/api/courses/{course_id}/knowledge")
        assert framework_response.status_code == 200
        framework = framework_response.json()
        assert framework["version_number"] == 1
        assert framework["tree"]
        assert framework["nodes"]

        # 合并层现在保留「文档 → 知识点」：顶层是文档父节点，来源挂在叶子。
        document_node = framework["tree"][0]
        assert document_node["title"] == "lesson.pdf"
        assert document_node["is_leaf"] is False
        assert document_node["sources"] == []
        assert document_node["children"]
        assert "section_label" in document_node
        assert "content" in document_node

        leaf_node = _collect_leaves(framework["tree"])[0]
        assert leaf_node["sources"]
        detail_response = await client.get(f"/api/knowledge/{leaf_node['knowledge_node_id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["title"]
        assert detail["sources"]
        assert detail["framework_version_id"] == build_body["framework_version_id"]

    reset_settings_cache()


@pytest.mark.anyio
async def test_knowledge_build_processes_materials_in_batches(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "large_lesson.pdf"
    _create_pdf(
        pdf_path,
        [f"Batch topic {index} explains memory hierarchy concept {index}." for index in range(15)],
    )

    class CountingAdapter:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def ensure_available(self) -> None:
            return None

        def generate_structured_output(self, **kwargs) -> LLMStructuredResult:
            payload = kwargs["user_payload"]
            self.payloads.append(payload)
            nodes = []
            for document in payload["documents"]:
                children = [
                    KnowledgeNodeCandidate(
                        ref=f"chunk_{segment['chunk_id']}",
                        title=f"Topic from page {segment['page_start']}",
                        content=document["content"][segment["start_char"] : segment["end_char"]],
                        sources=[
                            KnowledgeSourceCandidate(
                                document_id=document["document_id"],
                                page_number=segment["page_start"],
                                chunk_id=segment["chunk_id"],
                                evidence_type="chunk",
                            )
                        ],
                        children=[],
                    )
                    for segment in document["source_segments"]
                ]
                nodes.append(
                    KnowledgeNodeCandidate(
                        ref=f"doc_{document['document_id']}",
                        title=document["filename"],
                        content=None,
                        sources=[],
                        children=children,
                    )
                )

            return LLMStructuredResult(
                summary=LLMRunSummary(
                    model_name="test-model",
                    prompt_version=kwargs["prompt_version"],
                    provider="test",
                ),
                data=KnowledgeFrameworkCandidate(
                    root_title=payload["course_name"],
                    root_description=None,
                    nodes=nodes,
                    relations=[],
                ),
            )

    adapter = CountingAdapter()
    monkeypatch.setattr("app.services.knowledge_service.get_llm_adapter", lambda: adapter)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Computer Systems")
        await _upload_pdf_material(client, course_id, pdf_path)

        build_response = await client.post(f"/api/courses/{course_id}/knowledge/build", json={})
        assert build_response.status_code == 202
        build_job = await _wait_for_job(client, build_response.json()["job_id"])
        assert build_job["status"] == "succeeded"

        framework_response = await client.get(f"/api/courses/{course_id}/knowledge")
        assert framework_response.status_code == 200
        framework = framework_response.json()
        leaves = _collect_leaves(framework["tree"])

    assert len(adapter.payloads) == 2
    assert all(
        len(document["source_segments"]) <= 12
        for payload in adapter.payloads
        for document in payload["documents"]
    )
    assert all("chunks" not in document for payload in adapter.payloads for document in payload["documents"])
    assert all(document["content"] for payload in adapter.payloads for document in payload["documents"])
    assert len(leaves) == 15


@pytest.mark.anyio
async def test_knowledge_build_payload_includes_context_and_filtering_rules(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "memory.pdf"
    _create_pdf(
        pdf_path,
        [
            "Computer Systems Chapter 3 Memory Hierarchy",
            "Agenda: technology trends and cache designer questions",
            "Temporal locality means recently referenced data is likely to be referenced again soon.",
        ],
    )

    class InspectingAdapter:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def ensure_available(self) -> None:
            return None

        def generate_structured_output(self, **kwargs) -> LLMStructuredResult:
            payload = kwargs["user_payload"]
            self.payloads.append(payload)
            document = payload["documents"][0]
            source = document["batch_sources"][-1]
            return LLMStructuredResult(
                summary=LLMRunSummary(
                    model_name="test-model",
                    prompt_version=kwargs["prompt_version"],
                    provider="test",
                ),
                data=KnowledgeFrameworkCandidate(
                    root_title=payload["course_name"],
                    root_description=None,
                    nodes=[
                        KnowledgeNodeCandidate(
                            ref="memory",
                            title="Memory hierarchy",
                            content=None,
                            sources=[],
                            children=[
                                KnowledgeNodeCandidate(
                                    ref="temporal_locality",
                                    title="Temporal locality",
                                    content=(
                                        "Recently referenced data tends to be referenced again soon."
                                    ),
                                    sources=[
                                        KnowledgeSourceCandidate(
                                            document_id=source["document_id"],
                                            page_number=source["page_number"],
                                            chunk_id=source["chunk_id"],
                                            evidence_type="chunk",
                                        )
                                    ],
                                    children=[],
                                )
                            ],
                        )
                    ],
                    relations=[],
                ),
            )

    adapter = InspectingAdapter()
    monkeypatch.setattr("app.services.knowledge_service.get_llm_adapter", lambda: adapter)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Computer Systems")
        await _upload_pdf_material(client, course_id, pdf_path)

        build_response = await client.post(f"/api/courses/{course_id}/knowledge/build", json={})
        assert build_response.status_code == 202
        build_job = await _wait_for_job(client, build_response.json()["job_id"])
        assert build_job["status"] == "succeeded"

    payload = adapter.payloads[0]
    assert payload["generation_scope"]["instruction"].startswith(
        "Generate source-backed knowledge points"
    )
    assert "table-of-contents" in " ".join(payload["selection_rules"])
    assert "document or section containers" in payload["output_shape"]["nodes"]
    document_payload = payload["documents"][0]
    assert len(document_payload["nearby_page_context"]) == 3
    assert "Temporal locality" in document_payload["nearby_page_context"][2]["text_preview"]
    assert document_payload["batch_sources"]


@pytest.mark.anyio
async def test_knowledge_build_fails_for_invalid_batch_output(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(pdf_path, ["Cache blocks store recently used data."])

    class InvalidStructuredOutputAdapter:
        def ensure_available(self) -> None:
            return None

        def generate_structured_output(self, **_) -> None:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="LLM returned invalid structured output.",
                status_code=502,
            )

    monkeypatch.setattr(
        "app.services.knowledge_service.get_llm_adapter",
        lambda: InvalidStructuredOutputAdapter(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Architecture")
        await _upload_pdf_material(client, course_id, pdf_path)

        build_response = await client.post(f"/api/courses/{course_id}/knowledge/build", json={})
        assert build_response.status_code == 202
        build_job = await _wait_for_job(client, build_response.json()["job_id"])
        assert build_job["status"] == "failed"
        assert build_job["error_code"] == "LLM_OUTPUT_INVALID"


@pytest.mark.anyio
async def test_material_delete_rejected_when_used_by_framework(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-knowledge-framework")
    reset_settings_cache()

    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(pdf_path, ["Newton's laws describe motion."])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Mechanics")
        with pdf_path.open("rb") as handle:
            upload_response = await client.post(
                f"/api/courses/{course_id}/materials",
                files={"file": (pdf_path.name, handle, "application/pdf")},
            )
        material_body = upload_response.json()
        await _wait_for_job(client, material_body["job_id"])

        build_response = await client.post(
            f"/api/courses/{course_id}/knowledge/build",
            json={},
        )
        await _wait_for_job(client, build_response.json()["job_id"])

        delete_response = await client.delete(
            f"/api/materials/{material_body['document_id']}"
        )
        assert delete_response.status_code == 409
        assert delete_response.json()["error"]["code"] == "MATERIAL_IN_USE"

    reset_settings_cache()


@pytest.mark.anyio
async def test_failed_knowledge_rebuild_does_not_replace_active_version(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-knowledge-framework")
    reset_settings_cache()

    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(pdf_path, ["Energy moves through an ecosystem."])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Ecology")
        await _upload_pdf_material(client, course_id, pdf_path)

        first_build_response = await client.post(
            f"/api/courses/{course_id}/knowledge/build",
            json={},
        )
        assert first_build_response.status_code == 202
        first_build_body = first_build_response.json()
        first_job = await _wait_for_job(client, first_build_body["job_id"])
        assert first_job["status"] == "succeeded"

        class FailingAdapter:
            def ensure_available(self) -> None:
                return None

            def generate_structured_output(self, **_) -> None:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Invalid framework output.",
                    status_code=502,
                )

        monkeypatch.setattr(
            "app.services.knowledge_service.get_llm_adapter",
            lambda: FailingAdapter(),
        )

        second_build_response = await client.post(
            f"/api/courses/{course_id}/knowledge/build",
            json={},
        )
        assert second_build_response.status_code == 202
        second_build_body = second_build_response.json()
        second_job = await _wait_for_job(client, second_build_body["job_id"])
        assert second_job["status"] == "failed"
        assert second_job["error_code"] == "LLM_OUTPUT_INVALID"

        versions_response = await client.get(f"/api/courses/{course_id}/knowledge/versions")
        assert versions_response.status_code == 200
        versions = versions_response.json()
        assert [version["status"] for version in versions] == ["failed", "active"]

        framework_response = await client.get(f"/api/courses/{course_id}/knowledge")
        assert framework_response.status_code == 200
        assert framework_response.json()["framework_version_id"] == first_build_body["framework_version_id"]

    reset_settings_cache()
