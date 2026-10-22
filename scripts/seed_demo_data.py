"""在冻结的 v16 结构上播种演示数据（生成测验 → 作答 → 断言）。

只调用 quiz 生成/提交、掌握度、错题本和评分读取接口：
- 不触发知识构建/重建，不改设置；
- 不删除、不迁移任何旧掌握度记录；
- 固定随机种子作答（正确答案提交前不可知，随机作答会得到"薄弱点多"的真实形态）。

用法（仓库根目录，后端跑在 8000）：

    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --course 96d00dc9 --rounds 2
"""

from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass

import httpx

DEFAULT_API = "http://127.0.0.1:8000/api"
DEFAULT_SEED = 20261022
QUESTIONS_PER_QUIZ = 10
QUIZ_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class CourseTarget:
    course_id: str
    label: str
    expected_version: int
    expected_leaves: int


TARGETS = (
    CourseTarget(
        course_id="96d00dc9-9c7a-49df-bec6-0b22219563d5",
        label="425 页课",
        expected_version=16,
        expected_leaves=258,
    ),
    CourseTarget(
        course_id="204637ae-a9a0-4708-832c-97a33351d133",
        label="187 页课",
        expected_version=16,
        expected_leaves=98,
    ),
)


def count_leaves(nodes: list[dict]) -> int:
    total = 0
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if node.get("is_leaf"):
            total += 1
        stack.extend(node.get("children") or [])
    return total


