# 知识面板 Phase 1（v5 构建流水线）交接文档

**写给接手的 agent**：你认识的 StudyMate 是 v4 知识构建（12 chunk/14k 字符分批 → 按文档名分桶的两层树）。2026-10-21 我把它重写为三阶段 v5 流水线，本文说明改了什么、为什么、踩过什么坑、接下来做什么。改动**全部未提交**（20 个文件，分支 `frontend/scaffold`，工作树其余干净），提交由用户自己执行。

---

## 0. 一分钟状态

| 项 | 状态 |
|---|---|
| 测试 | 后端 **59 passed**（基线 50）；前端未动（63 vitest 不受影响） |
| 迁移 | head = `20261021_0010`；**dev 库 `data/studymate.db` 已升级**（纯增量：jobs 4 列、`llm_calls`、`knowledge_section_cache`、framework 元数据 2 列） |
| Live 冒烟 | mock://local 下全流程通过（章节树/进度阶段/缓存命中/attempts=1） |
| 未验证 | **真模型（DeepSeek）下 400+ 页课件的构建质量与耗时**——这是第一优先事项，等用户拍板 Phase 2/3 |
| 8000 端口 | 可能还在跑旧代码，需重启才生效（重启前先和用户确认进程归属） |

## 1. 环境速查

- 仓库：`C:\Users\86159\Desktop\hackathon\StudyMate`（分支 `frontend/scaffold`）
- 所有命令用 conda `studymate` 环境（Python 3.13），shell 状态不跨调用保留：
  `source /c/Users/86159/anaconda3/etc/profile.d/conda.sh && conda activate studymate`
- 测试：`python -m pytest -q -p no:cacheprovider`（在 `StudyMate/` 下）
- 起后端：先 `alembic upgrade head`（新库必须），再 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- 根级 `CLAUDE.md` 是权威行为规范（错误信封、无假数据、密钥红线等）——已打上 v5 补丁，先读它。

## 2. 改动清单（旧 → 新映射）

**新增文件**
- `app/services/knowledge_outline_service.py` — Stage A：PDF `get_toc()` → 字号+编号标题启发 → LLM 兜底（`KNOWLEDGE_OUTLINE_FAILED` 显式失败，不用文件名造结构）；PPTX 标题占位符（`PP_PLACEHOLDER.TITLE/CENTER_TITLE`）；多文档按规范化标题合并（NFKC+casefold+空白折叠）。
- `app/services/knowledge_pipeline.py` — Stage B/C 核心：窗口切分（28k 字符）、ThreadPool(3) 并发 LLM、`BuildBudget`（270s 截止，单次超时按剩余预算÷内层重试数钳制）、`knowledge_section_cache` 断点缓存、`IdentityResolver` 身份裁决、`ProgressReporter`、`_persist_containers` 原子激活。纯函数（`normalize_title_key`/`is_quality_topic`/`compute_phase_progress` 等）都可直接单测。
- `app/llm/prompts/knowledge_outline_v5.py`、`knowledge_framework_v5.py` — 英文提示词（防注入措辞沿用 v4）；版本常量 `knowledge-outline-v5` / `knowledge-framework-v5`。
- `app/db/models/llm_call.py` + 迁移 `20261021_0010_*.py`。

**修改**
- `knowledge_service.py`（977→约 380 行）：v4 批处理全删；`start_build` 加 409 守卫（`get_building_framework_version` + `has_pending_build_job`，崩溃遗留自愈为 failed）；`build_framework_job` 委托 pipeline；payload 模型加 `job_id`。
- `openai_compatible.py`：mock 新增 `KnowledgeOutlineV5`/`KnowledgeSectionExtractionV5` 两分支（从 payload 的 `page_inventory`/`source_segments` 合成合法输出）；`generate_structured_output` 加 `timeout_seconds` 可选参数；`LLMRunSummary` 加 `latency_ms`/`attempts`。
- `job.py` 模型 + `JobResponse`：新增 `phase/completed_units/total_units/message`（可空，旧任务为 None）。
- `knowledge_repository.py`：`find_node_by_stable_key`/`update_node_stable_key`/`get_building_framework_version`/`has_pending_build_job`/`get_section_cache_payloads`/`add_section_cache_entry`。
- `job_repository.py`：`update_progress`（单调不回退）。
- 测试：`tests/unit/test_knowledge_merge.py` 重写（outline 三路/合并/身份四分支/进度/质量）；`tests/integration/test_knowledge.py` 重写（章节树全流程/窗口化/缓存+身份稳定/409/自愈/attempts=1/PPTX）；`test_health.py` 的 head 断言更新为 0010。

## 3. 设计决策（不要推翻，都有测试锚定）

1. **身份规则**：叶子 `stable_key = "v1:"+sha256(course_id|norm_title|primary_doc|primary_page)`，与树路径无关；primary source 取 `(page_number, document_id, chunk_id)` 最小者。旧节点按规范化标题匹配：唯一→复用并改写 stable_key；多个候选恰一个有 `student_gap_states` 数据→复用那个；多个有数据→新建+诊断孤儿化。**绝不把两份掌握度合并到同一节点**。容器用 `v5path::sha256(course|路径)`。
2. **缓存与观测写入用独立短事务 session**（`session_scope()` 开-提交-关），绝不用 handler 的 session——它到 runner 收尾才 commit，中间写进度轮询读不到，且会持 SQLite 写锁。缓存只存通过 Pydantic 校验的结果；失败 job 的已完成 section 缓存保留供续跑。
3. **D5 修复形态**：构建 job `max_attempts=1`（AppError 本就不被外层重试）；`LLMTemporaryError` 在 worker 内有界重试 1 次；`JOB_DEADLINE_EXCEEDED` 显式失败。270s 截止 < 300s `job_lock_timeout_seconds`，保证不被 stale 恢复重跑。
4. **DB 写入全在主线程**；ThreadPool 只跑 LLM 调用（无 DB 访问）。
5. **旧契约不变**：`GET /knowledge` 的 tree/nodes 形状、`GET /knowledge/{id}` 详情（新构建 relations 为空）、`GET /jobs/{id}` 新字段可空——旧前端零改动可用。

