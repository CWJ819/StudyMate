import json

from pydantic import BaseModel

from app.core.config import reset_settings_cache
from app.llm.openai_compatible import OpenAICompatibleAdapter
from app.llm.schemas import QuizGenerationCandidate


def test_extract_json_content_accepts_markdown_fence() -> None:
    adapter = OpenAICompatibleAdapter()

    assert adapter._extract_json_content('```json\n{"ok": true}\n```') == '{"ok": true}'


def test_extract_json_content_accepts_surrounding_text() -> None:
    adapter = OpenAICompatibleAdapter()

    assert adapter._extract_json_content('Here is the JSON:\n{"ok": true}\nDone.') == '{"ok": true}'


def test_http_structured_output_retries_invalid_json(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    reset_settings_cache()

    class Result(BaseModel):
        ok: bool

    class Response:
        def __init__(self, content: str) -> None:
            self.status_code = 200
            self._content = content

        def json(self) -> dict:
            return {"choices": [{"message": {"content": self._content}}]}

    class Client:
        responses = [Response("not json"), Response(json.dumps({"ok": True}))]
        calls = []

        def __init__(self, **_) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *args, **kwargs):
            self.calls.append(kwargs["json"])
            return self.responses.pop(0)

    monkeypatch.setattr("app.llm.openai_compatible.httpx.Client", Client)
    try:
        result = OpenAICompatibleAdapter().generate_structured_output(
            prompt_version="test",
            system_prompt="Return JSON.",
            user_payload={"input": "value"},
            response_model=Result,
        )
    finally:
        reset_settings_cache()

    assert result.data.ok is True
    assert len(Client.calls) == 2
    assert Client.calls[0]["response_format"] == {"type": "json_object"}
    assert "structured-output retry" in Client.calls[1]["messages"][0]["content"]


def test_http_request_uses_locally_saved_api_key(tmp_path, monkeypatch) -> None:
    """设置页保存的 Key（local_secrets.json）必须压过环境变量，并进入 Authorization 头。"""
    secrets_file = tmp_path / "local_secrets.json"
    secrets_file.write_text(json.dumps({"llm_api_key": "local-key"}), encoding="utf-8")
    monkeypatch.setenv("LOCAL_SECRETS_PATH", str(secrets_file))
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    reset_settings_cache()

    class Result(BaseModel):
        ok: bool

    captured: dict = {}

    class Response:
        status_code = 200

        def json(self) -> dict:
            return {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}

    class Client:
        def __init__(self, **_) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *args, **kwargs):
            captured["url"] = args[0] if args else kwargs.get("url")
            captured["headers"] = kwargs["headers"]
            return Response()

    monkeypatch.setattr("app.llm.openai_compatible.httpx.Client", Client)
    try:
        result = OpenAICompatibleAdapter().generate_structured_output(
            prompt_version="test",
            system_prompt="Return JSON.",
            user_payload={"input": "value"},
            response_model=Result,
        )
    finally:
        reset_settings_cache()

    assert result.data.ok is True
    assert captured["url"] == "https://llm.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer local-key"


def test_normalize_quiz_aliases_without_inventing_answer_mapping() -> None:
    adapter = OpenAICompatibleAdapter()

    normalized = adapter._normalize_structured_payload(
        {
            "question": {
                "type": "single",
                "question": "What is cache locality?",
                "choices": {"A": "Recent reuse", "B": "No reuse"},
                "answer": "A",
                "knowledge_points": [{"knowledge_node_id": "node-1"}],
                "difficulty": "low",
            }
        },
        response_model=QuizGenerationCandidate,
        user_payload={},
    )

    assert normalized["questions"][0]["question_type"] == "single_choice"
    assert normalized["questions"][0]["stem"] == "What is cache locality?"
    assert normalized["questions"][0]["options"] == [
        {"id": "A", "text": "Recent reuse"},
        {"id": "B", "text": "No reuse"},
    ]
    assert normalized["questions"][0]["answer_key_option_ids"] == ["A"]
