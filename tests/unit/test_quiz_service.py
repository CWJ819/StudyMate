import pytest
from types import SimpleNamespace

from app.core.errors import AppError
from app.schemas.quiz import (
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QuizAnswerInput,
    QuizQuestionOption,
    QuizQuestionSnapshot,
    QuizGenerateRequest,
)
from app.services.quiz_service import QuizService


def _multiple_choice_snapshot() -> QuizQuestionSnapshot:
    return QuizQuestionSnapshot(
        question_id="question-1",
        question_type=QUESTION_TYPE_MULTIPLE_CHOICE,
        stem="Select all correct statements.",
        options=[
            QuizQuestionOption(id="A", text="First"),
            QuizQuestionOption(id="B", text="Second"),
            QuizQuestionOption(id="C", text="Third"),
        ],
        answer_key_option_ids=["A", "B"],
        reference_answer=None,
        rubric=None,
        explanation="A and B are correct.",
        difficulty="low",
        max_score=1.0,
        knowledge_mappings=[],
        source_metadata={},
    )


def test_multiple_choice_grading_exact_match_and_reordered_match() -> None:
    service = QuizService()
    snapshot = _multiple_choice_snapshot()

    exact_result, _ = service._grade_answer(
        snapshot,
        QuizAnswerInput(question_id=snapshot.question_id, selected_option_ids=["A", "B"]),
    )
    reordered_result, _ = service._grade_answer(
        snapshot,
        QuizAnswerInput(question_id=snapshot.question_id, selected_option_ids=["B", "A"]),
    )

    assert exact_result.score == 1.0
    assert reordered_result.score == 1.0
    assert exact_result.correct is True
    assert reordered_result.correct is True


def test_multiple_choice_grading_missing_extra_and_empty_return_zero() -> None:
    service = QuizService()
    snapshot = _multiple_choice_snapshot()

    missing_result, _ = service._grade_answer(
        snapshot,
        QuizAnswerInput(question_id=snapshot.question_id, selected_option_ids=["A"]),
    )
    extra_result, _ = service._grade_answer(
        snapshot,
        QuizAnswerInput(question_id=snapshot.question_id, selected_option_ids=["A", "B", "C"]),
    )
    empty_result, _ = service._grade_answer(
        snapshot,
        QuizAnswerInput(question_id=snapshot.question_id, selected_option_ids=[]),
    )

    assert missing_result.score == 0.0
    assert extra_result.score == 0.0
    assert empty_result.score == 0.0
    assert missing_result.correct is False
    assert extra_result.correct is False
    assert empty_result.correct is False


def test_multiple_choice_grading_rejects_invalid_and_duplicate_option_ids() -> None:
    service = QuizService()
    snapshot = _multiple_choice_snapshot()

    with pytest.raises(AppError) as invalid_error:
        service._grade_answer(
            snapshot,
            QuizAnswerInput(question_id=snapshot.question_id, selected_option_ids=["Z"]),
        )
    with pytest.raises(AppError) as duplicate_error:
        service._grade_answer(
            snapshot,
            QuizAnswerInput(question_id=snapshot.question_id, selected_option_ids=["A", "A"]),
        )

    assert invalid_error.value.code == "INVALID_OPTION_IDENTIFIER"
    assert duplicate_error.value.code == "INVALID_OPTION_IDENTIFIER"


def test_generation_selection_keeps_explicit_scope_beyond_previous_twenty_limit() -> None:
    service = QuizService()
    nodes = [
        SimpleNamespace(knowledge_node_id=f"node-{index}", is_leaf=True, content="content")
        for index in range(25)
    ]
    settings = QuizGenerateRequest(
        knowledge_node_ids=[node.knowledge_node_id for node in nodes],
        question_count=10,
        question_types=["single_choice"],
    )

    selected, roles = service._select_generation_nodes(
        quiz_id="quiz-1",
        settings=settings,
        nodes=nodes,
        selection_stats={},
    )

    assert len(selected) == 25
    assert set(roles) == {node.knowledge_node_id for node in nodes}


def test_exploration_selection_prefers_uncovered_nodes_but_is_bounded() -> None:
    service = QuizService()
    nodes = [
        SimpleNamespace(knowledge_node_id=f"node-{index}", is_leaf=True, content="content")
        for index in range(50)
    ]
    settings = QuizGenerateRequest(question_count=10, question_types=["single_choice"])
    stats = {
        node.knowledge_node_id: {"question_count": 4}
        for node in nodes[:20]
    }

    selected, roles = service._select_generation_nodes(
        quiz_id="quiz-2",
        settings=settings,
        nodes=nodes,
        selection_stats=stats,
    )

    assert len(selected) == 36
    assert all(roles[node.knowledge_node_id] == "exploration" for node in selected)
    assert sum(node.knowledge_node_id in {item.knowledge_node_id for item in selected} for node in nodes[20:]) > 0