## 4. 踩过的坑（按复发概率排序）

1. **`alembic/env.py` 强制 `config.set_main_option("sqlalchemy.url", settings.database_url)`**——传临时 URL 给 Config 无效，会打到默认 dev 库！迁移临时库必须 `DATABASE_URL=... python -m alembic upgrade head`（环境变量优先）。
2. **Git Bash 的 `/tmp` 对 Windows Python 无效**（sqlite "unable to open database file"）。临时目录一律 `python -c "import tempfile;print(tempfile.mkdtemp())"`。
3. **中文测试 PDF 必须 `page.insert_text(..., fontname='china-s')`**，否则提取出的是占位符。
4. **mock://local 按 `response_model` 身份分发**（`_build_mock_candidate`），新增响应模型不加分支直接 `LLM_OUTPUT_INVALID`。
5. `normalize_title_key` 是"空白折叠为单空格"不是"去空白"：`'旧概念' ≠ '旧 概念'`，但 `'tcp 协议' == 'TCP  协议'`。
6. 冒烟/脚本优先用 Python `urllib`（Windows curl 中文 JSON 会坏）；uvicorn 冒烟结束记得 terminate，否则端口占用（winerror 10048）。

## 5. 接下来的工作（按优先级）

### ① 真模型验收（第一优先，用户在等这个结果拍板）

1. 与用户确认后重启 8000 端口后端（先 `GET /api/health` 辨别是不是 StudyMate；8000 曾被用户的 KnowledgeForge 占用）。
2. 用现有 DeepSeek 配置（已存在 DB 设置里，**不要动 .env**）对真实课件重建：课程列表 `GET /api/courses`，主课程（id 前缀 `204637ae`，400+ 页）和/或验收课程（`96d00dc9`）。`POST /api/courses/{id}/knowledge/build`，轮询 `GET /api/jobs/{id}`。
3. 验收点：章节树 3-4 层且章名来自原文；构建耗时（目标 5 分钟预算内，首跑可能贴近，超时是干净的 `JOB_DEADLINE_EXCEEDED` 失败且缓存保留）；再次构建的提速（缓存命中）；`sqlite3 data/studymate.db "select purpose,count(*),avg(latency_ms) from llm_calls group by purpose"`；**掌握度孤儿率**——对比 `student_gap_states.knowledge_node_id` 与新 active 版本叶子 id 的交集（旧 v4 标题与新 v5 标题匹配率未知，孤儿化是已接受的风险，但要给用户数字）。
4. 把以上数字报给用户，由用户决定是否继续。

### ② 尾巴清单（小事，随手）

- 前端 `frontend/src/…/errors.ts` 补 3 个新错误码中文文案（`KNOWLEDGE_BUILD_IN_PROGRESS`/`KNOWLEDGE_OUTLINE_FAILED`/`JOB_DEADLINE_EXCEEDED`），同步 `errors.test.ts` 快照；这是本轮唯一合理的前端改动。
- `StudyMate/README.md` "已知限制"若还写着"知识树按文档分组"，按 v5 章节树更新。
- 用户确认后由用户 commit（历史惯例：用户自己提交，agent 不要 commit）。

### ③ Phase 2（类型化关系，用户拍板后才做）

参考用户手里的 GPT 方案 v1.0 Phase 2 章节 + 以下修正/事实：
- `knowledge_node_relations.confidence` 目前 **NOT NULL**——Phase 2 第一个迁移就是改可空 + 加 `explanation`/`evidence_refs_json` 列。
- 关系抽取 = Stage B 同 section 顺带 + 全局 pass（候选对生成：标题词项重合 + 跨 section 优先 + 每节点/全局上限，防毛球）；quote 必须能在 chunk 原文匹配。
- 节点详情现在**只返回出边**——`get_node_detail` 要补入边方向（prerequisite 两个方向都要能用）。
- 新关系模型需要 mock 分支（允许返回空列表）。
- graph API：`GET /courses/{id}/knowledge/graph`（扁平 nodes+edges，React Flow 消费）。

### 红线（任何阶段都不要做）

- 不 commit/push（用户执行）；不改 quiz 生成/判分与 Beta-Binomial 掌握度模型；不引入 LangChain/GraphRAG/图数据库/新消息队列；真实模式失败不得静默降级 mock；无证据不评分；不把文档文件名当容器标题；不在日志/观测表写 API Key 或完整 prompt。

## 6. 相关文档索引

- 团队评审契约（章节树目标形态，v5 依据）：`StudyMate/docs/reviews/backend-knowledge-design-review-2026-10-20.md` §3.5/§4.6
- 真模型验收历史（D1-D8 缺陷定义）：`StudyMate/docs/testing/real-model-acceptance-report-2026-10-20.md`
- 行为规范与环境：仓库根 `CLAUDE.md`（已含 v5 补丁）
