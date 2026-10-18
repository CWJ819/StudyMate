import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_course_crud_flow(migrated_database_url: str) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        create_response = await client.post(
            "/api/courses",
            json={"name": "Linear Algebra", "description": "Matrices and vectors"},
        )
        assert create_response.status_code == 201
        created = create_response.json()
        course_id = created["id"]
        assert created["name"] == "Linear Algebra"
        assert created["description"] == "Matrices and vectors"

        list_response = await client.get("/api/courses")
        assert list_response.status_code == 200
        listed = list_response.json()
        assert len(listed) == 1
        assert listed[0]["id"] == course_id

        detail_response = await client.get(f"/api/courses/{course_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["name"] == "Linear Algebra"

        update_response = await client.patch(
            f"/api/courses/{course_id}",
            json={"name": "Advanced Linear Algebra"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Advanced Linear Algebra"

        delete_response = await client.delete(f"/api/courses/{course_id}")
        assert delete_response.status_code == 204

        missing_response = await client.get(f"/api/courses/{course_id}")
        assert missing_response.status_code == 404
        assert missing_response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
