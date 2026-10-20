# StudyMate 后端设计复盘：资料删除、框架构建性能与知识层级

- 报告日期：2026-10-20
- 审查对象：`StudyMate/` 后端（FastAPI + SQLAlchemy 2 + SQLite + Alembic）
- 代码基线：`frontend/scaffold` 分支 HEAD `ecf0417`，另含 2026-10-20 16:44–16:54 工作区中未提交的后端补丁
- 数据基线：`StudyMate/data/studymate.db`（真实模型验收库）
- 审查方式：读代码、只读 SQLite 查询、作业时间戳核对、API/页面行为核对；**未修改后端代码**
- 读者：负责重新设计后端的 agent / 组员
- 结论：**三个问题不是三个孤立 bug，而是同一个设计取向的三个表现——知识框架被当成“一批 LLM 生成的知识点列表”，而不是“可版本化、可追溯到材料、可聚合的课程大纲”。**

---

## 0. 执行摘要

### 0.1 三个问题各自是什么

| 用户看到的问题 | 直接原因 | 设计层原因 |
|---|---|---|
| 生成知识框架后不能删除资料 | `knowledge_sources.document_id` 是 `ON DELETE RESTRICT`，服务层又提前做了“只要被引用就 409”的硬拦截 | 只有“禁止删除”的完整性约束，没有“资料删除后的生命周期”：软删除、框架失效、重建、历史来源标记 |
| 生成知识框架非常慢 | 每 12 个 chunk 调一次 LLM，串行调用；4 份材料 424 个 chunk 被拆成 37 次调用，实测 543 秒 | 批处理按“chunk 数量”而不是“章节/ token 预算”；一个 job 串完整条流水线；无缓存、无并发、无断点、无进度 |
| 知识点平铺、看不出章节、掌握度无法聚焦 | 提示词明确要求 flat list、禁止 chapter/section container；合并阶段只按文件分桶；`section_label` 只是展示字符串 | 没有“大纲抽取”这一层；文件边界被当成知识边界；层级在生成阶段被丢弃，只在合并/展示阶段临时补了两层 |

### 0.2 最重要的三个判断

1. **数据库和数据模型本身支持 3–4 层树，API 也返回嵌套 `children`，前端 `TreeRow` 也支持递归。** 问题不在表结构，而在“生成什么、如何合并、如何验证”的契约。
2. **工作区里 16:54 的未提交补丁（`_merge_batch_candidates` 改成“文档 → 知识点”）只是把 98/309 个一级叶子变成了“几个文件组 + 仍然平铺的知识点”。** 它没有章节层，也没有解决掌握度聚合；不要把该补丁当成问题 3 已修复。
3. **“慢”不是单纯把超时调大能解决的。** 37 次串行 LLM 调用是结构性的；只改 `LLM_TIMEOUT_SECONDS` 会把失败变成更长的等待。

### 0.3 建议优先级

| 优先级 | 事项 | 原因 |
|---|---|---|
| P0 | 先定“资料删除生命周期”和“知识树契约” | 这两个是产品语义，必须先拍板；否则性能优化会围绕错误结构做 |
| P0 | 大纲优先的分层生成，替代 flat list + 文件分桶 | 直接决定知识页、掌握度、复习、计划是否可用 |
| P1 | 删除资料后的 stale / rebuild / 历史来源策略 | 解除当前“建了框架就永远不能删资料”的死锁 |
| P1 | 批处理、连接复用、并发、进度、断点 | 把 9 分钟降到可接受范围，并让等待可解释 |
| P1 | 掌握度的树级聚合与章节级复习目标 | 依赖层级；否则几百个叶子仍然无法聚焦 |
| P2 | LLM 调用可观测、增量重建、树的人工修订 | 长期可维护性 |

---

## 1. 审查证据

### 1.1 真实库里的两套框架

只读查询 `data/studymate.db` 得到：

| 课程 | 活跃版本 | 节点总数 | level 0 | level 1 | level 2+ | 非空 `section_label` | 叶子来源 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `计算机网络·运输层`（`204637ae-...`） | v2 | 99 | 1 | 98 | 0 | 0 | 98 个叶子，每个 1 条来源 |
| `真实模型验收 10-20 11:09`（`96d00dc9-...`） | v2 | 310 | 1 | 309 | 0 | 288 | 309 个叶子，最多 3 条来源 |

关键事实：

- 两套框架都是 **1 个根 + 全部叶子直接挂在根下**；没有 chapter/section 容器。
- 第二套虽然有 288 个 `section_label`（如 `第3章 运输层`、`1.1`、`课程导论`），但 label 只是行内文本，**没有变成树节点**。
- 99 节点课程有 2 份材料（96 + 2 条来源），310 节点课程有 4 份材料；文件边界与知识点边界并不一致。

### 1.2 真实构建耗时

`knowledge_framework.build` 作业 `8dcfff1f-0c14-4b14-aa19-d373b021c0f7`：

```text
started_at  2026-10-20 04:31:44.548145
finished_at 2026-10-20 04:40:47.653495
duration    543.1 秒（9 分 03 秒）
status      succeeded
attempts    1 / max_attempts 2
```

该课程材料与分块：

| 文档 | chunk 数 | 字符数 | 按当前批规则拆出的批次数 |
|---|---:|---:|---:|
| `f1-sample.pdf` | 2 | 291 | 1 |
| `ch1_引言_v2.0(4).pdf` | 118 | 29,159 | 10 |
| `ch3_数据链路层_v2.0(3).pdf` | 120 | 28,854 | 10 |
| `ch4_MAC子层_v2.0(5).pdf` | 184 | 35,635 | 16 |
| **合计** | **424** | **93,939** | **37** |

平均每次 LLM 调用约 `543 / 37 ≈ 14.7 秒`。这不是“某一次请求特别慢”，而是 **37 次串行调用叠加**。

> 精度说明：库里没有逐次 `llm_call` 记录，14.7 秒是“总耗时 / 批次数”的推算，不是每次调用的实测分布；单个 batch 可能因输出长度、内部重试而显著高于或低于该值。见 5.3 的可观测性建议。

### 1.3 审查时的代码状态

工作区（未提交）已经有另一轮后端修改：

- `app/services/knowledge_service.py`：`_merge_batch_candidates` 从“完全平铺”改为按 `document_id` 分桶，生成“文档文件名 → 知识点”两层。
- `tests/unit/test_knowledge_merge.py`：测试期望 `root → document → topic`，并明确只验证到文档层。
- `app/llm/schemas.py`、`app/llm/openai_compatible.py`、`app/services/quiz_service.py`：还有出题/批改 schema 的修复，与本报告三个问题部分交叉，但不是本报告重点。

**因此本报告同时标注两类结论：**

- `HEAD ecf0417`：完全平铺；
- 当前工作区：文档层 + 平铺知识点；
- 活跃数据库：补丁前生成，仍然是完全平铺。

后面说“当前代码”时，指工作区；需要区分的地方会写明“HEAD”。

---

## 2. 问题一：生成知识框架后无法删除课程资料

### 2.1 用户路径与现象

1. 上传 PDF/PPTX，解析成功。
2. 生成知识框架，框架的叶子节点写入了 `knowledge_sources`，每条来源指向 `document_id` 和 `chunk_id`。
3. 回到资料页点击删除，确认对话框提示“若知识框架正引用它，后端会拒绝并提示”。
4. `DELETE /api/materials/{id}` 返回 `409 MATERIAL_IN_USE`，前端显示“材料正被知识框架引用，不能删除”。

