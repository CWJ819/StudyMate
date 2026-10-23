"""v5 知识构建流水线：Stage A 大纲（KnowledgeOutlineService）→ Stage B 按
section 并发抽取叶子（缓存 + 截止时间 + 有界重试）→ Stage C 合并、校验、
稳定身份、原子激活。

关键工程约束：
- SQLite 写入集中在主线程短事务（进度/缓存/llm_calls 各自独立提交），
  构建事务只在最终持久化时持锁；
- LLM 并发仅限外部调用（ThreadPool 3，有界提交：池内最多 3 个任务）；
- 全局预算 BuildBudget 由大纲与抽取共享：可用预算不足一次有效调用时不再
  发起请求，直接以 JOB_DEADLINE_EXCEEDED 收尾；总截止低于
  job_lock_timeout_seconds(300s)；
- 终态错误码由首个根因失败决定，取消/超时产生的辅助错误不覆盖它；
- 进度只统计成功单元（缓存命中算成功），失败/跳过不计入 completed；
- 断点缓存只存通过 Pydantic 校验的结果，构建失败后重触发可续跑；
- 身份规则：叶子 stable_key 与树路径无关；旧节点仅在匹配唯一（或唯一
  有学习数据）时复用，绝不合并两份掌握度（GPT 方案修正案）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from concurrent.futures import (
    CancelledError,
    Future,
    ThreadPoolExecutor,
    wait,
)
from concurrent.futures import FIRST_COMPLETED
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models.knowledge import KnowledgeFrameworkVersion, KnowledgeNode
from app.db.models.llm_call import LLMCall
from app.db.models.mastery import StudentGapState
from app.db.session import session_scope
from app.llm.base import LLMTemporaryError
from app.llm.prompts.knowledge_framework_v5 import (
    FRAMEWORK_PROMPT_VERSION,
    SYSTEM_PROMPT,
)
from app.llm.schemas import (
    RELATION_TYPES,
    KnowledgeSectionExtractionV5,
    KnowledgeSourceCandidate,
    LLMStructuredResult,
)
from app.repositories.job_repository import JobRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.services.knowledge_alignment import (
    AlignmentLeaf,
    MergeDecision,
    align_leaves,
    dedupe_relations,
    remap_relation_keys,
)
from app.services.knowledge_outline_service import (
    OUTLINE_PARSER_VERSION,
    MergedSection,
    OutlineCallRecord,
    classify_heading,
    KnowledgeOutlineService,
)

logger = logging.getLogger(__name__)

BUILDER_VERSION = "v5"
SECTION_WINDOW_CHAR_LIMIT = 28000
SECTION_EXTRACT_CONCURRENCY = 3
# 叶子预算随窗口覆盖页数缩放：伞形章把窗口合并后，固定 10 会让叶子总量被
# "窗口数 × 10" 封顶（2026-10-22 实测 425 页只有 217 叶）。幻灯片型课件里
# "页"才是内容单位（实测平均 220 字/页，按字符校准的公式恒落下限），所以
# 用 pages // 2 线性放大并夹在 [10, 20]。
SECTION_MAX_LEAVES_HINT = 10
SECTION_MAX_LEAVES_LIMIT = 20
# 关系上限与 prompt 规则一致；超出部分按 confidence 从高到低保留，其余丢弃。
MAX_RELATIONS_PER_LEAF = 3
MAX_RELATION_EVIDENCE_CHARS = 200
BUILD_DEADLINE_SECONDS = 270
# 截止时间模型（见 docs/reviews/v5-knowledge-pipeline-handoff-2026-10-21.md §3）：
# - finalization_reserve：留给终态写回/激活的时间，不能再被请求占用；
# - min_request_window：启动一次逻辑调用所需的最小可用预算；不足就停止发起，
#   直接以 JOB_DEADLINE_EXCEEDED 收尾，而不是发一个注定超时的短请求；
# - min_attempt_timeout：单次 HTTP 尝试的超时下限，低于它就不要发。
FINALIZATION_RESERVE_SECONDS = 10
MIN_REQUEST_WINDOW_SECONDS = 30
MIN_ATTEMPT_TIMEOUT_SECONDS = 15
MAX_SOURCES_PER_LEAF = 6
MAX_LEAF_TITLE_CHARS = 120
MIN_LEAF_CONTENT_CHARS = 24

# 全局进度单调映射；succeeded 固定 100 由 mark_succeeded 写入。
PHASE_BOUNDS = {
    "outline": (1, 15),
    "extract": (15, 70),
    "merge": (70, 82),
    "validate": (82, 95),
    "activate": (95, 99),
}

REJECTED_TOPIC_MARKERS = (
    "table of contents",
    "contents",
    "agenda",
    "acknowledgement",
    "acknowledgment",
    "copyright",
    "course outline",
    "chapter outline",
    "目录",
)


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameworkSourceUnit:
    document_id: str
    filename: str
    page_number: int
    page_end: int
    text: str
    chunk_id: str | None = None


@dataclass(frozen=True)
class SectionWindow:
    window_index: int
    chapter_index: int
    section_index: int  # 0 = 直接挂在 chapter 下（该章无小节）
    section_path: list[str]
    page_ranges: list[tuple[str, int, int]]
    units: list[FrameworkSourceUnit]
    content_hash: str
    cache_key: str
    payload: dict[str, Any]


@dataclass
class WindowCallMeta:
    model_name: str = ""
    prompt_version: str = FRAMEWORK_PROMPT_VERSION
    latency_ms: int | None = None
    attempts: int | None = None
    input_chars: int | None = None
    output_chars: int | None = None
    # started=False 表示这次逻辑任务没有真正发出 HTTP 请求（预算不足/被取消）
    started: bool = False
    status: str = "succeeded"
    error_code: str | None = None


@dataclass
class WindowOutcome:
    window: SectionWindow
    ok: bool
    data: KnowledgeSectionExtractionV5 | None = None
    meta: WindowCallMeta | None = None
    error: Exception | None = None
    cached: bool = False


@dataclass
class OldLeafRef:
    knowledge_node_id: str
    title: str
    has_learning_data: bool


@dataclass(frozen=True)
class IdentityDecision:
    reuse_node_id: str | None
    orphaned: bool  # 多个同名候选且其中多个带学习数据 → 显式孤儿化


@dataclass
class PendingLeaf:
    title: str
    content: str
    section_label: str | None
    sources: list[KnowledgeSourceCandidate]
    # 跨 section/文档对齐后留下的别名与合并方式；singleton 为空/None。
    aliases: list[str] = field(default_factory=list)
    merge_method: str | None = None
    similarity: float | None = None


@dataclass(frozen=True)
class PendingRelation:
    """待落库的叶子关系。

    source_key/target_key 是规范化叶子标题（`normalize_title_key`），不是 LLM
    的 ref：跨窗口合并后同一概念只剩一个 leaf，ref 只在单次输出内有意义。
    """

    source_key: str
    target_key: str
    relation_type: str
    confidence: float
    evidence: str | None = None


@dataclass
class PendingContainer:
    title: str
    level: int
    section_label: str | None
    leaves: list[PendingLeaf] = field(default_factory=list)
    children: list[PendingContainer] = field(default_factory=list)
    relations: list[PendingRelation] = field(default_factory=list)


@dataclass
class BuildDiagnostics:
    windows: int = 0
    cached_windows: int = 0
    llm_calls: int = 0
    dropped_leaves: int = 0
    reused_nodes: int = 0
    new_nodes: int = 0
    orphaned_nodes: int = 0
    # 关系：kept 是真正落库的行数；dropped 是所有"模型给了但没落库"的关系，
    # 包含非法 ref/类型/置信度、自环、去重输家、超上限与端点丢失。
    relations_kept: int = 0
    relations_dropped: int = 0
    # 版本级唯一守卫：同一 stable_key 的叶再次出现（对齐漏网）被跳过的次数。
    duplicate_leaf_occurrences: int = 0
    merge_decisions: list[MergeDecision] = field(default_factory=list)
    # 进度与终态诊断：completed_units 只统计成功，失败/跳过分开计
    succeeded_units: int = 0
    failed_units: int = 0
    skipped_units: int = 0
    cancelled_units: int = 0
    terminal_reason: str | None = None


# --------------------------------------------------------------------------
# 纯工具函数（供单测直接覆盖）
# --------------------------------------------------------------------------


def normalize_source_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").split("\n")]
    normalized_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank and normalized_lines:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(line)
        previous_blank = False
    return "\n".join(normalized_lines).strip()


def normalize_title_key(title: str) -> str:
    return " ".join(title.casefold().split())


def is_quality_topic(title: str, content: str | None) -> bool:
    normalized_title = " ".join(title.split())
    normalized_content = " ".join((content or "").split())
    combined = f"{normalized_title} {normalized_content}".casefold()
    if not normalized_title or len(normalized_title) > MAX_LEAF_TITLE_CHARS:
        return False
    if any(marker in combined for marker in REJECTED_TOPIC_MARKERS):
        return False
    if not normalized_content or len(normalized_content) < MIN_LEAF_CONTENT_CHARS:
        return False
    return True


def section_label_from_title(title: str) -> str | None:
    heading = classify_heading(title)
    return heading[1] if heading else None


def compute_phase_progress(phase: str, completed: int, total: int) -> int:
    start, end = PHASE_BOUNDS[phase]
    if total <= 0:
        return start
    ratio = max(0, min(1, completed / total))
    return start + int((end - start) * ratio)


def count_window_pages(units: list[FrameworkSourceUnit]) -> int:
    """窗口覆盖的页跨度：同一文档取 max(page_end)-min(page_number)+1，多文档相加。

    页是幻灯片型课件的内容单位，比字符数稳定；窗口切分仍只看字符数，两者互不
    影响（缓存键把预算也纳入了，见 _section_cache_key）。
    """
    spans: dict[str, tuple[int, int]] = {}
    for unit in units:
        current = spans.get(unit.document_id)
        if current is None:
            spans[unit.document_id] = (unit.page_number, unit.page_end)
        else:
            spans[unit.document_id] = (
                min(current[0], unit.page_number),
                max(current[1], unit.page_end),
            )
    return sum(end - start + 1 for start, end in spans.values())


def compute_max_leaves_hint(page_count: int) -> int:
    """按窗口覆盖页数给出叶子预算：每 2 页 1 个叶子，夹在 [10, 20]。

    纯函数便于单测；3 页的窗口仍要 10（下限），46 页的窗口给 20（上限）。
    """
    if page_count <= 0:
        return SECTION_MAX_LEAVES_HINT
    return max(SECTION_MAX_LEAVES_HINT, min(SECTION_MAX_LEAVES_LIMIT, page_count // 2))


def compute_content_hash(units: list[FrameworkSourceUnit]) -> str:
    parts = [
        f"{unit.document_id}|{unit.chunk_id or '-'}|{unit.page_number}|{unit.page_end}|"
        f"{hashlib.sha256(unit.text.encode('utf-8')).hexdigest()}"
        for unit in units
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def compute_leaf_stable_key(
    course_id: str, title: str, primary_document_id: str, primary_page_number: int
) -> str:
    payload = f"{course_id}|{normalize_title_key(title)}|{primary_document_id}|{primary_page_number}"
    return "v1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_container_stable_key(course_id: str, path_titles: list[str]) -> str:
    joined = " > ".join(normalize_title_key(title) for title in path_titles)
    return "v5path::" + hashlib.sha256(
        f"{course_id}|{joined}".encode("utf-8")
    ).hexdigest()


def compute_source_fingerprint(documents: list[Any]) -> str:
    parts: list[str] = []
    for document in documents:
        chunk_hashes = sorted(chunk.content_hash or "" for chunk in document.chunks)
        parts.append(f"{document.id}:{len(document.pages)}:{';'.join(chunk_hashes)}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _dedupe_sources(sources: list[KnowledgeSourceCandidate]) -> list[KnowledgeSourceCandidate]:
    seen: set[tuple[str, int, str | None]] = set()
    deduped: list[KnowledgeSourceCandidate] = []
    for source in sources:
        key = (source.document_id, source.page_number, source.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _provider_hash() -> str:
    base_url = (get_settings().llm_base_url or "").strip()
    return hashlib.sha256(base_url.encode("utf-8")).hexdigest()[:16]


def _stopping(stop_event: threading.Event | None) -> bool:
    return stop_event is not None and stop_event.is_set()


def _section_cache_key(
    content_hash: str,
    model_name: str,
    section_path: list[str] | None = None,
    page_ranges: list[tuple[str, int, int]] | None = None,
    max_leaves: int = 0,
) -> str:
    """缓存键包含结构指纹（解析器版本 + 规范化路径 + 页码区间）与本次叶子预算。

    只按文本内容做键会在"章节边界变、文本不变"时误命中旧抽取结果；预算不
    进键则调参后会命中旧预算的抽取结果、看起来"改了没效果"。
    """
    path_key = " > ".join(normalize_title_key(title) for title in (section_path or []))
    range_key = ";".join(
        f"{document_id}:{start}-{end}"
        for document_id, start, end in sorted(page_ranges or [])
    )
    payload = (
        f"v5-section|{OUTLINE_PARSER_VERSION}|{path_key}|{range_key}|{content_hash}|"
        f"{FRAMEWORK_PROMPT_VERSION}|{model_name}|{_provider_hash()}|leaves:{max_leaves}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _adapter_model_name(adapter: Any) -> str:
    settings = getattr(adapter, "settings", None)
    model = getattr(settings, "llm_model", None)
    if model:
        return model
    return type(adapter).__name__


# --------------------------------------------------------------------------
# 身份裁决 / 预算 / 进度
# --------------------------------------------------------------------------


class IdentityResolver:
    """纯逻辑身份裁决：按规范化标题在旧 active 版本叶子中匹配。

    - 唯一匹配 → 复用；
    - 多个候选 → 仅当恰有一个带学习数据时复用该节点，否则新建
      （多个带数据时新建并计孤儿化，绝不合并两份掌握度）；
    - 零匹配 → 新建。
    """

    def __init__(self, old_leaves: list[OldLeafRef]) -> None:
        self._by_title: dict[str, list[OldLeafRef]] = {}
        for leaf in old_leaves:
            self._by_title.setdefault(normalize_title_key(leaf.title), []).append(leaf)

    def resolve(self, title: str) -> IdentityDecision:
        candidates = self._by_title.get(normalize_title_key(title), [])
        if len(candidates) == 1:
            return IdentityDecision(
                reuse_node_id=candidates[0].knowledge_node_id, orphaned=False
            )
        if len(candidates) > 1:
            with_data = [item for item in candidates if item.has_learning_data]
            if len(with_data) == 1:
                return IdentityDecision(
                    reuse_node_id=with_data[0].knowledge_node_id, orphaned=False
                )
            return IdentityDecision(reuse_node_id=None, orphaned=True)
        return IdentityDecision(reuse_node_id=None, orphaned=False)


class BuildBudget:
    """全局截止时间：Stage A 大纲与 Stage B 抽取共享同一份预算。

    预算模型：
    - available = remaining - finalization_reserve，终态写回不能被请求占用；
    - available 低于 min_request_window 时不再发起任何调用，直接
      JOB_DEADLINE_EXCEEDED（不是先发一个注定超时的短请求）；
    - 单次调用超时按时段均摊内层重试次数，且不低于
      min_attempt_timeout，保证"发出去的请求有机会跑完"。
    """

    def __init__(
        self,
        deadline_seconds: float | None = None,
        clock: Callable[[], float] | None = None,
        settings: Any | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        # 用适配器实际生效的设置（设置页的 DB 覆盖优先于环境变量），
        # 否则"内层重试次数/单次超时"会算少，预算可能被突破。
        self._settings = settings
        total = BUILD_DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
        self.deadline = self._clock() + total
        self.deadline_seconds = total

    @property
    def settings(self) -> Any:
        return self._settings if self._settings is not None else get_settings()

    @property
    def remaining(self) -> float:
        return self.deadline - self._clock()

    @property
    def available(self) -> float:
        return self.remaining - FINALIZATION_RESERVE_SECONDS

    @property
    def inner_attempts(self) -> int:
        return max(1, self.settings.llm_max_retries + 1)

    @property
    def min_request_window(self) -> float:
        return max(
            MIN_REQUEST_WINDOW_SECONDS, self.inner_attempts * MIN_ATTEMPT_TIMEOUT_SECONDS
        )

    def ensure_call_possible(self) -> None:
        if self.available < self.min_request_window:
            raise AppError(
                code="JOB_DEADLINE_EXCEEDED",
                message="Knowledge build exceeded its total time budget.",
                status_code=500,
                details={
                    "remaining_seconds": round(self.remaining, 1),
                    "required_seconds": round(self.min_request_window, 1),
                    "phase": "extract",
                },
            )

    def call_timeout(self) -> int:
        """单次 HTTP 尝试的超时；预算不足时抛 JOB_DEADLINE_EXCEEDED。

        下限只约束"预算切片"：服务商本身配置的超时更短时，按服务商的值发。
        """
        per_attempt = self.available / self.inner_attempts
        provider_timeout = self.settings.llm_timeout_seconds
        if per_attempt < min(MIN_ATTEMPT_TIMEOUT_SECONDS, provider_timeout):
            raise AppError(
                code="JOB_DEADLINE_EXCEEDED",
                message="Knowledge build exceeded its total time budget.",
                status_code=500,
                details={
                    "remaining_seconds": round(self.remaining, 1),
                    "required_seconds": round(self.min_request_window, 1),
                    "phase": "extract",
                },
            )
        return int(max(1, min(provider_timeout, per_attempt)))

    def allows_retry(self) -> bool:
        return self.available >= self.min_request_window


class ProgressReporter:
    """进度写入走独立短事务会话；单调不回退，失败只记日志不中断构建。"""

    def __init__(self, job_id: str | None) -> None:
        self.job_id = job_id
        self._repository = JobRepository()

    def update(
        self, phase: str, completed: int, total: int, message: str | None = None
    ) -> None:
        if not self.job_id:
            return
        progress = compute_phase_progress(phase, completed, total)
        try:
            with session_scope() as session:
                self._repository.update_progress(
                    session,
                    self.job_id,
                    progress=progress,
                    phase=phase,
                    completed_units=completed,
                    total_units=total,
                    message=message,
                )
                session.commit()
        except Exception:
            logger.warning(
                "Failed to persist build progress", extra={"job_id": self.job_id}
            )


class RepositoryOutlineCache:
    """Stage A 大纲缓存的 DB 实现：独立短事务，读写失败只记日志不中断构建。"""

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def get(self, cache_key: str) -> dict | None:
        try:
            with session_scope() as session:
                return self.repository.get_outline_cache_payload(
                    session, cache_key=cache_key
                )
        except Exception:
            logger.warning(
                "Failed to read outline cache", extra={"cache_key": cache_key}
            )
            return None

    def put(
        self,
        cache_key: str,
        *,
        document_id: str,
        content_hash: str,
        prompt_version: str,
        model_name: str,
        payload: dict,
    ) -> None:
        try:
            with session_scope() as session:
                self.repository.add_outline_cache_entry(
                    session,
                    cache_key=cache_key,
                    document_id=document_id,
                    content_hash=content_hash,
                    parser_version=OUTLINE_PARSER_VERSION,
                    prompt_version=prompt_version,
                    model_name=model_name,
                    provider_hash=_provider_hash(),
                    payload_json=payload,
                )
                session.commit()
        except Exception:
            logger.warning(
                "Failed to persist outline cache", extra={"cache_key": cache_key}
            )


# --------------------------------------------------------------------------
# 流水线
# --------------------------------------------------------------------------


class KnowledgeBuildPipeline:
    def __init__(self, repository: KnowledgeRepository | None = None) -> None:
        self.repository = repository or KnowledgeRepository()

    def run(
        self,
        session: Session,
        *,
        adapter: Any,
        course: Any,
        version: KnowledgeFrameworkVersion,
        documents: list[Any],
        reference_outline: str | None,
        job_id: str | None = None,
    ) -> BuildDiagnostics:
        diagnostics = BuildDiagnostics()
        reporter = ProgressReporter(job_id)
        # 一份预算贯穿大纲与抽取：Stage A 的 LLM 兜底同样受全局截止约束。
        # settings 取适配器实际生效的那份（设置页覆盖优先于环境变量）。
        budget = BuildBudget(settings=getattr(adapter, "settings", None))

        # ---- Stage A: outline ------------------------------------------------
        reporter.update("outline", 0, len(documents), "正在解析文档结构")
        outline_call_log: list[OutlineCallRecord] = []
        try:
            outline = KnowledgeOutlineService(
                cache=RepositoryOutlineCache(self.repository)
            ).build_course_outline(
                documents,
                adapter=adapter,
                course_name=course.name,
                reference_outline=reference_outline,
                call_log=outline_call_log,
                budget=budget,
            )
        finally:
            for record in outline_call_log:
                self._persist_llm_call(
                    job_id,
                    purpose=record.purpose,
                    prompt_version=record.prompt_version,
                    model_name=record.model_name,
                    batch_index=None,
                    latency_ms=record.latency_ms,
                    input_chars=record.input_chars,
                    output_chars=record.output_chars,
                    attempt=record.attempt,
                    status=record.status,
                    error_code=record.error_code,
                )
                diagnostics.llm_calls += 1
        if not outline:
            raise AppError(
                code="KNOWLEDGE_OUTLINE_FAILED",
                message="Document outlines produced no usable chapters.",
                status_code=502,
            )
        reporter.update("outline", len(documents), len(documents), "文档结构解析完成")

        # ---- Stage B: per-section windows -----------------------------------
        windows = self._plan_windows(adapter, documents, outline)
        diagnostics.windows = len(windows)
        if not windows:
            raise AppError(
                code="MATERIALS_NOT_READY",
                message="Parsed materials include no extractable text in any section.",
                status_code=400,
            )
        reporter.update("extract", 0, len(windows), "正在按章节抽取知识点")
        outcomes = self._extract_windows(
            session, adapter, windows, reporter, job_id, diagnostics, budget=budget
        )

        # ---- Stage C: merge / validate / persist / activate ------------------
        reporter.update("merge", 1, 1, "正在合并知识点")
        containers = self._merge_to_containers(
            session, course.id, outline, outcomes, diagnostics
        )
        reporter.update("validate", 1, 1, "正在校验知识框架")
        self._validate_containers(containers)

        reporter.update("activate", 1, 1, "正在激活知识框架")
        with session.begin_nested():
            self._persist_containers(
                session,
                course=course,
                version=version,
                containers=containers,
                documents=documents,
                diagnostics=diagnostics,
            )

        version.builder_version = BUILDER_VERSION
        version.source_fingerprint = compute_source_fingerprint(documents)
        self.repository.deactivate_active_versions(session, course.id)
        version.status = "active"
        version.activated_at = datetime.now(UTC)
        course.active_framework_version_id = version.id
        return diagnostics

    # ------------------------------------------------------------- Stage B

    def _plan_windows(
        self, adapter: Any, documents: list[Any], outline: list[MergedSection]
    ) -> list[SectionWindow]:
        doc_by_id = {document.id: document for document in documents}
        model_name = _adapter_model_name(adapter)
        windows: list[SectionWindow] = []
        for chapter_index, chapter in enumerate(outline, start=1):
            if chapter.children:
                indexed_bearers = list(enumerate(chapter.children, start=1))
            else:
                indexed_bearers = [(0, chapter)]
            for section_index, section in indexed_bearers:
                units = self._units_for_ranges(doc_by_id, section.page_ranges)
                if not units:
                    continue
                section_path = [chapter.title] + (
                    [section.title] if chapter.children else []
                )
                for window_units in self._split_units_by_budget(units):
                    content_hash = compute_content_hash(window_units)
                    payload = self._window_payload(section_path, window_units)
                    windows.append(
                        SectionWindow(
                            window_index=len(windows) + 1,
                            chapter_index=chapter_index,
                            section_index=section_index,
                            section_path=section_path,
                            page_ranges=section.page_ranges,
                            units=window_units,
                            content_hash=content_hash,
                            cache_key=_section_cache_key(
                                content_hash,
                                model_name,
                                section_path,
                                section.page_ranges,
                                max_leaves=payload["max_leaves"],
                            ),
                            payload=payload,
                        )
                    )
        return windows

    def _units_for_ranges(
        self, doc_by_id: dict[str, Any], page_ranges: list[tuple[str, int, int]]
    ) -> list[FrameworkSourceUnit]:
        units: list[FrameworkSourceUnit] = []
        for document_id, page_start, page_end in page_ranges:
            document = doc_by_id.get(document_id)
            if document is None:
                continue
            if document.chunks:
                for chunk in sorted(
                    document.chunks,
                    key=lambda item: (item.page_start, item.page_end, item.id),
                ):
                    if not chunk.text.strip():
                        continue
                    if chunk.page_start > page_end or chunk.page_end < page_start:
                        continue
                    units.append(
                        FrameworkSourceUnit(
                            document_id=document.id,
                            filename=document.filename,
                            page_number=chunk.page_start,
                            page_end=chunk.page_end,
                            text=chunk.text,
                            chunk_id=chunk.id,
                        )
                    )
                continue
            for page in sorted(document.pages, key=lambda item: item.page_number):
                text = page.extracted_text or ""
                if page.extraction_status != "extracted" or not text.strip():
                    continue
                if not page_start <= page.page_number <= page_end:
                    continue
                units.append(
                    FrameworkSourceUnit(
                        document_id=document.id,
                        filename=document.filename,
                        page_number=page.page_number,
                        page_end=page.page_number,
                        text=text,
                        chunk_id=None,
                    )
                )
        return units

    def _split_units_by_budget(
        self, units: list[FrameworkSourceUnit]
    ) -> list[list[FrameworkSourceUnit]]:
        windows: list[list[FrameworkSourceUnit]] = []
        current: list[FrameworkSourceUnit] = []
        current_chars = 0
        for unit in units:
            unit_chars = len(normalize_source_text(unit.text))
            if current and current_chars + unit_chars > SECTION_WINDOW_CHAR_LIMIT:
                windows.append(current)
                current = []
                current_chars = 0
            current.append(unit)
            current_chars += unit_chars
        if current:
            windows.append(current)
        return windows

    def _window_payload(
        self, section_path: list[str], units: list[FrameworkSourceUnit]
    ) -> dict[str, Any]:
        segments = [
            {
                "document_id": unit.document_id,
                "chunk_id": unit.chunk_id,
                "page_start": unit.page_number,
                "page_end": unit.page_end,
                "text": normalize_source_text(unit.text),
            }
            for unit in units
        ]
        pages = [unit.page_number for unit in units]
        return {
            "section_path": section_path,
            "page_range": [min(pages), max(pages)],
            "max_leaves": compute_max_leaves_hint(count_window_pages(units)),
            "source_segments": segments,
        }

    def _extract_windows(
        self,
        session: Session,
        adapter: Any,
        windows: list[SectionWindow],
        reporter: ProgressReporter,
        job_id: str | None,
        diagnostics: BuildDiagnostics,
        budget: BuildBudget | None = None,
    ) -> list[WindowOutcome]:
        """有界提交 + 单一终态原因。

        - 线程池里最多只有 CONCURRENCY 个任务，不会预先把几百个 section 塞进
          队列后集体失败；
        - 预算不足时不再发起新请求，直接以 JOB_DEADLINE_EXCEEDED 收尾；
        - 首个"根因"失败决定 job 错误码，其后因取消/超时产生的辅助错误不覆盖它；
        - completed/进度只统计成功（缓存命中算成功）。
        """
        cache_payloads = self.repository.get_section_cache_payloads(
            session, cache_keys=[window.cache_key for window in windows]
        )
        outcomes: list[WindowOutcome] = []
        pending: list[SectionWindow] = []
        for window in windows:
            if window.cache_key in cache_payloads:
                outcomes.append(
                    WindowOutcome(
                        window=window,
                        ok=True,
                        data=KnowledgeSectionExtractionV5.model_validate(
                            cache_payloads[window.cache_key]
                        ),
                        cached=True,
                    )
                )
            else:
                pending.append(window)
        completed = len(outcomes)
        diagnostics.cached_windows = completed
        if completed:
            reporter.update(
                "extract",
                completed,
                len(windows),
                f"已抽取 {completed}/{len(windows)} 个片段（缓存）",
            )

        budget = budget or BuildBudget()
        stop_event = threading.Event()
        executor = ThreadPoolExecutor(max_workers=SECTION_EXTRACT_CONCURRENCY)
        inflight: dict[Future, SectionWindow] = {}
        queue: deque[SectionWindow] = deque(pending)
        terminal: WindowOutcome | None = None

        try:
            while True:
                while (
                    not stop_event.is_set()
                    and queue
                    and len(inflight) < SECTION_EXTRACT_CONCURRENCY
                ):
                    window = queue.popleft()
                    try:
                        budget.ensure_call_possible()
                    except AppError as exc:
                        # 预算已不够完成一次有效调用：不提交，直接终止原因
                        stop_event.set()
                        terminal = WindowOutcome(
                            window=window,
                            ok=False,
                            error=exc,
                            meta=WindowCallMeta(
                                status="skipped_deadline",
                                error_code=exc.code,
                                input_chars=len(
                                    json.dumps(window.payload, ensure_ascii=False)
                                ),
                            ),
                        )
                        outcomes.append(terminal)
                        diagnostics.skipped_units += 1
                        self._persist_window_call(job_id, terminal)
                        break
                    inflight[
                        executor.submit(
                            self._run_window, adapter, window, budget, stop_event
                        )
                    ] = window

                if stop_event.is_set() and queue:
                    # 预算不足或已判定失败：未提交的窗口一律取消
                    diagnostics.cancelled_units += len(queue)
                    queue.clear()

                if not inflight:
                    break

                done, _ = wait(tuple(inflight), return_when=FIRST_COMPLETED)
                for future in done:
                    inflight.pop(future, None)
                    try:
                        outcome = future.result()
                    except CancelledError:
                        diagnostics.cancelled_units += 1
                        continue
                    outcomes.append(outcome)
                    meta = outcome.meta
                    if meta is not None and meta.started:
                        diagnostics.llm_calls += 1
                    if outcome.ok and not outcome.cached:
                        self._persist_section_cache(outcome)
                    self._persist_window_call(job_id, outcome)

                    if outcome.ok:
                        completed += 1
                        diagnostics.succeeded_units += 1
                        if not outcome.cached:
                            reporter.update(
                                "extract",
                                completed,
                                len(windows),
                                f"已抽取 {completed}/{len(windows)} 个片段",
                            )
                        continue

                    if meta is not None and meta.status == "skipped_deadline":
                        diagnostics.skipped_units += 1
                    elif meta is not None and meta.status == "cancelled":
                        diagnostics.cancelled_units += 1
                    else:
                        diagnostics.failed_units += 1
                    if terminal is None:
                        terminal = outcome
                    stop_event.set()

                if stop_event.is_set() and queue:
                    # 未提交的窗口一律取消，不再生成注定失败的调用
                    diagnostics.cancelled_units += len(queue)
                    if terminal is not None:
                        diagnostics.terminal_reason = (
                            getattr(terminal.error, "code", None)
                            or "KNOWLEDGE_EXTRACTION_FAILED"
                        )
                    queue.clear()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        outcomes.sort(key=lambda item: item.window.window_index)
        diagnostics.cached_windows = sum(1 for item in outcomes if item.cached)
        diagnostics.succeeded_units = sum(1 for item in outcomes if item.ok)

        if terminal is not None:
            diagnostics.terminal_reason = (
                getattr(terminal.error, "code", None)
                or "KNOWLEDGE_EXTRACTION_FAILED"
            )
            raise self._terminal_error(terminal)
        if len(outcomes) != len(windows):
            raise AppError(
                code="KNOWLEDGE_EXTRACTION_FAILED",
                message=(
                    "Knowledge section extraction did not complete every planned window."
                ),
                status_code=502,
                details={"completed": len(outcomes), "planned": len(windows)},
            )
        return outcomes

    def _terminal_error(self, outcome: WindowOutcome) -> AppError:
        """把根因失败转成 job 终态错误；保留原始错误码，不做"最先完成"推断。"""
        error = outcome.error
        if isinstance(error, AppError):
            return error
        code = getattr(error, "code", None) or "KNOWLEDGE_EXTRACTION_FAILED"
        message = (
            getattr(error, "message", None)
            or "Knowledge section extraction failed."
        )
        return AppError(
            code=code,
            message=message,
            status_code=502,
            details={"window": outcome.window.window_index},
        )

    def _run_window(
        self,
        adapter: Any,
        window: SectionWindow,
        budget: BuildBudget,
        stop_event: threading.Event | None = None,
    ) -> WindowOutcome:
        payload_chars = len(json.dumps(window.payload, ensure_ascii=False))
        meta = WindowCallMeta(
            input_chars=payload_chars,
            model_name=_adapter_model_name(adapter),
        )
        last_error: Exception | None = None
        attempts_allowed = 2
        for attempt in range(attempts_allowed):
            if _stopping(stop_event):
                meta.status = "cancelled"
                return WindowOutcome(window=window, ok=False, error=None, meta=meta)
            try:
                # 先确认预算足够，再计算超时；两步都可能抛 JOB_DEADLINE_EXCEEDED
                budget.ensure_call_possible()
                timeout_seconds = budget.call_timeout()
            except AppError as exc:
                meta.status = "skipped_deadline"
                meta.error_code = exc.code
                return WindowOutcome(window=window, ok=False, error=exc, meta=meta)

            meta.started = True
            try:
                result: LLMStructuredResult = adapter.generate_structured_output(
                    prompt_version=FRAMEWORK_PROMPT_VERSION,
                    system_prompt=SYSTEM_PROMPT,
                    user_payload=window.payload,
                    response_model=KnowledgeSectionExtractionV5,
                    timeout_seconds=timeout_seconds,
                )
            except LLMTemporaryError as exc:
                last_error = exc
                if (
                    attempt + 1 < attempts_allowed
                    and budget.allows_retry()
                    and not _stopping(stop_event)
                ):
                    continue
                meta.status = "failed"
                meta.error_code = exc.code
                return WindowOutcome(window=window, ok=False, error=exc, meta=meta)
            except AppError as exc:
                meta.status = "failed"
                meta.error_code = exc.code
                return WindowOutcome(window=window, ok=False, error=exc, meta=meta)

            meta.model_name = result.summary.model_name or meta.model_name
            meta.latency_ms = result.summary.latency_ms
            meta.attempts = result.summary.attempts
            meta.output_chars = len(
                json.dumps(result.data.model_dump(), ensure_ascii=False)
            )
            meta.status = "succeeded"
            return WindowOutcome(window=window, ok=True, data=result.data, meta=meta)

        meta.status = "failed"
        return WindowOutcome(
            window=window,
            ok=False,
            error=last_error
            or AppError(
                code="KNOWLEDGE_EXTRACTION_FAILED",
                message="Knowledge section extraction failed.",
                status_code=502,
            ),
            meta=meta,
        )

    # ------------------------------------------------------------- Stage C

    def _merge_to_containers(
        self,
        session: Session,
        course_id: str,
        outline: list[MergedSection],
        outcomes: list[WindowOutcome],
        diagnostics: BuildDiagnostics,
    ) -> list[PendingContainer]:
        outcomes_by_section: dict[tuple[int, int], list[WindowOutcome]] = {}
        for outcome in outcomes:
            key = (outcome.window.chapter_index, outcome.window.section_index)
            outcomes_by_section.setdefault(key, []).append(outcome)

        containers: list[PendingContainer] = []
        for chapter_index, chapter in enumerate(outline, start=1):
            chapter_container = PendingContainer(
                title=chapter.title,
                level=1,
                section_label=section_label_from_title(chapter.title),
            )
            if chapter.children:
                for section_index, section in enumerate(chapter.children, start=1):
                    section_container = PendingContainer(
                        title=section.title,
                        level=2,
                        section_label=section_label_from_title(section.title),
                    )
                    section_container.leaves, section_container.relations = self._collect_leaves(
                        session,
                        section,
                        outcomes_by_section.get((chapter_index, section_index), []),
                        diagnostics,
                    )
                    chapter_container.children.append(section_container)
            else:
                chapter_container.leaves, chapter_container.relations = self._collect_leaves(
                    session,
                    chapter,
                    outcomes_by_section.get((chapter_index, 0), []),
                    diagnostics,
                )
            containers.append(chapter_container)
        containers = self._prune_containers(containers)
        containers = self._align_containers(
            session, course_id, containers, diagnostics
        )
        return self._prune_containers(containers)

    def _align_containers(
        self,
        session: Session,
        course_id: str,
        containers: list[PendingContainer],
        diagnostics: BuildDiagnostics,
    ) -> list[PendingContainer]:
        """跨 section 对齐叶子，并把关系 key 改指 canonical 叶。

        对齐是 Stage C 的纯后处理：输入只来自已通过来源校验的 PendingLeaf，
        不重抽、不改 section 缓存；canonical 叶留在其原始 section。
        """
        origin_container: dict[int, PendingContainer] = {}
        flattened: list[AlignmentLeaf] = []
        origin = 0

        def add_leaves(container: PendingContainer, path: list[str]) -> None:
            nonlocal origin
            for leaf in container.leaves:
                origin_container[origin] = container
                flattened.append(
                    AlignmentLeaf(
                        title=leaf.title,
                        content=leaf.content,
                        section_label=leaf.section_label,
                        sources=tuple(leaf.sources),
                        section_path=tuple(path),
                        origin=origin,
                    )
                )
                origin += 1

        for chapter in containers:
            if chapter.children:
                for section in chapter.children:
                    add_leaves(section, [chapter.title, section.title])
            else:
                add_leaves(chapter, [chapter.title])

        locked_pairs = set(
            self.repository.list_alias_locks(session, course_id=course_id)
        )
        result = align_leaves(
            flattened,
            locked_pairs=locked_pairs,
            max_sources=MAX_SOURCES_PER_LEAF,
        )
        diagnostics.merge_decisions = list(result.decisions)

        aligned_by_container: dict[int, list[tuple[int, AlignmentLeaf]]] = {}
        for leaf in result.leaves:
            container = origin_container[leaf.origin]
            aligned_by_container.setdefault(id(container), []).append(
                (leaf.origin, leaf)
            )

        for chapter in containers:
            chapter_containers = [chapter, *chapter.children]
            for container in chapter_containers:
                entries = aligned_by_container.get(id(container), [])
                entries.sort(key=lambda item: item[0])
                container.leaves = [
                    PendingLeaf(
                        title=leaf.title,
                        content=leaf.content,
                        section_label=leaf.section_label,
                        sources=list(leaf.sources),
                        aliases=list(leaf.aliases),
                        merge_method=leaf.merge_method,
                        similarity=leaf.similarity,
                    )
                    for _, leaf in entries
                ]
                if result.canonical_by_title:
                    container.relations = remap_relation_keys(
                        container.relations,
                        result.canonical_by_title,
                        normalize_key=normalize_title_key,
                    )
        return containers

    def _collect_leaves(
        self,
        session: Session,
        section: MergedSection,
        outcomes: list[WindowOutcome],
        diagnostics: BuildDiagnostics,
    ) -> tuple[list[PendingLeaf], list[PendingRelation]]:
        """合并窗口输出为 section 叶子，并同时收集通过校验的关系。

        关系在"叶子质量过滤 + 来源校验"之后才解析 ref：模型引用一个已被丢弃
        的叶子时那条关系必须一起丢弃，不能落一条指向不存在的边。
        """
        valid_pages: set[tuple[str, int]] = set()
        for document_id, page_start, page_end in section.page_ranges:
            for page in range(page_start, page_end + 1):
                valid_pages.add((document_id, page))

        merged: dict[str, PendingLeaf] = {}
        edges: dict[tuple[str, str, str], PendingRelation] = {}
        for outcome in outcomes:
            if outcome.data is None:
                continue
            ref_to_key: dict[str, str] = {}
            ambiguous_refs: set[str] = set()
            for leaf in outcome.data.leaves:
                title = " ".join(leaf.title.split()).strip()
                if not is_quality_topic(title, leaf.content):
                    diagnostics.dropped_leaves += 1
                    continue
                sources: list[KnowledgeSourceCandidate] = []
                for source in leaf.sources:
                    if (source.document_id, source.page_number) not in valid_pages:
                        continue
                    if source.chunk_id and not self.repository.chunk_belongs_to_document(
                        session,
                        chunk_id=source.chunk_id,
                        document_id=source.document_id,
                    ):
                        continue
                    sources.append(source)
                sources = _dedupe_sources(sources)[:MAX_SOURCES_PER_LEAF]
                if not sources:
                    diagnostics.dropped_leaves += 1
                    continue
                key = normalize_title_key(title)
                # ref 只在叶子通过全部校验后才可被关系引用；同一 ref 指向两个
                # 不同标题时无法判定模型意图，整个 ref 作废。
                ref = (leaf.ref or "").strip()
                if ref:
                    previous = ref_to_key.get(ref)
                    if previous is not None and previous != key:
                        ambiguous_refs.add(ref)
                    ref_to_key[ref] = key
                existing = merged.get(key)
                if existing is None:
                    merged[key] = PendingLeaf(
                        title=title,
                        content=leaf.content,
                        section_label=section_label_from_title(section.title),
                        sources=sources,
                    )
                else:
                    existing.sources = _dedupe_sources([*existing.sources, *sources])[
                        :MAX_SOURCES_PER_LEAF
                    ]
                    if len(leaf.content or "") > len(existing.content or ""):
                        existing.content = leaf.content
            for ref in ambiguous_refs:
                ref_to_key.pop(ref, None)
            self._collect_relations(outcome, ref_to_key, edges, diagnostics)

        leaves = list(merged.values())
        leaves.sort(
            key=lambda item: (
                min((source.page_number, source.document_id) for source in item.sources),
                normalize_title_key(item.title),
            )
        )
        return leaves, self._cap_relations(edges, diagnostics)

    def _collect_relations(
        self,
        outcome: WindowOutcome,
        ref_to_key: dict[str, str],
        edges: dict[tuple[str, str, str], PendingRelation],
        diagnostics: BuildDiagnostics,
    ) -> None:
        """把单窗口的 ref 关系解析成叶子标题对，按 (无向边, 类型) 去重留高置信度。"""
        if outcome.data is None:
            return
        for relation in outcome.data.relations:
            source_key = ref_to_key.get(relation.source_ref.strip())
            target_key = ref_to_key.get(relation.target_ref.strip())
            if source_key is None or target_key is None or source_key == target_key:
                diagnostics.relations_dropped += 1
                continue
            relation_type = relation.relation_type.strip()
            if relation_type not in RELATION_TYPES:
                diagnostics.relations_dropped += 1
                continue
            confidence = float(relation.confidence)
            if not 0.0 <= confidence <= 1.0:
                diagnostics.relations_dropped += 1
                continue
            edge_key = (
                min(source_key, target_key),
                max(source_key, target_key),
                relation_type,
            )
            existing = edges.get(edge_key)
            if existing is not None:
                # 同一对叶子反向重复声明：算一条边，保留置信度更高的方向
                diagnostics.relations_dropped += 1
                if confidence <= existing.confidence:
                    continue
            evidence = (relation.evidence or "").strip()[:MAX_RELATION_EVIDENCE_CHARS]
            edges[edge_key] = PendingRelation(
                source_key=source_key,
                target_key=target_key,
                relation_type=relation_type,
                confidence=confidence,
                evidence=evidence or None,
            )

    def _cap_relations(
        self,
        edges: dict[tuple[str, str, str], PendingRelation],
        diagnostics: BuildDiagnostics,
    ) -> list[PendingRelation]:
        """每叶最多 MAX_RELATIONS_PER_LEAF 条关系：按置信度从高到低保留。"""
        per_key: dict[str, int] = {}
        kept: list[PendingRelation] = []
        ordered = sorted(
            edges.values(),
            key=lambda item: (
                -item.confidence,
                item.source_key,
                item.target_key,
                item.relation_type,
            ),
        )
        for relation in ordered:
            if (
                per_key.get(relation.source_key, 0) >= MAX_RELATIONS_PER_LEAF
                or per_key.get(relation.target_key, 0) >= MAX_RELATIONS_PER_LEAF
            ):
                diagnostics.relations_dropped += 1
                continue
            per_key[relation.source_key] = per_key.get(relation.source_key, 0) + 1
            per_key[relation.target_key] = per_key.get(relation.target_key, 0) + 1
            kept.append(relation)
        return kept

    def _prune_containers(
        self, containers: list[PendingContainer]
    ) -> list[PendingContainer]:
        pruned: list[PendingContainer] = []
        for chapter in containers:
            chapter.children = [section for section in chapter.children if section.leaves]
            if chapter.leaves or chapter.children:
                pruned.append(chapter)
        return pruned

    def _validate_containers(self, containers: list[PendingContainer]) -> None:
        total_leaves = 0

        def walk(container: PendingContainer, level: int) -> None:
            nonlocal total_leaves
            if level > 4:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Knowledge tree exceeds the maximum depth of 4.",
                    status_code=502,
                )
            if container.children and container.leaves:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message=f"Container '{container.title}' mixes sections and leaves.",
                    status_code=502,
                )
            if not container.children and not container.leaves:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message=f"Container '{container.title}' is empty.",
                    status_code=502,
                )
            total_leaves += len(container.leaves)
            for child in container.children:
                walk(child, level + 1)

        for chapter in containers:
            walk(chapter, 1)
        if total_leaves == 0:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message=(
                    "Knowledge framework generation produced no source-backed "
                    "knowledge points."
                ),
                status_code=502,
            )

    def _persist_containers(
        self,
        session: Session,
        *,
        course: Any,
        version: KnowledgeFrameworkVersion,
        documents: list[Any],
        containers: list[PendingContainer],
        diagnostics: BuildDiagnostics,
    ) -> None:
        resolver = IdentityResolver(old_leaves=_load_old_leaf_refs(session, course.id))
        root_node = self.repository.get_or_create_node(
            session,
            course_id=course.id,
            stable_key=f"root::{course.name.strip().casefold()}",
        )
        root_version = self.repository.add_node_version(
            session,
            framework_version_id=version.id,
            knowledge_node_id=root_node.id,
            parent_id=None,
            title=course.name,
            section_label=None,
            content=None,
            level=0,
            is_leaf=False,
            sort_order=0,
        )

        # 关系必须等全部叶落库后再统一写：对齐后的 canonical 叶可能落在另一个
        # section，按容器局部写会把跨 section 的边误判为端点丢失。
        node_version_ids: dict[str, str] = {}
        node_version_by_node_id: dict[str, str] = {}
        persisted_leaf_node_ids: set[str] = set()
        for chapter_order, chapter in enumerate(containers, start=1):
            chapter_node = self.repository.get_or_create_node(
                session,
                course_id=course.id,
                stable_key=compute_container_stable_key(course.id, [chapter.title]),
            )
            chapter_version = self.repository.add_node_version(
                session,
                framework_version_id=version.id,
                knowledge_node_id=chapter_node.id,
                parent_id=root_version.id,
                title=chapter.title,
                section_label=chapter.section_label,
                content=None,
                level=1,
                is_leaf=False,
                sort_order=chapter_order,
            )
            if not chapter.children:
                self._persist_leaves(
                    session,
                    course=course,
                    version=version,
                    parent_id=chapter_version.id,
                    level=2,
                    leaves=chapter.leaves,
                    resolver=resolver,
                    diagnostics=diagnostics,
                    node_version_ids=node_version_ids,
                    node_version_by_node_id=node_version_by_node_id,
                    persisted_leaf_node_ids=persisted_leaf_node_ids,
                )
                continue
            for section_order, section in enumerate(chapter.children, start=1):
                section_node = self.repository.get_or_create_node(
                    session,
                    course_id=course.id,
                    stable_key=compute_container_stable_key(
                        course.id, [chapter.title, section.title]
                    ),
                )
                section_version = self.repository.add_node_version(
                    session,
                    framework_version_id=version.id,
                    knowledge_node_id=section_node.id,
                    parent_id=chapter_version.id,
                    title=section.title,
                    section_label=section.section_label,
                    content=None,
                    level=2,
                    is_leaf=False,
                    sort_order=section_order,
                )
                self._persist_leaves(
                    session,
                    course=course,
                    version=version,
                    parent_id=section_version.id,
                    level=3,
                    leaves=section.leaves,
                    resolver=resolver,
                    diagnostics=diagnostics,
                    node_version_ids=node_version_ids,
                    node_version_by_node_id=node_version_by_node_id,
                    persisted_leaf_node_ids=persisted_leaf_node_ids,
                )

        all_relations: list[PendingRelation] = []
        for chapter in containers:
            all_relations.extend(chapter.relations)
            for section in chapter.children:
                all_relations.extend(section.relations)
        all_relations = dedupe_relations(all_relations, diagnostics=diagnostics)
        self._persist_relations(
            session,
            version=version,
            relations=all_relations,
            node_version_ids=node_version_ids,
            diagnostics=diagnostics,
        )
        self._persist_merge_decisions(session, version=version, diagnostics=diagnostics)

    def _persist_leaves(
        self,
        session: Session,
        *,
        course: Any,
        version: KnowledgeFrameworkVersion,
        parent_id: str,
        level: int,
        leaves: list[PendingLeaf],
        resolver: IdentityResolver,
        diagnostics: BuildDiagnostics,
        node_version_ids: dict[str, str],
        node_version_by_node_id: dict[str, str],
        persisted_leaf_node_ids: set[str],
    ) -> None:
        """落库一个容器的叶子；版本级守卫保证一个 node 至多一行 version。

        ``node_version_ids`` 是跨容器共享的“规范化标题 → version id”映射；
        ``node_version_by_node_id`` 用于重复 occurrence 回指已存在的 version。
        """
        for leaf_order, leaf in enumerate(leaves, start=1):
            primary = min(
                (source.page_number, source.document_id, source.chunk_id or "")
                for source in leaf.sources
            )
            stable_key = compute_leaf_stable_key(
                course.id, leaf.title, primary[1], primary[0]
            )
            knowledge_node = self.repository.find_node_by_stable_key(
                session, course_id=course.id, stable_key=stable_key
            )
            if knowledge_node is None:
                decision = resolver.resolve(leaf.title)
                if decision.reuse_node_id is not None:
                    knowledge_node = session.get(
                        KnowledgeNode, decision.reuse_node_id
                    )
                if knowledge_node is not None:
                    if knowledge_node.stable_key != stable_key:
                        self.repository.update_node_stable_key(
                            session,
                            knowledge_node=knowledge_node,
                            stable_key=stable_key,
                        )
                    diagnostics.reused_nodes += 1
                else:
                    knowledge_node = self.repository.get_or_create_node(
                        session, course_id=course.id, stable_key=stable_key
                    )
                    diagnostics.new_nodes += 1
                    if decision.orphaned:
                        diagnostics.orphaned_nodes += 1
            if knowledge_node.id in persisted_leaf_node_ids:
                # 对齐漏网的结构兜底：同一框架版本内同一 node 只允许一行
                # version。关系仍指向已落库的那一行，不能产生第二个 version。
                diagnostics.duplicate_leaf_occurrences += 1
                existing_version_id = node_version_by_node_id[knowledge_node.id]
                node_version_ids.setdefault(
                    normalize_title_key(leaf.title), existing_version_id
                )
                continue
            node_version = self.repository.add_node_version(
                session,
                framework_version_id=version.id,
                knowledge_node_id=knowledge_node.id,
                parent_id=parent_id,
                title=leaf.title,
                section_label=leaf.section_label,
                content=leaf.content,
                level=level,
                is_leaf=True,
                sort_order=leaf_order,
                aliases=list(leaf.aliases) or None,
            )
            persisted_leaf_node_ids.add(knowledge_node.id)
            node_version_by_node_id[knowledge_node.id] = node_version.id
            node_version_ids.setdefault(normalize_title_key(leaf.title), node_version.id)
            for source in leaf.sources:
                self.repository.add_source(
                    session,
                    node_version_id=node_version.id,
                    document_id=source.document_id,
                    page_number=source.page_number,
                    chunk_id=source.chunk_id,
                    evidence_type=source.evidence_type,
                )

    def _persist_relations(
        self,
        session: Session,
        *,
        version: KnowledgeFrameworkVersion,
        relations: list[PendingRelation],
        node_version_ids: dict[str, str],
        diagnostics: BuildDiagnostics,
    ) -> None:
        """在叶子落库后写关系行；版本级按无序端点去重，保留高置信度方向。"""
        best: dict[tuple[str, str, str], PendingRelation] = {}
        resolved: dict[tuple[str, str, str], tuple[str, str]] = {}
        for relation in relations:
            source_id = node_version_ids.get(relation.source_key)
            target_id = node_version_ids.get(relation.target_key)
            if not source_id or not target_id or source_id == target_id:
                # 端点叶子被裁掉（或合并成同一节点）时整条边丢弃
                diagnostics.relations_dropped += 1
                continue
            edge_key = (
                min(source_id, target_id),
                max(source_id, target_id),
                relation.relation_type,
            )
            existing = best.get(edge_key)
            if existing is not None:
                diagnostics.relations_dropped += 1
                if relation.confidence <= existing.confidence:
                    continue
            best[edge_key] = relation
            resolved[edge_key] = (source_id, target_id)

        for edge_key, relation in best.items():
            source_id, target_id = resolved[edge_key]
            self.repository.add_relation(
                session,
                framework_version_id=version.id,
                source_node_version_id=source_id,
                target_node_version_id=target_id,
                relation_type=relation.relation_type,
                confidence=relation.confidence,
                evidence=relation.evidence,
            )
            diagnostics.relations_kept += 1

    def _persist_merge_decisions(
        self,
        session: Session,
        *,
        version: KnowledgeFrameworkVersion,
        diagnostics: BuildDiagnostics,
    ) -> None:
        for decision in diagnostics.merge_decisions:
            self.repository.add_merge_decision(
                session,
                framework_version_id=version.id,
                canonical_title=decision.canonical_title,
                aliases=list(decision.aliases),
                members=list(decision.members),
                distinct_documents=decision.distinct_documents,
                method=decision.method,
                similarity=decision.similarity,
            )

    # ---------------------------------------------------------- 独立事务写

    def _persist_section_cache(self, outcome: WindowOutcome) -> None:
        if outcome.data is None:
            return
        try:
            with session_scope() as session:
                self.repository.add_section_cache_entry(
                    session,
                    cache_key=outcome.window.cache_key,
                    content_hash=outcome.window.content_hash,
                    prompt_version=FRAMEWORK_PROMPT_VERSION,
                    model_name=(outcome.meta.model_name if outcome.meta else "")
                    or "unknown",
                    provider_hash=_provider_hash(),
                    payload_json=outcome.data.model_dump(),
                )
                session.commit()
        except Exception:
            logger.warning(
                "Failed to persist section cache",
                extra={"cache_key": outcome.window.cache_key},
            )

    def _persist_window_call(self, job_id: str | None, outcome: WindowOutcome) -> None:
        if outcome.cached or outcome.meta is None:
            return
        meta = outcome.meta
        if not meta.started:
            # 没有真正发出请求：只记录预算不足导致的跳过；被取消的不入观测表
            if meta.status != "skipped_deadline":
                return
            self._persist_llm_call(
                job_id,
                purpose="section_extract",
                prompt_version=meta.prompt_version,
                model_name=meta.model_name or "unknown",
                batch_index=outcome.window.window_index,
                latency_ms=None,
                input_chars=meta.input_chars,
                output_chars=None,
                attempt=0,
                status="skipped_deadline",
                error_code=meta.error_code or "JOB_DEADLINE_EXCEEDED",
            )
            return
        self._persist_llm_call(
            job_id,
            purpose="section_extract",
            prompt_version=meta.prompt_version,
            model_name=meta.model_name or "unknown",
            batch_index=outcome.window.window_index,
            latency_ms=meta.latency_ms,
            input_chars=meta.input_chars,
            output_chars=meta.output_chars,
            attempt=meta.attempts,
            status="succeeded" if outcome.ok else "failed",
            error_code=meta.error_code
            or (getattr(outcome.error, "code", None) if outcome.error else None),
        )

    def _persist_llm_call(
        self,
        job_id: str | None,
        *,
        purpose: str,
        prompt_version: str,
        model_name: str,
        batch_index: int | None,
        latency_ms: int | None,
        input_chars: int | None,
        output_chars: int | None,
        attempt: int | None,
        status: str,
        error_code: str | None,
    ) -> None:
        if not model_name:
            return
        try:
            with session_scope() as session:
                session.add(
                    LLMCall(
                        job_id=job_id,
                        purpose=purpose,
                        prompt_version=prompt_version,
                        model_name=model_name,
                        batch_index=batch_index,
                        latency_ms=latency_ms,
                        input_chars=input_chars,
                        output_chars=output_chars,
                        attempt=attempt,
                        status=status,
                        error_code=error_code,
                    )
                )
                session.commit()
        except Exception:
            logger.warning("Failed to persist llm_calls record", extra={"purpose": purpose})


def _load_old_leaf_refs(session: Session, course_id: str) -> list[OldLeafRef]:
    old_version = KnowledgeRepository().get_active_framework(session, course_id)
    if old_version is None:
        return []
    nodes_with_data = set(
        session.scalars(
            select(StudentGapState.knowledge_node_id).where(
                StudentGapState.course_id == course_id
            )
        )
    )
    refs: list[OldLeafRef] = []
    for node_version in old_version.node_versions:
        if not node_version.is_leaf:
            continue
        refs.append(
            OldLeafRef(
                knowledge_node_id=node_version.knowledge_node_id,
                title=node_version.title,
                has_learning_data=node_version.knowledge_node_id in nodes_with_data,
            )
        )
    return refs