def request(client: httpx.Client, method: str, path: str, *, expected: int, **kwargs) -> httpx.Response:
    response = client.request(method, path, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(
            f"{method} {path} -> {response.status_code} (expected {expected}): {response.text[:600]}"
        )
    return response


def wait_job(client: httpx.Client, job_id: str, *, timeout: int = QUIZ_TIMEOUT_SECONDS) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        last = request(client, "GET", f"/jobs/{job_id}", expected=200).json()
        if last["status"] in {"succeeded", "failed", "cancelled"}:
            return last
        time.sleep(2)
    raise TimeoutError(f"job {job_id} did not finish in {timeout}s: {last}")


def read_tree(client: httpx.Client, course_id: str) -> dict:
    return request(client, "GET", f"/courses/{course_id}/knowledge/tree", expected=200).json()


def precheck(client: httpx.Client, target: CourseTarget) -> tuple[str, int]:
    """确认结构没被动过：v16 + 预期叶数。返回 (framework_version_id, 叶数)。"""
    tree = read_tree(client, target.course_id)
    leaves = count_leaves(tree["tree"])
    if tree["version_number"] != target.expected_version:
        raise AssertionError(
            f"{target.label}: version {tree['version_number']} != {target.expected_version}"
        )
    if leaves != target.expected_leaves:
        raise AssertionError(
            f"{target.label}: leaves {leaves} != {target.expected_leaves}（结构可能已被改动）"
        )
    print(
        f"  precheck OK: v{tree['version_number']} framework={tree['framework_version_id'][:8]} "
        f"leaves={leaves}",
        flush=True,
    )
    return tree["framework_version_id"], leaves


def generate_quiz(client: httpx.Client, target: CourseTarget, round_index: int, attempt: int = 1) -> dict:
    payload = {
        "question_count": QUESTIONS_PER_QUIZ,
        "question_types": ["single_choice"],
        "difficulty": "low",
    }
    response = request(
        client,
        "POST",
        f"/courses/{target.course_id}/quiz/generate",
        expected=202,
        json=payload,
    ).json()
    job = wait_job(client, response["job_id"])
    if job["status"] != "succeeded":
        if attempt >= 2:
            raise RuntimeError(
                f"{target.label} round {round_index}: quiz job failed "
                f"({job.get('error_code')}): {job.get('message')}"
            )
        print(
            f"  quiz job failed ({job.get('error_code')}), retrying with a fresh quiz ...",
            flush=True,
        )
        return generate_quiz(client, target, round_index, attempt=attempt + 1)
    quiz = request(client, "GET", f"/quizzes/{response['quiz_id']}", expected=200).json()
    if quiz["status"] != "open":
        raise AssertionError(f"quiz {quiz['quiz_id']} status {quiz['status']} != open")
    if len(quiz["questions"]) != QUESTIONS_PER_QUIZ:
        raise AssertionError(
            f"quiz {quiz['quiz_id']} has {len(quiz['questions'])} questions, expected {QUESTIONS_PER_QUIZ}"
        )
    print(
        f"  round {round_index}: quiz {quiz['quiz_id']} open, {len(quiz['questions'])} 题 "
        f"(job {response['job_id']})",
        flush=True,
    )
    return quiz


def submit_random_answers(
    client: httpx.Client,
    target: CourseTarget,
    quiz: dict,
    rng: random.Random,
    round_index: int,
) -> dict:
    answers = []
    for question in quiz["questions"]:
        options = question.get("options") or []
        if not options:
            raise AssertionError(f"question {question['question_id']} has no options")
        answers.append(
            {
                "question_id": question["question_id"],
                "selected_option_ids": [rng.choice(options)["id"]],
            }
        )
    response = request(
        client,
        "POST",
        f"/quizzes/{quiz['quiz_id']}/submit",
        expected=200,
        json={
            "idempotency_key": f"seed-v16-{target.course_id[:8]}-{round_index}",
            "answers": answers,
        },
    ).json()
    correct = sum(1 for result in response["question_results"] if result.get("correct"))
    print(
        f"  round {round_index}: submitted {len(answers)} answers, correct={correct}, "
        f"score={response['total_score']}/{response['max_score']}, "
        f"questions={len(quiz['questions'])}",
        flush=True,
    )
    return response


def highlight_rows(client: httpx.Client, course_id: str, order: str) -> list[dict]:
    return request(
        client,
        "GET",
        f"/courses/{course_id}/knowledge/highlights",
        expected=200,
        params={"limit": 50, "order": order},
    ).json()["items"]


def gap_value(item: dict) -> float:
    mastery = item["mastery_estimate"]
    return item["importance"] * (1.0 - mastery) if mastery is not None else -1.0


def report_course(
    client: httpx.Client,
    target: CourseTarget,
    framework_before: str,
    leaves_before: int,
    quiz_ids: list[str],
) -> None:
    mastery = request(
        client, "GET", f"/courses/{target.course_id}/mastery", expected=200
    ).json()
    wrongbook = request(
        client, "GET", f"/courses/{target.course_id}/wrongbook", expected=200
    ).json()
    importance = highlight_rows(client, target.course_id, "importance")
    gap = highlight_rows(client, target.course_id, "gap")
    tree = read_tree(client, target.course_id)

    if tree["version_number"] != target.expected_version:
        raise AssertionError(f"{target.label}: framework version changed to {tree['version_number']}")
    if tree["framework_version_id"] != framework_before:
        raise AssertionError(f"{target.label}: framework_version_id changed after seeding")
    if count_leaves(tree["tree"]) != leaves_before:
        raise AssertionError(f"{target.label}: leaf count changed after seeding")
    if not mastery:
        raise AssertionError(f"{target.label}: /mastery 仍为空")
    if any(not item["title"] for item in mastery):
        raise AssertionError(f"{target.label}: /mastery 有 title 为空的记录")
    if not wrongbook:
        raise AssertionError(f"{target.label}: /wrongbook 为空（随机作答没有产生 low_score 缺口）")

    tested = [item for item in gap if item["untested"] is False]
    if not tested:
        raise AssertionError(f"{target.label}: gap 列表没有被考到的节点（untested=false）")
    if all(item["mastery_estimate"] is None for item in tested):
        raise AssertionError(f"{target.label}: 被考到的节点没有 mastery_estimate")
    importance_ids = [item["knowledge_node_id"] for item in importance]
    gap_ids = [item["knowledge_node_id"] for item in gap]
    if importance_ids == gap_ids:
        raise AssertionError(f"{target.label}: order=gap 与 order=importance 排序没有分歧")

    estimates = [item["mastery_estimate"] for item in mastery]
    evidence_total = sum(item["evidence_count"] for item in mastery)
    gap_types: dict[str, int] = {}
    for item in wrongbook:
        gap_types[item["gap_type"]] = gap_types.get(item["gap_type"], 0) + 1

    print(f"\n[{target.label}] {target.course_id}")
    print(
        f"  mastery rows={len(mastery)} (全部 title 非空) evidence_total={evidence_total} "
        f"estimate min/avg/max={min(estimates):.2f}/{sum(estimates) / len(estimates):.2f}/{max(estimates):.2f}"
    )
    print(f"  wrongbook rows={len(wrongbook)} kinds={gap_types}")
    print(f"  quizzes={quiz_ids}")
    print("  top5 importance                        top5 gap（有掌握度的排前）")
    for rank in range(5):
        left = importance[rank]
        right = gap[rank]
        left_text = (
            f"{rank + 1}. I={left['importance']:.3f} "
            f"{'untested' if left['untested'] else 'm=%.2f' % left['mastery_estimate']} "
            f"| {left['title'][:34]}"
        )
        right_text = (
            f"{rank + 1}. I={right['importance']:.3f} gap={gap_value(right):.3f} "
            f"{'untested' if right['untested'] else 'm=%.2f' % right['mastery_estimate']} "
            f"| {right['title'][:34]}"
        )
        print(f"  {left_text:<58} {right_text}")
    print("  排序分歧（前 50）: yes（gap 中被考节点 untested=false 的数量=%d）" % len(tested))
    print("  结构校验: v16 未变、framework_version_id 未变、叶数未变")


def run_course(client: httpx.Client, target: CourseTarget, rounds: int, seed: int) -> None:
    print(f"\n=== {target.label} {target.course_id} ===", flush=True)
    framework_before, leaves_before = precheck(client, target)
    rng = random.Random(f"{seed}:{target.course_id}")
    quiz_ids: list[str] = []
    for round_index in range(1, rounds + 1):
        quiz = generate_quiz(client, target, round_index)
        quiz_ids.append(quiz["quiz_id"])
        submit_random_answers(client, target, quiz, rng, round_index)
    report_course(client, target, framework_before, leaves_before, quiz_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=DEFAULT_API)
    parser.add_argument("--course", default=None, help="只处理 course id 前缀匹配的课程")
    parser.add_argument("--rounds", type=int, default=2, help="每门课生成几场测验")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    targets = [target for target in TARGETS if not args.course or target.course_id.startswith(args.course)]
    if not targets:
        raise SystemExit(f"没有课程匹配 --course {args.course}")

    print(f"API: {args.api_base} | seed={args.seed} | rounds={args.rounds}", flush=True)
    print("提示：本脚本只生成/提交测验并读掌握度，不会触发知识构建或修改设置。", flush=True)

    with httpx.Client(
        base_url=args.api_base,
        timeout=httpx.Timeout(180.0, connect=10.0),
        headers={"User-Agent": "studymate-demo-seed/1.0"},
    ) as client:
        health = request(client, "GET", "/health", expected=200).json()
        print(f"health: {health}", flush=True)
        for target in targets:
            run_course(client, target, args.rounds, args.seed)

    print("\nALL DEMO SEED CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