这不是前端按钮问题；前端已经如实展示了后端拒绝。问题是：**拒绝之后没有出路。**

### 2.2 代码路径

#### 2.2.1 路由

`app/api/routes/materials.py:64-67`：

```python
@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(material_id: str) -> None:
    with session_scope() as session:
        MaterialService().delete_material(session, material_id)
```

#### 2.2.2 服务层的硬拦截

`app/services/material_service.py:152-171`：

```python
if self.knowledge_repository.is_document_referenced_by_knowledge(session, document.id):
    raise AppError(
        code="MATERIAL_IN_USE",
        message="Material cannot be deleted because it is referenced by a knowledge framework.",
        status_code=409,
        details={"material_id": document_id},
    )
self.storage.delete(document.storage_key)
self.job_repository.cancel_document_jobs(session, document_id=document.id)
self.material_repository.delete_document(session, document)
session.commit()
```

注意顺序：**先检查引用，再删文件、取消任务、删数据库行**。只要引用存在，后面都不会执行。

#### 2.2.3 “被引用”的判定范围

`app/repositories/knowledge_repository.py:241-249`：

```python
def is_document_referenced_by_knowledge(self, session: Session, document_id: str) -> bool:
    return (
        session.scalar(
            select(KnowledgeSource.id)
            .where(KnowledgeSource.document_id == document_id)
            .limit(1)
        )
        is not None
    )
```

这个查询**不区分框架版本状态**：active、inactive、failed、甚至历史测验引用的旧版本，只要有一条 `knowledge_sources` 记录，就永久阻止删除。

#### 2.2.4 数据库层还有第二道锁

`app/db/models/knowledge.py:136-141`：

```python
document_id: Mapped[str] = mapped_column(
    String(36),
    ForeignKey("documents.id", ondelete="RESTRICT"),
    nullable=False,
    index=True,
)
chunk_id: Mapped[str | None] = mapped_column(
    String(36),
    ForeignKey("document_chunks.id", ondelete="RESTRICT"),
    nullable=True,
    index=True,
)
```

迁移 `alembic/versions/20261016_0004_stage4_knowledge.py:100-118` 也是 `ondelete="RESTRICT"`：

```python
sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="RESTRICT")
sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT")
```

即使删掉服务层的前置检查，`MaterialRepository.delete_document()`（`app/repositories/material_repository.py:66-67`）也只是 `session.delete(document)`；SQLite 已开启 `PRAGMA foreign_keys=ON`（`app/db/session.py:32-36`），删除会被外键再次拒绝。

#### 2.2.5 资料删除只取消了“排队中”的解析任务

`app/repositories/job_repository.py:119-135` 的 `cancel_document_jobs` 只处理：

```python
.where(Job.type == "document.parse")
.where(Job.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RETRY_WAIT]))
```

正在运行的 `document.parse` 不会被取消。即使资料删除成功，解析 worker 仍可能继续写 page/chunk，或者因为 document 已不存在而失败。

### 2.3 设计思维：为什么当初会这样写

从代码和规范看，后端的设计意图是合理的：

- **可追溯**：知识点必须能回到具体文件、页码、chunk；`backend-spec.md:260` 要求“文档、页面、片段、知识点来源之间应可追溯到具体文件和页码”。
- **版本不可变**：旧框架、旧测验、旧掌握度不能被新框架覆盖；`backend-spec.md:300` 要求保留旧版本及历史测验、作答、掌握度引用的版本。
- **来源不能悬空**：`backend-spec.md:270` 明确要求“删除材料时要定义来源引用策略：至少不能留下指向不存在文件且未标记失效的来源；必要时使用软删除”。

但实现只完成了“不能悬空”这一半：用 `RESTRICT` 保证来源永远能找到 document。它没有完成规范要求的“定义策略”和“必要时软删除”。结果就是：

- 完整性正确；
- 产品不可用；
- 历史版本没有失效标记；
- 用户没有“删除并重建”的路径。

这不是一个普通的边界条件，而是 **生命周期设计缺失**：

```text
资料上传 → 解析 → 生成框架 → 资料被来源引用
                                      ↓
                              用户想删除资料
                                      ↓
                          RESTRICT / 409（永久）
                                      ↓
                         没有 archive、没有 detach、没有 rebuild
```

### 2.4 为什么是死锁，而不是“提示一下就完了”

假设用户接受“不能删”，想通过“重新构建”绕开：

1. 重新构建仍然会读取**所有** `completed/completed_with_warnings` 的文档；
2. `KnowledgeRepository.get_documents_for_framework_build()`（`knowledge_repository.py:205-213`）没有“排除某文档”的参数；
3. `KnowledgeBuildRequest`（`app/schemas/knowledge.py:6-9`）只有 `reference_outline`，没有 `exclude_document_ids`；
4. 所以新框架仍然引用这份资料；
5. 资料仍然不能删。

用户唯一的“解决办法”是删课程或手工改数据库，这显然不是产品设计。

### 2.5 现有设计的五个具体缺陷

| 缺陷 | 代码/数据表现 | 后果 |
|---|---|---|
| 引用检查不分版本状态 | `is_document_referenced_by_knowledge` 只查 `KnowledgeSource` | 任何历史版本都能永久锁死资料 |
| 没有软删除字段 | `Document` 只有 `status` / `error_code`，没有 `deleted_at` | 无法“保留来源行、隐藏资料” |
| 没有失效状态 | `KnowledgeFrameworkVersion.status` 只有 building/active/inactive/failed 等 | 无法表达“框架还在，但来源已失效” |
| 没有重建编排 | 删除接口不生成 rebuild job，也不改 `active_framework_version_id` | 删除与框架状态不一致 |
| 运行中的解析任务不取消 | `cancel_document_jobs` 只取消 queued/retry_wait | 删除与解析并发时产生脏数据/失败任务 |

另外，`KnowledgeSource.chunk_id` 也是 `RESTRICT`。软删除时如果保留 chunk 行没问题；如果做硬删除，必须同时处理 `knowledge_sources.chunk_id`，否则会从“document RESTRICT”变成“chunk RESTRICT”。

### 2.6 建议的目标策略：归档 + 框架失效 + 可重建

#### 2.6.1 推荐方案：软删除（archive），不直接物理删除

新增：

```text
documents.deleted_at         DATETIME NULL
documents.deleted_reason     VARCHAR(255) NULL   -- 可选
```

语义：

- `DELETE /api/materials/{id}` 默认执行 archive：
  - 设置 `deleted_at`；
  - 从资料列表、搜索、框架构建的输入中排除；
  - **保留** `documents` 行和 `knowledge_sources` 行，保证旧框架/旧测验的来源仍可解析到“已归档”状态；
  - 物理文件可以：
    - 继续保留（简单、可恢复）；或
    - 移到 tombstone 目录，来源仍可显示“文件已归档”；不要立即不可逆删除。
- 课程级状态：
  - `course.framework_state = stale`（或 `active_framework_version.status = stale`）；
  - `GET /courses/{id}/knowledge` 继续返回上一版，但带 `stale: true` / `stale_reason: "material_archived"`；
  - 新建测验默认拒绝 stale 框架，或只允许不依赖被删来源的叶子（二选一，需产品拍板；建议先拒绝并提示重建）。
  - 前端 `frameworkStatus()`（`frontend/src/api/status.ts`）需要新增 `stale` 文案；否则状态会落到未知/默认显示。
