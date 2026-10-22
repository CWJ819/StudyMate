"""Phase 3 集成测试：读取时评分的 tree / highlights 端点。

评分不落库：构建完成后直接调用两个新端点，验证形状、排序与旧契约不变。
"""

import asyncio
from pathlib import Path

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
from app.db.session import session_scope
from app.main import app
from app.repositories.mastery_repository import MasteryRepository
from app.services.knowledge_scoring import (
    DIFFICULTY_WEIGHTS,
    HIGHLIGHT_LIMIT_MAX,
    IMPORTANCE_WEIGHTS,
    SCORING_VERSION,
)


def _create_pdf_with_toc(path: Path, page_texts: list[str], toc: list[list]) -> None:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        # 中文必须用内建 china-s 字体，否则提取出的文本会退化为占位符
        page.insert_text((72, 72), text, fontname="china-s")
        page.insert_text((72, 110), "本页补充正文内容，用于生成足够长度的文本块。", fontname="china-s")
    document.set_toc(toc)
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


async def _create_course(client: AsyncClient, name: str = "Transport") -> str:
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
    job = await _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"


async def _build_knowledge(client: AsyncClient, course_id: str) -> dict:
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


def _assert_tree_matches(framework_nodes: list[dict], scored_nodes: list[dict]) -> None:
    """新树必须保留旧树的所有字段与结构，只多出评分字段。"""
    assert len(framework_nodes) == len(scored_nodes)
    for old, scored in zip(framework_nodes, scored_nodes):
        for key in (
            "knowledge_node_id",
            "node_version_id",
            "section_label",
            "title",
            "content",
            "level",
            "is_leaf",
            "sources",
        ):
            assert scored[key] == old[key], key
        _assert_tree_matches(old["children"], scored["children"])


