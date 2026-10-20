"""LLM 结构化输出归一化测试。

fixture 取自真实模型验收（2026-10-20，DeepSeek）捕获的原始输出：
- 简答 rubric 用 `points` 别名、缺 `criterion_id`；
- flash 给选择题塞非法 rubric（criteria 为字符串数组）；
- 批改返回 `points_awarded` / `criteria_results` / `overall_feedback` 等不同字段名。
报告：docs/testing/real-model-acceptance-report-2026-10-20.md §3.3。
"""

from app.llm.openai_compatible import OpenAICompatibleAdapter
from app.llm.schemas import QuizGenerationCandidate, ShortAnswerGradingCandidate


def _adapter() -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter()


def test_quiz_rubric_points_alias_and_missing_criterion_id() -> None:
    """验收原始输出：criteria 用 points、缺 criterion_id → 归一化后通过校验。"""
    payload = {
        "questions": [
            {
                "question_type": "short_answer",
                "stem": "请说明 TCP 超时与快重传后拥塞窗口恢复方式的差别。",
                "options": [],
                "answer_key_option_ids": [],
                "reference_answer": "超时重新慢启动；3 个重复 ACK 触发快重传与快恢复。",
                "rubric": {
                    "max_points": 5,
                    "criteria": [
                        {"description": "正确说明超时后 ssthresh 减半并重新慢启动", "points": 2},
                        {"description": "正确说明 3 个重复 ACK 触发快重传与快恢复", "points": 2},
                        {"description": "能对比超时与快重传的恢复方式", "points": 1},
                    ],
                },
                "explanation": None,
                "difficulty": "low",
                "knowledge_mappings": [
                    {"knowledge_node_id": "kn1", "relation_role": "primary", "weight": 1.0}
                ],
                "source_chunk_ids": [],
                "source_page_numbers": [1],
            }
        ]
    }

    normalized = _adapter()._normalize_quiz_payload(payload, user_payload={"difficulty": "low"})
    data = QuizGenerationCandidate.model_validate(normalized)

    rubric = data.questions[0].rubric
    assert rubric is not None
    assert rubric.max_points == 5
    assert [c.criterion_id for c in rubric.criteria] == ["c1", "c2", "c3"]
    assert [c.max_points for c in rubric.criteria] == [2, 2, 1]


def test_quiz_choice_question_rubric_forced_null_and_string_criteria() -> None:
    """flash 的原始输出：选择题带 rubric（criteria 为字符串数组）→ 置 null 后通过校验。"""
    payload = {
        "questions": [
            {
                "question_type": "single_choice",
                "stem": "慢启动阶段每个 RTT 内 cwnd 近似如何变化？",
                "options": [
                    {"id": "A", "text": "翻倍"},
                    {"id": "B", "text": "减半"},
                ],
                "answer_key_option_ids": ["A"],
                "rubric": {"criteria": ["选择 A，说明一个 RTT 内窗口近似翻倍"], "max_points": 1},
                "difficulty": "low",
                "knowledge_mappings": ["kn1"],
            }
        ]
    }

    normalized = _adapter()._normalize_quiz_payload(payload, user_payload={"difficulty": "low"})
    data = QuizGenerationCandidate.model_validate(normalized)

    question = data.questions[0]
    assert question.rubric is None  # 选择题不参与 rubric 评分
    assert question.knowledge_mappings[0].knowledge_node_id == "kn1"
    assert question.knowledge_mappings[0].weight == 1.0


def test_quiz_missing_difficulty_backfilled_from_request() -> None:
    payload = {
        "questions": [
            {
                "question_type": "多选",
                "stem": "下列哪些属于拥塞控制机制？",
                "options": [{"id": "A", "text": "慢启动"}, {"id": "B", "text": "拥塞避免"}],
                "answer_key_option_ids": ["A", "B"],
                "knowledge_mappings": [{"node_id": "kn1", "relation_role": "primary"}],
                "extra_analysis_field": "models add helpful junk",
            }
        ]
    }

    normalized = _adapter()._normalize_quiz_payload(payload, user_payload={"difficulty": "medium"})
    data = QuizGenerationCandidate.model_validate(normalized)

    question = data.questions[0]
    assert question.question_type == "multiple_choice"  # 中文题型别名
    assert question.difficulty == "medium"  # 缺失回填请求值
    assert question.options is not None
    assert len(question.options) == 2


def test_grading_field_aliases_normalized() -> None:
    """验收原始输出：字段名完全不同 + met/feedback 结构 → 归一化后通过校验。"""
    payload = {
        "points_awarded": 1.0,
        "max_points": 2.0,
        "criteria_results": [
            {
                "criterion_id": "mentions_topic",
                "points_awarded": 1.0,
                "max_points": 1.0,
                "met": True,
                "feedback": "Mentions 25G and 100G Ethernet concepts.",
            },
            {
                "criterion_id": "mentions_material_support",
                "points_awarded": 0.0,
                "max_points": 1.0,
                "met": False,
                "feedback": "Does not mention IEEE 802.3by.",
            },
        ],
        "overall_feedback": "Names the topic but omits the specific standard.",
    }

    normalized = _adapter()._normalize_grading_payload(payload)
    data = ShortAnswerGradingCandidate.model_validate(normalized)

    assert [c.criterion_id for c in data.criterion_scores] == [
        "mentions_topic",
        "mentions_material_support",
    ]
    assert data.criterion_scores[0].awarded_points == 1.0
    assert data.criterion_scores[0].rationale.startswith("Mentions")
    assert data.feedback.startswith("Names the topic")
    assert data.score == 1.0


def test_grading_missing_score_computed_from_criteria() -> None:
    payload = {
        "criteria_results": [
            {"criterion_id": "c1", "points_awarded": 2},
            {"criterion_id": "c2", "points_awarded": 1.5},
        ],
        "overall_feedback": "部分正确。",
        "reason": "覆盖两个要点。",
    }

    normalized = _adapter()._normalize_grading_payload(payload)
    data = ShortAnswerGradingCandidate.model_validate(normalized)

    assert data.score == 3.5
    assert data.rationale == "覆盖两个要点。"