- 重建：
  - `DELETE` 返回 `202` + `rebuild_job_id`，或返回 `204` 并让前端显式调用 `POST /knowledge/build`；
  - 新构建自动排除 `deleted_at IS NOT NULL` 的资料；
  - 构建成功后新版本 active，旧版本保留。
- 如果删掉最后一份资料：
  - `active_framework_version_id = NULL`；
  - `GET /knowledge` 回到 404 空状态；
  - 已存在的测验快照、历史掌握度保留，但新测验返回 `MATERIALS_NOT_READY`。

#### 2.6.2 为什么不推荐“硬删除 + 级联删来源”

硬删除会同时破坏：

- 旧框架的来源；
- 历史 quiz 的 `source_metadata` 追溯；
- 掌握度/错题本对旧 node version 的引用；
- 规范要求的版本不可变。

如果确实需要“彻底清除”，应作为第二个动作：

```text
DELETE /materials/{id}                 → archive（默认）
DELETE /materials/{id}?purge=true      → 仅在没有 active/历史引用，或用户明确接受历史来源失效时
```

V1 不需要做 purge；先把 archive 做对。

#### 2.6.3 需要补的 API/数据契约

```json
// GET /api/courses/{course_id}/knowledge 的建议新增字段
{
  "framework_version_id": "...",
  "status": "active",
  "stale": true,
  "stale_reason": "material_archived",
  "tree": [...]
}
```

```json
// GET /api/materials/{id} 或 sources 中的来源
{
  "document_id": "...",
  "filename": "ch3_数据链路层.pdf",
  "archived": true,
  "page_number": 12,
  "chunk_id": "..."
}
```

如果不想改 `KnowledgeSourceResponse`，至少要让 `KnowledgeSource` 能 join 到 `Document.deleted_at`，前端显示“来源已归档”。

#### 2.6.4 并发与竞态

- 构建开始时记录 `documents_revision`（课程级递增版本，或 `max(document.updated_at)` + 资料数量）；
- 构建结束激活前再次检查 revision；若资料集合变化，当前版本标 `stale` 或 `failed`，不要激活；
- archive 时取消该文档所有 `queued/retry_wait/running` 的 parse job；running job 在写 page/chunk 前检查 `deleted_at`；
- 同一课程只允许一个 active build（见 3.5.4）。

### 2.7 验收标准（问题一）

- [ ] 被框架引用的资料执行 `DELETE` 返回 204/202，不再返回 409 `MATERIAL_IN_USE`。
- [ ] 删除后资料列表不再显示；搜索不再命中；新构建不再读取。
- [ ] 旧框架仍可读取，返回 `stale: true`；来源显示 `archived: true`，不出现悬空 500。
- [ ] 删除最后一份资料后，`GET /knowledge` 回到 404 空状态；已有 quiz 仍可查看历史结果。
- [ ] 删除时 running 的 parse job 被取消或安全终止，不产生新的 page/chunk。
- [ ] 删除与构建并发时，构建不会把已归档资料重新写进新 active 版本。
- [ ] 历史版本、历史 quiz、mastery 记录不被物理删除。
- [ ] 有测试覆盖：有引用删除、无引用删除、最后一份删除、删除后重建、并发删除/构建。

---

## 3. 问题二：生成知识框架非常慢

### 3.1 实测结论

- 4 份材料、424 个 chunk，按当前规则拆成 **37 个 batch**；
- 作业串行调用 LLM **37 次**；
- 总耗时 **543 秒**；
- 平均每次 **14.7 秒**；
- 作业直到最后才把 `progress` 从 0 改成 100；
- 前端 `useJob` 默认 **5 分钟** 后停止轮询并提示“仍在处理”，而实际作业跑了 9 分钟。

所以用户感受到的是：

```text
点击“构建” → 长时间无进度 → 5 分钟后 UI 说“仍在处理” → 9 分钟后才成功
```

这比“单纯慢”更糟：**等待不可解释，且 UI 在作业完成前就放弃了轮询。**

### 3.2 代码路径

#### 3.2.1 启动：创建一个 building 版本 + 一个 job

`app/services/knowledge_service.py:81-128`：

```python
version = self.repository.create_framework_version(... status="building")
job = self.job_repository.create_job(
    session,
    job_type="knowledge_framework.build",
    payload_json=...,
    max_attempts=2,
)
session.commit()
return KnowledgeBuildResponse(job_id=job.id, ...)
```

路由 `app/api/routes/knowledge.py:24-36` 返回 202，然后 `_trigger_jobs_once()` 起一个 daemon 线程；同时 `app/main.py:20` 还有一个常驻 `run_worker_loop`。两条触发路径最终都进入 `JobRunner.process_available_jobs`。

#### 3.2.2 作业执行：一次只处理一个 job，job 内部串行

`app/jobs/runner.py:49-57`：

```python
for _ in range(limit):
    job_id = self._claim_next_job_id()
    if job_id is None:
        break
    self._execute_job(job_id)
```

`_generate_framework_candidate`（`knowledge_service.py:455-498`）：

```python
for batch in batches:
    payload = self._build_llm_payload(...)
    llm_result = adapter.generate_structured_output(...)
    candidate = llm_result.data
    batch_candidates.append(self._sanitize_batch_candidate(candidate, batch))
```

没有 `asyncio.gather`、没有线程池、没有并行。37 个 batch 就是 37 次串行 HTTP 请求。

#### 3.2.3 分批规则：12 个 chunk 是实际约束

`knowledge_service.py:39-40`：

```python
FRAMEWORK_BATCH_CHUNK_LIMIT = 12
FRAMEWORK_BATCH_CHAR_LIMIT = 14000
```

`_build_framework_batches`（`knowledge_service.py:500-548`）在“当前 batch 已有内容”时，只要满足任一条件就切批：

```python
exceeds_chars = current_units and current_chars + unit_chars > 14000
exceeds_units = len(current_units) >= 12
```

这份材料是 PDF 按页切 chunk，单页 chunk 平均只有几百字符：

- 实际 batch 字符数约 **1,500–4,200**，远低于 14,000；
- 12 个 chunk 的限制先触发；
- 37 个 batch 中，大部分只包含 12 页。

这不是“上下文窗口不够”，而是 **用 chunk 数量代替 token/语义边界**。

#### 3.2.4 每次调用新建 HTTP client

`app/llm/openai_compatible.py:112-118`：

```python
with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
    response = client.post(
        f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
        json=request_body,
        headers=headers,
    )
```

`httpx.Client` 在每次 `generate_structured_output` 内部创建、关闭。37 次调用就是 37 次连接池/TLS 握手生命周期，无法复用 keep-alive。单次几十到几百毫秒，叠加起来是可见开销，但不是 9 分钟的主因；它是“结构性慢”的一部分。

#### 3.2.5 内部重试与 job 重试都会放大耗时

`openai_compatible.py:90-99`：

```python
for attempt in range(self.settings.llm_max_retries + 1):
    ...
```

默认 `llm_max_retries=2`，即每个 batch 最多 3 次请求。若模型输出 schema 不稳定：

- 单个 batch 从 1 次变 3 次；
- 37 个 batch 中的一部分会被放大；
- 如果 job 层再失败重试（`max_attempts=2`），整个 37 次从头再来。

当前 `knowledge_framework.build` 的 `max_attempts=2` 是整 job 级重试，不是 batch 级重试。`JobRunner` 的 retry 分支（`jobs/runner.py:75-91`）会把整个 job 重新排队；`build_framework_job` 没有“已完成 batch 缓存”，因此下一次还是从第一个 batch 开始。