async def _build_scored_course(tmp_path: Path) -> str:
    """一节 3 页 + 一节 1 页：mock 前一个窗口产 3 叶 2 边，后一个窗口 1 叶。"""
    pdf_path = tmp_path / "transport.pdf"
    _create_pdf_with_toc(
        pdf_path,
        [
            "第1章 运输层",
            "用户数据报协议 UDP 提供无连接的不可靠传输服务。",
            "传输控制协议 TCP 提供面向连接的可靠传输服务。",
            "拥塞控制通过调整发送速率避免网络过载。",
            "差错检测通过校验和发现传输中的比特错误。",
        ],
        [
            [1, "第1章 运输层", 1],
            [2, "1.1 UDP 与拥塞控制", 2],
            [2, "1.2 差错检测", 5],
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client)
        await _upload_pdf_material(client, course_id, pdf_path)
        await _build_knowledge(client, course_id)
    return course_id


@pytest.mark.anyio
async def test_scored_tree_preserves_old_shape_and_aggregates_children(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage8")
    reset_settings_cache()

    course_id = await _build_scored_course(tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        framework_response = await client.get(f"/api/courses/{course_id}/knowledge")
        assert framework_response.status_code == 200
        framework = framework_response.json()

        tree_response = await client.get(f"/api/courses/{course_id}/knowledge/tree")
        assert tree_response.status_code == 200
        scored = tree_response.json()

        # 旧契约一字不动：没有评分字段
        assert "importance" not in framework["tree"][0]
        assert all("components" not in leaf for leaf in _collect_leaves(framework["tree"]))

    assert scored["framework_version_id"] == framework["framework_version_id"]
    assert scored["version_number"] == framework["version_number"]
    assert scored["scoring_version"] == SCORING_VERSION
    _assert_tree_matches(framework["tree"], scored["tree"])

    def check(node: dict) -> None:
        assert 0.0 <= node["importance"] <= 1.0
        assert 0.0 <= node["difficulty"] <= 1.0
        children = node["children"]
        if node["is_leaf"]:
            assert node["components"] is not None
            assert set(node["components"]) == {
                "source_pages",
                "relation_centrality",
                "content_length",
                "quiz_reinforcement",
            }
            assert node["components"]["source_pages"] >= 1
            assert node["components"]["content_length"] > 0
        else:
            assert node["components"] is None
            assert children  # 每章/每节都有后代
            assert node["importance"] == max(child["importance"] for child in children)
            assert node["difficulty"] == max(child["difficulty"] for child in children)
            for child in children:
                check(child)

    for top in scored["tree"]:
        check(top)
    leaves = _collect_leaves(scored["tree"])
    assert len(leaves) >= 4

    reset_settings_cache()


@pytest.mark.anyio
async def test_highlights_defaults_ordering_and_zero_mastery_degrade(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage8")
    reset_settings_cache()

    course_id = await _build_scored_course(tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/api/courses/{course_id}/knowledge/highlights")
        assert response.status_code == 200
        highlights = response.json()

        difficulty_response = await client.get(
            f"/api/courses/{course_id}/knowledge/highlights",
            params={"order": "difficulty"},
        )
        assert difficulty_response.status_code == 200
        by_difficulty = difficulty_response.json()

        gap_response = await client.get(
            f"/api/courses/{course_id}/knowledge/highlights",
            params={"order": "gap"},
        )
        assert gap_response.status_code == 200
        by_gap = gap_response.json()

        limited_response = await client.get(
            f"/api/courses/{course_id}/knowledge/highlights",
            params={"limit": 2},
        )
        assert limited_response.status_code == 200

    items = highlights["items"]
    assert 1 <= len(items) <= HIGHLIGHT_LIMIT_MAX
    assert highlights["basis"]["scoring_version"] == SCORING_VERSION
    assert highlights["basis"]["weights"]["importance"] == IMPORTANCE_WEIGHTS
    assert highlights["basis"]["weights"]["difficulty"] == DIFFICULTY_WEIGHTS

    importances = [item["importance"] for item in items]
    assert importances == sorted(importances, reverse=True)
    difficulties = [item["difficulty"] for item in by_difficulty["items"]]
    assert difficulties == sorted(difficulties, reverse=True)
    assert len(limited_response.json()["items"]) == 2

    # 零掌握度：gap 退化为 importance 序，全部标 untested
    assert [item["knowledge_node_id"] for item in by_gap["items"]] == [
        item["knowledge_node_id"] for item in items
    ]
    for item in items:
        assert item["mastery_estimate"] is None
        assert item["untested"] is True
        assert item["evidence_count"] == 0
        assert item["section_path"][0] == "第1章 运输层"
        assert set(item["reasons"][0]) == {"component", "value", "normalized", "contribution"}

    # 3 页窗口里的叶子和 1 页窗口里的叶子分属两个小节，section_path 能区分
    section_paths = {tuple(item["section_path"]) for item in items}
    assert ("第1章 运输层", "1.1 UDP 与拥塞控制") in section_paths
    assert ("第1章 运输层", "1.2 差错检测") in section_paths

    reset_settings_cache()


@pytest.mark.anyio
async def test_gap_order_moves_tested_leaf_first_and_keeps_untested_after(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage8")
    reset_settings_cache()

    course_id = await _build_scored_course(tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        baseline = (
            await client.get(f"/api/courses/{course_id}/knowledge/highlights")
        ).json()
        weakest = baseline["items"][-1]
        with session_scope() as session:
            state = MasteryRepository().get_or_create_state(
                session,
                course_id=course_id,
                knowledge_node_id=weakest["knowledge_node_id"],
            )
            state.mastery_estimate = 0.2
            state.evidence_count = 4
            session.commit()

        gap = (
            await client.get(
                f"/api/courses/{course_id}/knowledge/highlights",
                params={"order": "gap"},
            )
        ).json()

    names = [item["knowledge_node_id"] for item in gap["items"]]
    assert names[0] == weakest["knowledge_node_id"]
    assert gap["items"][0]["untested"] is False
    assert gap["items"][0]["mastery_estimate"] == pytest.approx(0.2)
    assert gap["items"][0]["evidence_count"] == 4
    assert all(item["untested"] for item in gap["items"][1:])
    # 有掌握度的排在全部未测验之前
    tested_flags = [item["untested"] for item in gap["items"]]
    assert tested_flags == sorted(tested_flags)

    # importance 序不受掌握度影响
    importance_ids = [item["knowledge_node_id"] for item in baseline["items"]]
    assert names[1:] == [node_id for node_id in importance_ids if node_id != weakest["knowledge_node_id"]]

    reset_settings_cache()


@pytest.mark.anyio
async def test_scoring_endpoints_require_active_framework(
    migrated_database_url: str,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Empty")
        tree_response = await client.get(f"/api/courses/{course_id}/knowledge/tree")
        highlights_response = await client.get(
            f"/api/courses/{course_id}/knowledge/highlights"
        )
        unknown_response = await client.get(
            "/api/courses/does-not-exist/knowledge/highlights"
        )

    assert tree_response.status_code == 404
    assert tree_response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert highlights_response.status_code == 404
    assert highlights_response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert unknown_response.status_code == 404
    assert unknown_response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.anyio
async def test_highlight_query_validation(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage8")
    reset_settings_cache()

    course_id = await _build_scored_course(tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad_order = await client.get(
            f"/api/courses/{course_id}/knowledge/highlights",
            params={"order": "random"},
        )
        too_large = await client.get(
            f"/api/courses/{course_id}/knowledge/highlights",
            params={"limit": HIGHLIGHT_LIMIT_MAX + 1},
        )
        zero = await client.get(
            f"/api/courses/{course_id}/knowledge/highlights",
            params={"limit": 0},
        )

    assert bad_order.status_code == 422
    assert bad_order.json()["error"]["code"] == "VALIDATION_ERROR"
    assert too_large.status_code == 422
    assert zero.status_code == 422

    reset_settings_cache()