#### 3.2.6 进度只有 0 和 100

`JobRepository.mark_succeeded`（`job_repository.py:68-74`）只在这里设置：

```python
job.progress = 100
```

`_generate_framework_candidate` 没有更新 job；`Job` 也没有 `phase` / `completed_units` / `total_units` 字段。前端只能显示“构建中”。

#### 3.2.7 前端 5 分钟放弃轮询

`frontend/src/hooks/useJob.ts:33`：

```ts
{ timeoutMs = 5 * 60_000, ... }
```

`refetchInterval` 在 `elapsed > timeoutMs` 时返回 `false`（`useJob.ts:54-61`）。所以 9 分钟的作业在第 5 分钟就被前端标记为 `timeout`。这不是后端变快，但会显著放大“非常慢/卡住”的感受。

### 3.3 根因排序

| 排名 | 根因 | 影响 | 证据 |
|---:|---|---|---|
| 1 | 37 次串行 LLM 调用 | 主要耗时；每次 14.7s 直接相加 | `_generate_framework_candidate` 的 `for` + `adapter` 同步调用 |
| 2 | 12 chunk 上限过小 | 424 chunk → 37 batch；字符上限几乎未触发 | 实际 batch 1.5–4.2k 字符 vs 14k 上限 |
| 3 | 无连接复用 | 37 次 TLS/连接生命周期 | `httpx.Client` 在每次调用内创建 |
| 4 | 输出过长 | 每个叶子要求完整讲解，309 个叶子 → 大量输出 token | prompt 要求 `content` 完整解释；无长度上限 |
| 5 | 无缓存/增量 | 重建全部材料；相同内容重复调用 | `start_build` 每次新版本、全量 `documents` |
| 6 | 无断点/进度 | 失败重试从头来；UI 5 分钟放弃 | job 只有 0/100；`max_attempts=2` 整 job 重试 |
| 7 | 无并发/每课程互斥 | 多个构建可能排队；单 worker 串行 | `process_available_jobs(limit=10)` 串行；`start_build` 不检查已有 building |

### 3.4 设计思维：为什么当初会这样写

代码体现出几个合理的初始假设：

- **“LLM 上下文有限，所以按 chunk 分批”**：这是对的，但实现把“12 个 chunk”当成安全上限，没有按 token/字符和章节语义调整。
- **“一个 job 负责整条构建流程”**：实现简单，状态少；但代价是不可恢复、不可观测、不可并行。
- **“先保证正确，再优化性能”**：在 3 页样本（1 个 batch）上 18 秒完成，掩盖了 400 页时的线性放大。真实数据一上来就暴露了。
- **“progress 只有 0/100 也能显示”**：前端用不定进度条兜底，但 9 分钟超过 5 分钟轮询窗口，兜底失效。

问题不在于“用了 LLM”，而在于 **把 LLM 调用次数和知识结构绑定在一起**：每 12 页调用一次，导致调用次数随页数线性增长，且每次调用独立、看不到全局章节。

### 3.5 建议的目标设计

#### 3.5.1 两阶段/三阶段流水线，而不是一个 for 循环

```text
Stage A: 结构抽取（outline）
  - PDF: bookmarks / TOC / 字号 / 编号标题 / 页眉页脚规则
  - PPTX: slide title placeholder / 章节页
  - 无结构时：一次轻量 LLM 调用，只输出章节目录 + 页码范围
  - 产物：chapter/section 列表（不调用或只调用 1 次）

Stage B: 按章节/小节抽取叶子
  - 每个 section 一次调用，携带 section_path + page_range + 目标叶子数
  - 并行度 3–4（可配置），单次 token 预算 14k–24k
  - 输出版式固定：只返回该 section 下的叶子，不允许创建容器
  - 产物：per-section candidate + 来源

Stage C: 合并、校验、持久化、激活
  - 按 section_path 合并；去重；补来源；验证
  - 单事务写新版本，成功后切换 active
```

这样调用次数从“页数/12”变成“章节/小节数”。以当前 4 份材料约 10–15 个章节计算，约 10–15 次调用；并发 4 时墙钟时间可降到 1–3 分钟量级（取决于模型，不承诺固定值）。

#### 3.5.2 批大小按 token/字符，不按 chunk 数

- 保留 `FRAMEWORK_BATCH_CHAR_LIMIT`，把它作为主约束（例如 24k–32k 字符，按模型上下文留出输出余量）；
- 删除或大幅提高 `FRAMEWORK_BATCH_CHUNK_LIMIT`（例如 40–60，仅作为防御性上限）；
- 以 section 为优先切分：不要把一个 section 从中间切开；section 太大时再按页/段切；
- 每个 batch 限制输出叶子数（例如 8–12），避免一次生成几十个长解释导致超时。

#### 3.5.3 连接复用、并发与超时预算

- 每个 job 复用一个 `httpx.Client`（或 adapter 持有 client），开启连接池；不要每次调用新建。
- 用 `ThreadPoolExecutor` / `asyncio` 并行 3–4 个 section；SQLite 写入仍集中在主线程/单事务，避免并发写库。
- 每次调用超时 60s 可以保留，但要有 **job 总预算**（例如 5 分钟）和“已耗时/剩余”判断；不要把 37 × 60s 的最坏情况留给用户。
- 仅对 `LLM_TIMEOUT` / `LLM_NETWORK_ERROR` / 429/5xx 做重试；schema 错误应走一次修复提示或直接失败，不要 3 次都发同一提示。

#### 3.5.4 断点、缓存、增量

- 以 `document.content_hash + prompt_version + model` 为 key 缓存 section candidate；
- 构建 job 记录 `completed_sections` / `completed_batches`，重试时跳过已完成部分；
- 重建时只处理新增/修改的文档；未变文档复用上次候选；
- 同一课程只允许一个 building 版本：DB 唯一约束/事务检查；重复 POST 返回已有 `job_id`，不要排两个 9 分钟作业。

#### 3.5.5 进度契约

`JobResponse` 增加：

```json
{
  "progress": 42,
  "phase": "extract_sections",
  "completed_units": 5,
  "total_units": 12,
  "message": "正在抽取第 3 章"
}
```

前端 `useJob` 的 5 分钟硬超时可以改成“有进度就继续、无进度才提示”，或把默认超时提高到与后端预算一致。

#### 3.5.6 目标指标（建议写进验收）

- 4 份材料 / 400–500 chunk：p50 ≤ 120s，p95 ≤ 180s（真实模型，不含排队）。
- 首次进度更新 ≤ 5s；进度单调递增。
- 单次 LLM 调用不超过 60s；单 job 总预算不超过 5 分钟。
- 同一课程并发构建 = 1；重复请求返回同一 job。
- 失败重试从最近完成的 section 继续，不重跑全部。
- 以 mock adapter 测：424 chunk 时调用次数 ≤ 15；并发度可配置；注入 section 失败后能恢复。

> 注意：这些是设计目标，不是当前实测值；需要用真实模型和 mock 各测一轮后写回报告。

### 3.6 不建议的做法

- **只把 `LLM_TIMEOUT_SECONDS` 从 60 调到 300**：不会减少 37 次调用，只会让失败更晚、用户等更久。
- **只把 12 改成 50**：能减少调用次数，但可能让单次输出过长、schema 更不稳定；必须同时限制输出叶子数和 content 长度。
- **只加一个前端“预计还需 5 分钟”**：不解决结构问题，只是把不可解释的等待包装得更好。

---

## 4. 问题三：知识点平铺、章节关系不清、掌握度无法聚焦

### 4.1 数据证据

见 1.1。两个活跃框架都是：

```text
level 0: 1 个根（课程名）
level 1: 98 / 309 个叶子
level 2+: 0
```

第二套有 288 个 `section_label`，但全部挂在 level 1 叶子上，没有 section 容器。也就是说：

```text
课程
├── 第3章 运输层  TCP 慢启动...     ← 其实是一个叶子，label 只是前缀
├── 第3章 运输层  拥塞避免...
├── 第3章 运输层  GBN...
├── 1.1  网络的基本功能...
└── ... 309 行
```

用户看到的不是“课程大纲”，而是“309 条带编号前缀的平铺笔记”。

### 4.2 数据模型和 API 其实是支持层级的

`app/db/models/knowledge.py:75-110`：

```python
parent_id: Mapped[str | None] = mapped_column(
    String(36),
    ForeignKey("knowledge_node_versions.id", ondelete="CASCADE"),
    nullable=True,
)
level: Mapped[int]
is_leaf: Mapped[bool]
sort_order: Mapped[int]
```

`app/schemas/knowledge.py:42-51`：

```python
class KnowledgeTreeNodeResponse(BaseModel):
    ...
    level: int
    is_leaf: bool
    sources: list[KnowledgeSourceResponse]
    children: list["KnowledgeTreeNodeResponse"] = Field(default_factory=list)
```

`app/services/knowledge_service.py:332-426` 的 `_persist_candidate_node` 是递归的，会按 `node.children` 写入任意深度；`level` 逐层 +1，`is_leaf=not node.children`。

`frontend/src/pages/Knowledge.tsx:79-166` 的 `TreeRow` 也是递归的，支持任意深度、展开/折叠、缩进。

**所以问题不在“数据库不支持树”，也不在“前端不会渲染树”。问题在生成阶段没有树。**

### 4.3 代码逻辑：层级是在哪里丢的

#### 4.3.1 提示词明确要求“平铺”，禁止章节容器

`app/llm/prompts/knowledge_framework.py:25-31`：

```text
Return knowledge points as flat leaf concepts. Do not create document nodes, section nodes, or
chapter nodes as knowledge points. Put chapter or section markers such as "3.1" or "Chapter 3"
in section_label when available; ...
```

`knowledge_service.py:838-862` 的 `selection_rules` 同样写着：

```python
"Do not create document, chapter, or section container nodes.",
"Each leaf node must include at least one source from batch_sources.",
```

`output_shape`：

```python
"nodes": (
    "A flat list of high-signal knowledge point nodes. children should usually "
    "be empty. Do not include document or section containers."
),
```

这不是模型“不会分层”，而是**代码明确禁止模型分层**。模型被要求把章节信息塞进 `section_label`，不要建父节点。

#### 4.3.2 清洗阶段会保留子树，但合并阶段只要“有来源的节点”

`_sanitize_batch_candidate`（`knowledge_service.py:550-602`）会递归保留 `node.children`，看起来支持层级；但：

`_collect_source_backed_topics`（`knowledge_service.py:703-720`）：

```python
topics = []
if node.sources:
    topics.append(KnowledgeNodeCandidate(... children=[]))
for child in node.children:
    topics.extend(self._collect_source_backed_topics(child))
return topics
```

它只收集 **自身有 `sources` 的节点**，并且把每个节点的 `children` 置空。容器节点（chapter/section）通常没有 sources，于是：

- 父节点被丢弃；
- 子节点被提升；
- 无论 LLM 是否返回了层级，合并阶段都会把树拍平。

#### 4.3.3 HEAD 的合并：完全平铺

`HEAD ecf0417` 的 `_merge_batch_candidates`（`knowledge_service.py:604-664`）：

```python
merged_topics.append(
    KnowledgeNodeCandidate(
        ref=f"topic_{topic_index}",
        section_label=self._clean_section_label(topic.section_label),
        title=topic.title,
        content=topic.content,
        sources=topic.sources[:3],
        children=[],
    )
)
```

每个 topic 都是 `children=[]`；所有 batch 的 topic 进入一个全局列表；最终 root 下就是全部 topic。这就是 98/309 个 level-1 叶子的直接来源。

#### 4.3.4 工作区补丁：只加了“文档层”，不是“章节层”

未提交的 `_merge_batch_candidates` 改成：

```python
merged_by_doc[document_id].append(topic)
...
doc_nodes.append(
    KnowledgeNodeCandidate(
        title=document.filename,       # 文档文件名
        children=topics,               # 仍然全部是叶子
    )
)
```

结果：

```text
根（课程名）
├── ch1_引言_v2.0(4).pdf
│   ├── 网络的基本功能
│   ├── 网络应用的多样性
│   └── ... 约 100 条
├── ch3_数据链路层_v2.0(3).pdf
│   └── ... 约 100 条
└── ch4_MAC子层_v2.0(5).pdf
    └── ... 约 100 条
```

它解决了“所有叶子直接挂根”的一半问题，但仍然：

- **没有 chapter/section 结构**；
- 文件名不是章节名（一个 PDF 可以包含多章；一章也可以拆成多个文件）；
- `section_label` 仍然是行内前缀，不是父节点；
- 掌握度仍然按 309 个叶子平铺返回；
- 如果两份文档都讲“第 3 章”，会被拆到两个文件组，无法合并为同一章。

这就是为什么用户仍然觉得“每个知识点单独列出，看不出属于哪一章”。

#### 4.3.5 `section_label` 不是稳定的层级标识

当前 `section_label` 来源混杂：

- 模型自由生成：`第3章 运输层`、`1.1`、`课程导论`、`实验安排`；
- `_infer_section_label` 只用正则匹配数字/`Chapter`（`knowledge_service.py:733-746`）；
- 没有规范化：`第3章`、`Chapter 3`、`3`、`3.0` 不会被视为同一节；
- 同一个 label 下可能有几十个叶子，但 label 没有 ID、没有 parent、没有排序。

因此不能靠 `section_label` 做 group by；即使前端按 label 分组，也会得到不稳定的字符串桶。

#### 4.3.6 `_build_tree` 隐藏根节点

`knowledge_service.py:933-963`：

```python
root = roots[0]
return [convert(child) for child in sorted(children_map.get(root.id, []), ...)]
```

API 只返回根的直接子节点。对于 root → chapter → section → leaf 的结构，前端会看到 chapter 层；对于当前平铺结构，前端看到 309 个叶子。这个设计本身没问题，但它让“根下有几个孩子”直接决定页面观感。

### 4.4 设计思维：为什么会出现“平铺”

这是本报告最需要后端 agent 重新思考的部分。

#### 4.4.1 把“来源边界”当成了“知识边界”

工作区补丁用 `sources[0].document_id` 分桶，本质上是：

```text
一条来源属于哪个文件 → 这个知识点就属于哪个文件组
```

但知识结构不等于文件结构：

- 一份 PDF 可能包含第 1–4 章；
- 一章可能由 `ch3_part1.pdf`、`ch3_part2.pdf` 两份材料组成；
- 同一概念可能在多份材料中重复出现；
- 文件名是教师上传时的命名，不是课程大纲。

#### 4.4.2 没有“大纲”这个中间产物

理想流程应先回答：

```text
这门课有哪几章？每章有哪几节？每节覆盖哪些页？
```

再回答：

```text
这一节里有哪些知识点？
```

当前流程直接让模型从 12 页 chunk 里“提取知识点”，模型看不到全书目录，也不允许创建章节节点。批次之间互相独立，所以即使模型想分层，也无法保证跨批次一致。

#### 4.4.3 用 `children` 表达层级，却又在提示词里禁止 `children`

Schema 有 `children`，持久化支持递归，前端支持递归；但提示词说“children should usually be empty”“Do not create containers”。这是**契约自相矛盾**：

- 数据结构：树；
- 生成指令：平铺；
- 合并逻辑：先拍平，再按文件补两层；
- 展示：树。

四层各自合理，组合起来就是“看起来有树，实际没有课程结构”。

#### 4.4.4 校验只校验来源，不校验结构

`_persist_candidate_node` 会检查：

- 叶子必须有 source；
- source 的 page/chunk 存在；
- 标题非空。

但不会检查：

- 根是否唯一；
- 容器是否至少有一个子节点；
- 叶子深度是否 ≥ 2；
- 同一 section 的叶子是否在同一父节点；
- 是否有重复路径；
- 顶层节点数量是否爆炸（例如 > 50）；
- 文档文件名是否被误当成章节。

所以 309 个 level-1 叶子可以顺利通过校验并激活。

### 4.5 对掌握度和复习的直接影响

#### 4.5.1 `/mastery` 只返回叶子，且没有父级信息

`app/services/mastery_service.py:48-67`：

```python
active_nodes = {
    node.knowledge_node_id: node
    for node in self.repository.list_active_leaf_nodes(session, course_id)
}
for state in self.repository.list_states(session, course_id):
    node = active_nodes.get(state.knowledge_node_id)
    responses.append(MasteryStateResponse(
        knowledge_node_id=...,
        title=node.title if node else None,
        ...
    ))
```

`app/repositories/mastery_repository.py:185-202` 只查 `is_leaf.is_(True)`，按 `level, sort_order` 排序。响应里没有：

- `parent_id`
- `section_path`
- `chapter_title`
- `leaf_count`
- `tested_count`
- `average_mastery`

前端 `ReviewPage` 只能把 `mastery.data` 平铺排序，再对 `collectLeaves(tree)` 做差集找未测验。它没有章节上下文，所以只能显示“已测验 20 条 + 未测验 N 个”的长列表。

#### 4.5.2 复习目标选择也是叶子级

`mastery_service.py:73-137`：

```python
leaf_nodes = self.repository.list_active_leaf_nodes(...)
for node in leaf_nodes:
    state = states_by_node.get(node.knowledge_node_id)
    target = self._score_target(node, state)
    ...
weakness_targets.sort(key=lambda target: target.priority, reverse=True)
```

优先级只看单个叶子的 `mastery_estimate` 和 `evidence_count`，没有：

- 章节覆盖率；
- 章节平均掌握度；
- 同一章节内多个薄弱点的聚集；
- “这一章整体没测过”的探索价值。

结果：309 个叶子中选 10 个，可能全来自不同章节，用户无法形成“这一章要重点复习”的认知。

#### 4.5.3 错题本/计划同样缺少章节上下文

- `KnowledgeGapResponse` 只有 `title`，没有 `section_path`；
- `study_tasks` 的目标知识点是扁平 ID；
- Dashboard/Review 只能显示单点，无法按章聚合。

### 4.6 建议的目标层级契约

#### 4.6.1 目标树形

推荐 3–4 层，按材料实际结构自适应：

```text
课程（root, level 0）
└── 第 3 章 运输层（chapter, level 1, container）
    ├── 3.1 运输层服务（section, level 2, container）
    │   ├── 可靠传输（leaf, level 3）
    │   └── 滑动窗口（leaf, level 3）
    └── 3.2 TCP 拥塞控制（section, level 2, container）
        ├── 慢启动（leaf, level 3）
        └── 拥塞避免（leaf, level 3）
```

约束：

- 根唯一；
- 容器必须有 ≥1 个子节点；
- 叶子必须在 level ≥ 2（单章课程也至少有 chapter + leaf）；
- 叶子必须 ≥1 条来源；
- 最大深度 4；
- 同一 section 的叶子共享同一 `section_path`；
- 文档文件名**不作为**容器标题；文档只作为来源元数据。

#### 4.6.2 先抽大纲，再抽叶子

**Stage A：大纲**

- PDF：优先 `page.get_toc()` / bookmarks；没有则用字号、加粗、编号标题、页眉页脚规则；
- PPTX：slide title placeholder、章节页、目录页；
- 都没有：一次 LLM 调用，输入目录页/前几页 + 标题候选，输出 chapter/section + 页码范围；
- 产物不要求每个容器都有 source；容器是结构，不是知识点。

**Stage B：按 section 抽叶子**

Prompt 输入：

```json
{
  "course_name": "计算机网络",
  "section_path": ["第 3 章 运输层", "3.2 TCP 拥塞控制"],
  "page_range": [42, 58],
  "source_segments": [...],
  "max_leaves": 8
}
```

Prompt 约束：

- 只能返回该 section 下的叶子；
- 不要返回 chapter/section 容器；
- 每个叶子必须引用当前 section 的 source；
- `content` 限长（例如 120–240 字）；
- 标题是短名词短语；
- 不要跨 section 合并。

**Stage C：合并**

- 按 `section_path` 合并，而不是按 `document_id`；
- 同一路径下按标题去重；
- 同一叶子多个来源时合并 `sources`；
- 保留 section 的 `sort_order` 和页码范围；
- 对跨 section 的重复概念，生成 `related` 关系，而不是移动父节点。

#### 4.6.3 合并与稳定 ID

当前 `_persist_candidate_node` 的 `stable_key` 是：

```python
" > ".join([*path, section_label?, title]).lower()
```

加入 chapter/section 层后，leaf 的 `stable_key` 会变化，导致重建时 `knowledge_nodes` 新建，旧的 `student_gap_states` / `study_task_targets` / `knowledge_gaps` 变成孤儿。

建议：

- 叶子的稳定身份不要依赖完整树路径；使用 `course_id + 规范化标题 + 主来源 document_id + 首个 page_number`，或内容哈希 + 标题；
- 或者增加 `node_identity` / `node_aliases` 表，记录旧→新映射；
- 重建时迁移 mastery/gap/plan targets；
- 如果暂时不做迁移，至少要在 UI 明确提示“重建后掌握度会重置”，不要让用户以为数据丢了。

#### 4.6.4 API 返回结构

当前：

```json
{
  "tree": [...],
  "nodes": [...]   // 与 tree 相同，冗余
}
```

建议：

```json
{
  "framework_version_id": "...",
  "status": "active",
  "stale": false,
  "tree": [
    {
      "knowledge_node_id": "...",
      "title": "第 3 章 运输层",
      "level": 1,
      "is_leaf": false,
      "path": ["第 3 章 运输层"],
      "leaf_count": 42,
      "tested_count": 12,
      "mastery_summary": {
        "average_estimate": 0.58,
        "tested_leaves": 12,
        "total_leaves": 42,
        "low_mastery_leaves": 7
      },
      "children": [...]
    }
  ]
}
```

说明：

- `mastery_summary` 是**派生统计**，不是给容器伪造一个 Beta 状态；
- 只能对已测验叶子求平均，并标注 `tested_leaves/total_leaves`；
- 不要把它写成“章节掌握度已精确测量”。

`nodes` 字段可以保留兼容，但应标记 deprecated；前端目前只用 `tree`。

#### 4.6.5 掌握度与复习的树级设计

**后端**

- `GET /mastery` 增加 `section_path`、`parent_id`、`chapter_title`；
- 新增 `GET /courses/{id}/mastery/summary` 或让 `/mastery` 返回 `groups`：
  ```json
  {
    "groups": [
      {
        "section_path": ["第 3 章", "3.2"],
        "total_leaves": 12,
        "tested_leaves": 5,
        "average_estimate": 0.42,
        "low_mastery_leaves": 4
      }
    ],
    "leaves": [...]
  }
  ```
- `select_review_targets` 先按 section 聚合，再在 section 内选叶子：
  - 章节平均掌握度低；
  - 章节未测验比例高；
  - 章节内低分叶子多；
  - 保留探索配额；
  - 返回 `section_path`，让前端能显示“来自第 3 章”。
- `KnowledgeGapResponse` 增加 `section_path`；
- `study_task_targets` 可以继续指向叶子，但任务标题/描述应带章节路径。

**前端**

- 知识页默认只展开 chapter 层，section 折叠；
- 每组显示 `N 个知识点 · 已测 M`；
- 掌握度页按 chapter/section 分组，默认显示章节摘要，展开后看叶子；
- 复习目标显示章节路径，而不是孤立标题；
- 不要求前端自己计算章节平均（后端给 summary）。

### 4.7 验收标准（问题三）

- [ ] 合成 fixture：3 章 × 3 节 × 5 叶，API 返回深度 3–4；每个叶子有完整 `section_path`；无文件容器。
- [ ] 真实 4 份材料：顶层 chapter 数在合理范围（例如 ≤ 20），不是 309；每个叶子至少 level 2；无 level 1 叶子（单章课程可例外，需明确）。
- [ ] `section_label` 规范化；同一 section 的叶子共享同一 path；中文“第3章”、`Chapter 3`、`3` 能归一。
- [ ] 容器节点无 sources 也能持久化；叶子必须有 sources；空容器在激活前被拒绝。
- [ ] `GET /knowledge` 返回 `leaf_count` / `tested_count` / `mastery_summary`（或单独 summary API）。
- [ ] 掌握度页不再默认渲染 309 条平铺；章节摘要可见，展开后叶子可读。
- [ ] 复习目标至少包含 `section_path`；章节级覆盖率参与选择。
- [ ] 重建后旧 mastery 不静默丢失：要么迁移，要么明确提示重置。
- [ ] 测试覆盖：多层合并、跨文档同章节、同标题不同章节、空容器、超深树、非法父节点。

---

## 5. 跨问题的设计问题

这三个问题如果不一起改，会互相拖累。

### 5.1 框架版本与资料集合没有绑定

当前 `KnowledgeFrameworkVersion` 只记录 `course_id/version_number/status`，没有记录“这一版用了哪些 document、哪个 prompt/model、哪个 schema 版本”。

建议增加：

```text
framework_versions.source_document_ids_json
framework_versions.prompt_version
framework_versions.model_name
framework_versions.schema_version
framework_versions.build_revision
framework_versions.stale_reason
```

这样：

- 删除资料时能判断影响哪些版本；
- 重建时能只处理变化；
- 出题/掌握度能知道框架的来源基线；
- 排障时能复现。

### 5.2 构建没有“输入快照”和“失效检查”

`build_framework_job` 在开始时读取 documents，然后长时间调用 LLM；期间资料可能被删除/新增。当前没有 revision 检查，构建结束会直接激活。

建议：

- 课程级 `documents_revision`；
- job payload 记录 revision；
- 激活前比对；不一致则标记 `stale`，不要 active；
- 删除/新增资料时递增 revision；
- 同一课程只允许一个 building 版本。

### 5.3 LLM 调用没有持久化观测

当前 `LLMStructuredResult.summary` 只包含 model/prompt_version/provider，`knowledge_service` 没有保存；`jobs` 只有总耗时和错误码。无法回答：

- 37 次调用各花了多久？
- 哪一批触发了内部重试？
- 输入/输出 token 多少？
- 哪个 prompt 版本质量差？

建议新增 `llm_calls` 表（不存密钥、不存完整学生答案）：

```text
id, job_id, purpose, prompt_version, model_name, batch_index,
started_at, finished_at, latency_ms, input_chars, output_chars,
attempt, status, error_code
```

这是性能优化和回归的前提。

### 5.4 任务状态语义不够

- `progress` 只有 0/100；
- `attempts` 是 job 级，不是 batch 级；
- `retry_wait` 没有“当前阶段”；
- `failed` 没有“部分产物”。

建议：

- `progress` 0–100 单调；
- `phase`（outline/extract/merge/validate/activate）；
- `completed_units/total_units`；
- `resume_token` 或 `checkpoint_json`；
- 失败时保留已完成 section 的缓存，重试可续。

### 5.5 文档与章节的关系需要明确

建议明确写进设计：

> `documents` 是来源，不是知识树的层级。知识树层级来自课程大纲（chapter/section），来源通过 `knowledge_sources` 关联到叶子。

如果产品确实想按“资料”浏览，可以在 API 增加 `source_documents` 过滤/分组，但不要把它作为 `parent_id` 的唯一依据。

### 5.6 任务触发与领取不是原子操作

当前有两条触发路径：

- `app/main.py:20` 的常驻 `run_worker_loop`；
- `app/api/routes/knowledge.py:19-21`（以及 `materials.py`）在请求后另起一个 daemon 线程调用 `process_available_jobs`。

`JobRepository.claim_next_available_job`（`app/repositories/job_repository.py:44-66`）是“先 select queued/retry_wait，再改 running、commit”，没有 `FOR UPDATE`、没有原子 `UPDATE ... RETURNING`、没有 claim token。SQLite 下两个线程可能同时读到同一个 job，随后都执行。即使没有真的重复执行，双触发也会增加无谓的轮询和锁竞争。

建议：

- 路由只负责入队，不直接起 worker 线程；worker loop 是唯一消费者；
- claim 改为原子 SQL（`UPDATE ... WHERE status IN (...) AND run_after <= now RETURNING id`）或使用 `BEGIN IMMEDIATE`；
- 增加 `claimed_by` / `claim_token`，执行结束校验 token，防止旧 worker 覆盖新状态；
- 同一课程构建互斥，重复 POST 返回已有 `job_id`。

这会同时改善“慢”和“偶发重复构建/重复调用”的问题。

---

## 6. 建议的实施顺序

### Phase 0：先定契约（0.5–1 天）

- 确认“document 不是层级，chapter/section 才是”；
- 确认删除 = archive + stale + rebuild，还是 delete + purge；
- 确认最大深度、每 section 叶子上限、content 长度上限；
- 确认旧 mastery 是否迁移；
- 把这些写进 `backend-spec.md` / API schema，不要只在代码里约定。

### Phase 1：删除生命周期（0.5–1 天，P0）

- `documents.deleted_at` 迁移；
- `DELETE` 改为 archive；列表/搜索/构建过滤；
- `framework stale` 状态 + `GET /knowledge` 返回 stale；
- archive 后触发 rebuild（或返回 `rebuild_required`）；
- 取消 running parse job；
- 测试：有引用删除、最后一份删除、删除后重建、并发。

### Phase 2：分层生成（2–4 天，P0）

- 新增 outline 抽取器（PDF TOC/bookmarks/heading；PPTX title；LLM fallback）；
- `_build_llm_payload` 改为 section payload；删除“禁止容器”的指令；
- `_merge_batch_candidates` 按 `section_path` 合并，不再按 document 分桶；
- 校验：根唯一、容器有子、叶子有来源、深度 2–4、无文件容器；
- `GET /knowledge` 增加 `path` / `leaf_count` / `tested_count`；
- 旧平铺版本标记 stale，重建；不要原地改历史数据；
- 测试：多层 fixture、真实 4 材料重建、跨文档同章节。

### Phase 3：性能（1–2 天，P1）

- 批大小改为 token/字符 + section 优先；
- adapter 复用 HTTP client；
- section 级并发 3–4；
- job 进度/phase/checkpoint；
- 同一课程构建互斥；
- 前端超时与进度显示；
- 基准：mock + 真实模型各一轮，记录调用次数/耗时。

### Phase 4：掌握度聚合（1–2 天，P1）

- `/mastery` 增加 path/parent；
- 章节 summary；
- 复习目标按章节聚合；
- 前端按章分组、默认折叠；
- 测试：章节覆盖率、低掌握度聚合、未测验探索。

### Phase 5：可观测与增量（P2）

- `llm_calls` 表；
- section 缓存；
- 增量重建；
- 树的人工修订（如果产品需要）。

---

## 7. 需要后端 owner 明确拍板的问题

这些问题不拍板，agent 会继续在错误结构上打补丁：

1. **document 是知识树层级，还是仅来源？**
   - 建议：仅来源；chapter/section 来自大纲。
2. **删除资料是 archive 还是 purge？**
   - 建议：V1 只做 archive；purge 作为后续危险操作。
3. **删除后旧框架是否继续可读？**
   - 建议：可读但 `stale: true`；新建测验拒绝，直到重建。
4. **删除最后一份资料后，旧测验/掌握度是否保留？**
   - 建议：保留历史快照；`GET /knowledge` 404；新测验 400 `MATERIALS_NOT_READY`。
5. **章节层级以什么为准？**
   - PDF bookmarks/TOC > 字号/编号标题 > LLM fallback；PPTX slide title > 目录页 > LLM fallback。
6. **最大深度/每章叶子数/每 section 叶子数？**
   - 建议：最大 4 层；每 section 8–12 叶；每章不超过 50 叶（超出再分节）。
7. **掌握度章节聚合的定义？**
   - 建议：只对已测叶子求平均，返回 tested/total；不伪造容器 Beta 状态。
8. **是否迁移旧 mastery？**
   - 建议：至少做稳定 ID 映射；否则 UI 明示重置。
9. **模型/并发/预算？**
   - 建议：并发 3–4；单 job 5 分钟预算；单次 60s；失败只重试瞬时错误。
10. **旧平铺框架怎么处理？**
    - 建议：保留历史版本只读；新版本重建；不要原地改 `parent_id`。

---

## 8. 附录

### 8.1 关键代码索引

| 主题 | 位置 |
|---|---|
| 删除资料路由 | `app/api/routes/materials.py:64-67` |
| 删除资料服务/硬拦截 | `app/services/material_service.py:152-171` |
| 引用检查 | `app/repositories/knowledge_repository.py:241-249` |
| 来源外键 RESTRICT | `app/db/models/knowledge.py:136-153` |
| 迁移 RESTRICT | `alembic/versions/20261016_0004_stage4_knowledge.py:100-118` |
| 解析任务取消范围 | `app/repositories/job_repository.py:119-135` |
| 构建启动/版本 | `app/services/knowledge_service.py:81-128` |
| job 执行/重试 | `app/jobs/runner.py:49-132` |
| 构建主循环 | `app/services/knowledge_service.py:455-498` |
| 分批规则 | `app/services/knowledge_service.py:39-40, 500-548` |
| LLM 适配器/每次新建 client | `app/llm/openai_compatible.py:90-118` |
| 提示词禁止容器 | `app/llm/prompts/knowledge_framework.py:25-31` |
| payload 选择规则 | `app/services/knowledge_service.py:838-862` |
| 合并（HEAD 平铺） | `app/services/knowledge_service.py:604-664`（HEAD） |
| 合并（工作区文档层） | `app/services/knowledge_service.py:604-701`（工作区） |
| 只收集有来源节点 | `app/services/knowledge_service.py:703-720` |
| 持久化递归 | `app/services/knowledge_service.py:332-426` |
| 树返回隐藏根 | `app/services/knowledge_service.py:933-963` |
| 掌握度只查叶子 | `app/repositories/mastery_repository.py:185-202` |
| 掌握度响应 | `app/services/mastery_service.py:48-67` |
| 复习目标选择 | `app/services/mastery_service.py:73-137` |
| 前端 5 分钟超时 | `frontend/src/hooks/useJob.ts:33, 54-61` |
| 前端树递归 | `frontend/src/pages/Knowledge.tsx:79-166` |
| 规范：3–4 层 | `docs/spec/backend-spec.md:274-286` |
| 规范：删除材料策略 | `docs/spec/backend-spec.md:270` |
| 规范：框架生成流程 | `docs/spec/backend-spec.md:358-372` |

### 8.2 复现/核查命令（只读）

```powershell
# 作业耗时
@'
import sqlite3
con = sqlite3.connect('StudyMate/data/studymate.db')
for row in con.execute("""
  select id, status, attempts, max_attempts, started_at, finished_at
  from jobs
  where type='knowledge_framework.build'
  order by created_at desc
"""):
    print(row)
'@ | python -

# 框架层级统计
@'
import sqlite3
con = sqlite3.connect('StudyMate/data/studymate.db')
for row in con.execute("""
  select c.name, v.id, v.version_number, v.status,
         count(n.id) as nodes,
         sum(case when n.level=0 then 1 else 0 end) as roots,
         sum(case when n.level=1 then 1 else 0 end) as level1,
         sum(case when n.level>=2 then 1 else 0 end) as deep,
         sum(case when n.section_label is not null then 1 else 0 end) as labels
  from courses c
  join knowledge_framework_versions v on v.id=c.active_framework_version_id
  join knowledge_node_versions n on n.framework_version_id=v.id
  group by c.id, v.id
"""):
    print(row)
'@ | python -
```

### 8.3 实测批次

```text
f1-sample.pdf                 2 chunks    1 batch
ch1_引言_v2.0(4).pdf        118 chunks   10 batches
ch3_数据链路层_v2.0(3).pdf   120 chunks   10 batches
ch4_MAC子层_v2.0(5).pdf     184 chunks   16 batches
合计                         424 chunks   37 batches
```

### 8.4 术语

- **chapter/section**：课程大纲层级，来自目录/标题结构，不是文件名。
- **leaf**：真正可出题、可复习的知识点；必须有来源。
- **container**：只用于组织，不直接参与出题/掌握度；可以没有来源。
- **stale**：框架仍可读，但其来源资料集合已变化，不允许直接用于新测验。
- **archive**：资料逻辑删除，保留来源可追溯；不是物理删除。

---

## 9. 一句话给后端 agent

> 不要再往 `_merge_batch_candidates` 里加“按文件名分组”了。先把“课程大纲”作为一等产物抽出来，让 chapter/section 成为真正的父节点；再把资料删除做成 archive + stale + rebuild；最后把 37 次串行调用改成按 section 的并行流水线。否则每修一个点，另外两个点都会以另一种形式回来。
