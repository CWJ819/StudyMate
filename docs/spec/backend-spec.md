StudyMate

后端技术设计与开发实施规范

面向 Codex 的可执行工程规范 · V1.0

技术栈：Python 3.12+ · FastAPI · SQLAlchemy 2 · SQLite · Alembic

部署范围：单用户、本机可信环境

# 文档说明

本文档是 StudyMate 后端 V1 的统一需求、架构与实施规范。目标读者包括开发者和代码生成代理（Codex）。文档中的“必须”“不得”“应当”属于实现约束；除非用户明确批准变更，不应由实现者自行替换。

V1 的目标是构建一个可运行、可测试、可恢复的本地学习复习后端，而不是一次性实现复杂的分布式平台。架构要清晰、数据要可追溯、核心算法要可解释，并为后续扩展保留边界。

# 目录

- 1. 产品目标与核心流程

- 2. V1 范围与明确约束

- 3. 技术选型与系统架构

- 4. 工程目录与模块职责

- 5. 数据模型与数据库设计

- 6. 材料导入、解析与知识框架构建

- 7. LLM 接入与提示词治理

- 8. 题目生成、测验、判分与答案隔离

- 9. 错误诊断、知识点关联与掌握度估计

- 10. 复习选择策略与学习计划

- 11. 持久化后台任务

- 12. API 接口规范

- 13. 配置、日志、安全与错误处理

- 14. 测试策略与验收标准

- 15. Codex 分阶段开发计划

- 附录 A：AGENTS.md 建议内容

- 附录 B：开发完成检查清单

# 1. 产品目标与核心流程

StudyMate 是一个以课程资料为基础的复习辅助系统。系统从教师课件中提取课程结构和知识点，依据学生选择的复习范围生成练习题，记录作答表现，分析可能存在的知识缺口，并根据掌握度和覆盖情况安排后续复习。

## 1.1 核心用户流程

1. 创建课程，并上传教师 PPT/PPTX 或可提取文本的 PDF；可选上传教材 PDF 作为辅助结构参考。

1. 后台解析文件，保留页码、原始文本和解析状态，形成可追溯的材料片段。

1. 基于课件建立课程知识框架；如提供教材目录，可用于辅助组织层级，但课件是主要内容依据。

1. 用户查看、检查和必要时修订知识点结构；知识框架以版本形式保存。

1. 学生选择关注知识点或复习范围，系统生成一组初始难度较低、数量约为 10 道的题目。

1. 学生作答；后端对客观题确定性判分，对简答题按预定义评分标准调用 LLM 评分。

1. 系统结合题目涉及的知识点、学生答案和评分证据，诊断潜在缺口并更新掌握度估计。

1. 下一轮复习在已发现的薄弱点复测与未充分测试知识点探索之间进行平衡。

1. 系统根据考试日期、每日可用时间、目标分数和知识状态生成可调整的学习计划。

## 1.2 设计原则

- 可追溯：知识点、题目、评分、诊断和学习任务应尽可能保留来源及版本信息。

- 不把一次错误等同于知识点完全不会；所有推断都应带有证据和不确定性。

- 客观判分由后端规则决定，LLM 不得覆盖客观判分结果。

- 知识点之间的关系用于组织、检索、诊断和复习排序，不作为错误传播的自动依据。

- 模型输出必须经过结构校验；模型不是数据库、权限或业务规则的最终控制者。

- 关键状态变化可审计、可幂等，任务中断后可以恢复。

- V1 优先保证单机可用、行为明确、测试覆盖充分，不提前引入复杂分布式基础设施。

# 2. V1 范围与明确约束

| 项目 | V1 决策 | 实施要求 |
| --- | --- | --- |
| 运行环境 | 本地单用户 | 默认只绑定 127.0.0.1；无身份认证；不面向局域网或公网直接部署。 |
| 语言与版本 | Python 3.12+ | 使用类型标注、Pydantic 2 和现代 SQLAlchemy 2 API。 |
| Web 框架 | FastAPI | 提供版本清晰的 REST API 与 OpenAPI 文档。 |
| 数据库 | SQLite + SQLAlchemy 2 + Alembic | 数据库变更必须使用迁移管理；不在运行时静默重建生产表。 |
| LLM | OpenAI 兼容 API | base_url、API key、model 可配置；集中封装超时、重试、结构化输出与错误分类。 |
| 文件存储 | 本地文件系统 | 文件名使用服务端生成的存储键；数据库保存元数据和相对路径。 |
| 后台任务 | SQLite 持久化任务表 + 进程内 worker | 支持进度、重试、失败记录和进程重启恢复；不宣称支持多实例高可用。 |
| OCR | 不支持 | 只提取 PDF 内嵌文本；扫描件或无文本页标记为 NO_EXTRACTABLE_TEXT，不猜测、不伪造。 |
| 客观题判分 | 后端确定性判分 | 多选题仅当所选选项集合与标准答案集合完全一致时得满分；不提供部分分。 |
| 简答题判分 | LLM + 预定义评分标准 | 结构化评分结果必须校验；保留评分理由与标准版本。 |
| 掌握度 | Beta-Binomial 基础估计 | 以可解释的成功/失败证据更新；保留事件记录和算法版本。 |
| 认证 | 暂不实现 | 不得把当前版本描述为可安全公开访问。 |

## 2.1 非目标

- 不实现 OCR、图像理解或扫描版 PDF 自动识别。

- 不实现多租户、用户注册、权限系统或公开互联网部署。

- 不引入 Celery、Redis、Kafka 等分布式任务基础设施。

- 不在 V1 实现真正的 Monte Carlo Tree Search（MCTS）；复习策略采用透明的启发式方法。

- 不把 LLM 对知识点关系、掌握程度或学生能力的单次判断视为客观事实。

- 不保证任意 OpenAI 兼容服务都支持完全一致的结构化输出能力；必须有校验与失败处理。

# 3. 技术选型与系统架构

## 3.1 主要依赖

| 类别 | 建议依赖/方式 | 用途 |
| --- | --- | --- |
| API | fastapi、uvicorn | HTTP 接口与本地服务启动。 |
| 校验与配置 | pydantic、pydantic-settings | 请求/响应模型和环境配置。 |
| ORM 与迁移 | sqlalchemy 2、alembic | 数据库访问与 schema 版本控制。 |
| 数据库 | sqlite | 本地单实例持久化。 |
| PPTX 解析 | python-pptx | 提取幻灯片文字与页序信息。 |
| PDF 解析 | pymupdf 或 pypdf（择一并统一封装） | 提取页面文本并记录页码。 |
| HTTP 客户端 | httpx 或所选 OpenAI SDK | 调用兼容 LLM API。 |
| 测试 | pytest、httpx 测试客户端 | 单元、集成与 API 测试。 |

## 3.2 逻辑架构

```text
Client / Swagger UI
|
v
FastAPI Routes  ---- Pydantic Schemas
|
v
Application Services
|        |        |         |
v        v        v         v
Repositories  LLM Adapter  Job Queue  Local Storage
|        |        |         |
v        v        v         v
SQLite   OpenAI-compatible API   Worker   Filesystem
```

路由层负责 HTTP 协议、输入输出和状态码；服务层承载业务流程；仓储层负责持久化访问；LLM 适配层隔离供应商差异；任务层管理长耗时操作；文件存储层负责安全落盘和读取。路由不得直接编写复杂 SQL 或拼接业务提示词。

## 3.3 事务与一致性

- 一次业务操作涉及多张表时，尽量在明确的数据库事务中完成。

- 文件系统与数据库无法组成单一 ACID 事务：上传时采用临时文件写入、校验、原子重命名，再提交元数据；失败时清理临时文件。

- 知识框架重建先写入新版本，全部验证成功后再切换课程当前活动版本；失败不得破坏旧版本。

- 提交答案时必须保证判分、attempt 记录、证据记录和掌握度事件不会因重复请求重复应用。

- 后台任务处理器应设计为幂等；任务重复执行不应造成重复导入、重复生成或重复更新掌握度。

# 4. 工程目录与模块职责

```text
studymate-backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── dependencies.py
│   │   └── routes/
│   ├── core/
│   │   ├── config.py
│   │   ├── errors.py
│   │   └── logging.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   ├── llm/
│   │   ├── base.py
│   │   ├── openai_compatible.py
│   │   ├── schemas.py
│   │   └── prompts/
│   ├── jobs/
│   │   ├── runner.py
│   │   └── handlers.py
│   └── storage/
│       └── local.py
├── tests/
│   ├── unit/
│   └── integration/
├── data/
├── .env.example
├── .gitignore
├── AGENTS.md
├── alembic.ini
├── pyproject.toml
└── README.md
```

| 模块 | 职责边界 |
| --- | --- |
| api/routes | 解析 HTTP 请求、调用 service、返回响应；不直接实现领域算法。 |
| schemas | 请求、响应、LLM 结构化输出模型；禁止将 ORM 对象无约束地直接暴露。 |
| services | 编排课程、材料、知识框架、测验、判分、掌握度和计划等用例。 |
| repositories | 封装 ORM 查询与持久化；避免跨领域业务逻辑。 |
| llm | 统一供应商配置、调用、超时、重试、解析、schema 校验和错误归类。 |
| jobs | 持久化任务的领取、锁定、重试、恢复、进度和结果状态。 |
| storage | 本地文件安全写入、读取、删除和路径约束。 |
| core | 配置、日志、通用异常、请求追踪等基础设施。 |

# 5. 数据模型与数据库设计

以下是逻辑实体清单，Codex 可以在不改变语义的前提下调整物理字段名和拆分方式，但必须维持实体关系、历史可追溯性和幂等约束。所有主键建议使用 UUID 字符串或统一的整数主键；全项目必须保持一致。日期时间统一存 UTC，API 层以 ISO 8601 表示。SQLite 外键约束应显式启用。

## 5.1 主要实体

| 实体 | 关键字段/关系 | 说明 |
| --- | --- | --- |
| courses | id, name, description, active_framework_version_id, created_at | 课程根实体。 |
| documents | id, course_id, filename, storage_key, mime_type, size_bytes, status, error_code | 上传材料元数据和处理状态。 |
| document_pages | id, document_id, page_number, extracted_text, extraction_status, error_code | 逐页文本与提取状态；保留页码。 |
| document_chunks | id, document_id, page_start, page_end, text, content_hash | 检索和上下文拼接用片段，保留来源页。 |
| jobs | id, type, status, payload_json, progress, attempts, max_attempts, run_after, locked_at, error_code, error_summary | 持久化任务队列。payload 不存密钥或完整原始文件。 |
| knowledge_framework_versions | id, course_id, version_number, status, created_at, activated_at | 知识框架版本。 |
| knowledge_nodes | id, course_id, stable_key, created_at | 跨版本保持身份的知识点。 |
| knowledge_node_versions | id, framework_version_id, knowledge_node_id, parent_id, title, description, level, is_leaf, sort_order | 某版本下的知识点树节点内容。 |
| knowledge_sources | id, node_version_id, document_id, page_number, chunk_id, evidence_type | 知识点来源证据。 |
| knowledge_node_relations | id, framework_version_id, source_node_version_id, target_node_version_id, relation_type, confidence, evidence | 同版本下的知识点关系。 |
| questions | id, course_id, type, stem, options_json, answer_key_json, rubric_json, explanation, difficulty, source_metadata_json, content_hash | 题目主数据；敏感答案字段不得直接暴露给学生。 |
| question_knowledge | question_id, node_version_id, relation_role, weight | 一题可关联多个知识点，并标注主测/次测或权重。 |
| quizzes | id, course_id, framework_version_id, status, settings_json, created_at | 测验实例。 |
| quiz_questions | quiz_id, question_id, ordinal, question_snapshot_json | 测验题目快照，确保历史不随题库变更。 |
| attempts | id, quiz_id, question_id, idempotency_key, submitted_answer_json, score, max_score, grading_method, feedback_json, submitted_at | 一次作答记录。 |
| knowledge_gaps | id, course_id, node_version_id, gap_type, status, confidence, evidence_summary_json | 可解释的缺口诊断。 |
| attempt_gap_evidence | id, attempt_id, gap_id, evidence_type, strength, rationale | 将具体作答证据关联到缺口。 |
| student_gap_states | id, course_id, knowledge_node_id, alpha, beta, mastery_estimate, evidence_count, updated_at | 当前知识点掌握度状态。 |
| mastery_events | id, state_id, attempt_id, evidence_type, delta_alpha, delta_beta, old_estimate, new_estimate, algorithm_version, created_at | 掌握度变更审计事件。 |
| question_generation_runs | id, quiz_id, prompt_version, model_name, input_summary_json, output_summary_json, status | 生成运行元数据，不记录密钥。 |
| review_strategy_logs | id, course_id, selected_targets_json, strategy_version, rationale_json, created_at | 记录复习选择依据。 |
| study_plans | id, course_id, version_number, exam_date, daily_minutes, target_score, status, constraints_json | 计划版本。 |
| study_tasks | id, plan_id, title, task_type, scheduled_date, estimated_minutes, priority, status | 计划中的任务。 |
| study_task_targets | task_id, knowledge_node_id, target_role | 任务与知识点目标的关联。 |
| settings | key, value_json, updated_at | 仅存普通非敏感偏好；不得把 API key 明文放在此表。 |

## 5.2 关键约束

- 文档、页面、片段、知识点来源之间应可追溯到具体文件和页码。

- 知识点稳定身份与版本化内容分离；改名、拆分、合并应有明确映射策略，不能直接覆盖历史版本。

- 题目与测验保存快照，历史测验不因后续题目修改或知识框架更新而改变。

- attempt 的 idempotency_key（或等价机制）必须有唯一约束，防止重复提交重复计分。

- 掌握度更新需有唯一性保护，避免同一 attempt 对同一知识点重复应用。

- 删除材料时要定义来源引用策略：至少不能留下指向不存在文件且未标记失效的来源；必要时使用软删除。

- SQLite 中需要的复合索引、唯一索引和外键应在 Alembic 迁移中定义。

## 5.3 知识点树与关系

知识点树建议允许 3–4 层，但不能强制所有课程达到固定深度。结构层级用于导航和课程组织；知识点之间的关联关系另行保存，不要把所有关联都硬塞进父子树。

| 关系类型 | 用途 | 约束 |
| --- | --- | --- |
| parent-child | 目录层级与聚合展示 | 由 parent_id 表达，不重复存为普通关系。 |
| related | 概念相近、经常一起出现、适合联合复习 | 可以是弱关系；不直接导致掌握度传播。 |
| prerequisite | 存在明确的先修依赖时使用 | 必须有证据或人工确认；允许未知，不强迫每个知识点都指定先修项。 |
| often_confused | 容易混淆、易错辨析 | 用于对比题和针对性反馈。 |
| part_of | 某知识点是另一主题的组成部分 | 若已由目录父子关系表达则避免重复。 |

复习阶段不应强制推断严格先修 DAG。关系的主要作用是：帮助组织检索上下文、为题目选择补充候选、支持跨知识点错误诊断、生成对比题、展示学习路径，以及在用户明确确认时辅助安排复习顺序。关系是建议性信号，不是判定学生不会某个关联知识点的充分证据。

## 5.4 知识框架版本切换

1. 创建新的 framework_version，状态为 building。

1. 构建知识点节点、来源映射和关系。

1. 验证节点引用、父子结构、来源页码、关系端点及重复项。

1. 验证失败则将新版本标记 failed，旧活动版本保持不变。

1. 验证成功后在一个事务中标记新版本 active，并更新 courses.active_framework_version_id。

1. 保留旧版本及历史测验、作答和掌握度所引用的版本。

# 6. 材料导入、解析与知识框架构建

## 6.1 上传与文件验证

- 只接受明确允许的扩展名和 MIME 类型；扩展名与实际类型不匹配时拒绝或标记异常。

- 限制上传字节数、页数和解压后体量；限制值从配置读取。

- 使用服务端生成的存储键，不使用用户文件名作为实际路径。

- 防止路径穿越；所有读写路径都必须位于 STORAGE_ROOT 内。

- 上传先写临时文件，完成基本校验后原子移动，再创建或更新数据库状态。

- 解析是长耗时任务，应通过后台任务执行，不要在上传 HTTP 请求中同步执行完整 LLM 流程。

## 6.2 PPTX 解析

- 按幻灯片顺序提取可访问的文本框文字，并记录 slide/page number。

- 保留标题、正文和文本顺序；如果可以可靠识别标题层级，应保留其角色。

- 不要声称已提取图片、图表、公式图片或嵌入对象中的文字。

- 空白页可以记录为空页，不应伪造内容。

- 解析结果应存入 document_pages 和 document_chunks，并保留来源元数据。

## 6.3 PDF 解析与 OCR 禁止规则

- 仅进行文本层提取；V1 不实现 OCR。

- 逐页记录 page_number、extracted_text 和 extraction_status。

- 无可提取文本的页面标记为 no_extractable_text，并记录稳定错误码 NO_EXTRACTABLE_TEXT。

- 如果整份 PDF 都没有可用文本，则材料处理失败并返回清晰错误状态；不得调用 LLM 凭空重建文本。

- 如果部分页面成功、部分页面无文本，保留成功页面，整份文档标记 completed_with_warnings，并列出缺失页码。

- 对解析失败的单页记录错误信息，不能让一页失败导致所有成功页丢失。

- 不得把“没有提取到文本”表述为“通过 OCR 识别失败”；系统根本没有执行 OCR。

## 6.4 分块与检索

- 分块时尽量不跨文档；若跨页，保存 page_start/page_end 与源页面引用。

- 优先按段落、标题或自然边界切分；避免只按固定字符数截断导致上下文破碎。

- 保存 content_hash，用于避免重复导入相同片段。

- V1 可以先使用 SQLite 基础文本搜索或应用层检索，不必强制引入向量数据库。

- 提供课程内搜索接口，并在结果中返回文档、页码、片段 ID 等出处信息。

## 6.5 知识框架生成流程

1. 从课件中抽取标题、页面文本和章节线索。

1. 如果有教材目录，将其作为辅助结构参考，而不是覆盖课件事实。

1. 调用 LLM 生成结构化候选知识点树，并要求每个叶子节点附带来源页码或片段引用。

1. 校验引用确实存在、节点标题非空、父子结构合法、层级不过度碎片化。

1. 将无法定位到来源的节点标记为待核验或拒绝写入，不允许静默编造来源。

1. 保存新框架版本，待验证完成后原子切换。

1. 通过 API 返回框架和警告，让前端可以展示并允许用户修订。

# 7. LLM 接入与提示词治理

## 7.1 配置

```text
APP_ENV=development
DATABASE_URL=sqlite:///./data/studymate.db
STORAGE_ROOT=./data/uploads
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
MAX_UPLOAD_BYTES=
MAX_DOCUMENT_PAGES=
JOB_MAX_ATTEMPTS=3
```

空的 LLM 配置不应必然导致应用无法启动；纯本地功能和健康检查应可运行。实际执行需要 LLM 的任务时，若配置缺失，应返回可理解的配置错误。不要在 API 响应、日志或普通设置表中泄露 API key。

## 7.2 统一 LLM 适配层

- 所有 LLM 调用必须经过统一接口，不允许各业务 service 自行复制 HTTP 调用代码。

- 统一处理 base_url、model、API key、超时、有限重试、错误分类和请求追踪。

- 对结构化输出进行 JSON 解析、Pydantic 校验和业务语义校验。

- 对超时、限流、网络错误、鉴权失败、模型输出格式错误分别归类。

- 重试只针对适合重试的临时错误；鉴权失败和确定性 schema 错误不得无限重试。

- 模型名称和提示词版本写入运行记录，便于复现和排查。

## 7.3 提示词与不可信输入

- 课件文本、教材文本、用户输入和学生答案均视为不可信内容。

- 提示词明确指示模型把资料当作待分析内容，而不是可执行指令。

- LLM 不得自行执行 SQL、读取任意文件、调用任意 API 或改变系统权限；工具能力由应用代码控制。

- 不要把历史题目的标准答案、学生作答正确性或诊断标签提供给新题生成模型，除非某个独立任务明确需要且有边界。

- 日志不记录 API key；默认不记录完整敏感提示词和学生答案，必要调试日志必须可控并避免长期保留。

## 7.4 LLM 输出校验

- 题目必须具有有效题型、题干、选项（如适用）、答案键、解释和知识点映射。

- 答案键只能引用当前题目的合法选项 ID。

- 知识点 ID 必须属于当前课程活动框架版本，或明确标记为待映射候选。

- 模型返回缺字段、额外不允许字段、非法 ID 或格式不正确时，按失败处理或进行有限修复重试，不可直接入库。

- 保存生成状态、模型、提示词版本、校验错误摘要和最终结果摘要。

# 8. 题目生成、测验、判分与答案隔离

## 8.1 初始题目生成

学生指定复习范围后，默认生成约 10 道难度较低的题目；数量和难度应配置化。生成上下文优先包括所选知识点、对应课件片段、常见考试重点（若有明确证据）和题型约束。不得只凭模型自由联想生成与课程材料无关的事实题。

## 8.2 知识点映射

- 一题可以关联多个知识点。

- 关联记录需要区分主要考查目标与次要相关点，或使用明确的权重。

- 题目覆盖多个知识点并不意味着学生答错时所有关联点都应被判为薄弱。

- 知识点映射可由 LLM 提议，但必须经过存在性校验，并保存映射证据或理由。

- 如无法可靠定位主要考查点，应标记不确定，避免把错误证据平均传播到所有知识点。

## 8.3 历史题去重与变式

- 生成前检索同课程、同知识点范围内的历史题目。

- 使用规范化题干哈希进行精确去重；可以再做文本相似度去重；语义去重可作为后续增强。

- 给新题生成模型提供历史题目文本以避免重复，但不提供这些历史题的答案和作答正确性。

- 变式题应改变考查角度、推理路径或应用场景，而不是仅机械替换数字。

- 去重失败的候选题应丢弃或重新生成，并限制重试次数。

## 8.4 客观题判分规则

客观题必须由后端确定性判分。多选题使用选项 ID 集合比较，选项顺序不影响结果。只有提交集合与标准答案集合完全一致才得满分；漏选、多选或选错均为零分，不给部分分。

```text
selected = set(submitted_option_ids)
expected = set(answer_key_option_ids)
validate_all_ids_belong_to_question(selected)
score = max_score if selected == expected else 0
```

- 重复选项 ID、未知选项 ID、格式错误或不属于该题的 ID 应拒绝为无效提交，不得悄悄修正。

- 单选题同样要验证只提交一个合法选项 ID。

- 后端判分结果是权威结果，LLM 不得覆盖或重新解释为得分。

- 测试必须覆盖：完全匹配、顺序不同但集合相同、漏选、多选、选错、非法 ID、重复 ID 和空提交。

## 8.5 简答题判分

- 每道简答题生成时应有预定义 rubric，列出关键要点、分值权重和允许的合理表达变体。

- 将学生答案、题干、标准参考答案和 rubric 交给 LLM 评分；要求返回结构化分数、要点命中情况、简短理由和反馈。

- 后端验证分数范围、要点 ID、字段完整性；越界分数必须拒绝或按明确规则裁剪并记录，不能静默接受。

- 评分提示词版本、模型、分数、理由和原始结构化结果摘要应可追溯。

- LLM 暂时不可用时，应将评分任务标记为可重试/待处理，不得伪造评分成功。

## 8.6 答案隔离与测验快照

- 学生提交前的 GET quiz 响应不得包含标准答案、评分 rubric、隐藏解释或可推导答案的内部元数据。

- 答案键和 rubric 只在后端判分服务中读取；提交后只返回授权展示的反馈。

- 测验创建时保存题目快照，保证后续题目编辑不会改变已创建测验的题目内容。

- 写入操作支持幂等键；相同请求重试不应重复创建 attempt 或更新掌握度。

- 答案键不得通过错误消息、调试字段或 ORM 自动序列化泄漏。

# 9. 错误诊断、知识点关联与掌握度估计

## 9.1 从错误到知识缺口

系统不能仅根据“某题答错”就断言某个知识点不会。诊断流程应结合题目考查目标、学生具体答案、评分 rubric、来源材料和历史证据，输出候选缺口、置信度和理由。诊断结果是带不确定性的证据，不是永久标签。

- 优先定位题目的主要考查知识点和具体失误类型，例如概念混淆、公式使用错误、步骤遗漏或粗心。

- 如果一道题关联多个知识点，除非答案证据分别支持，否则不要对所有知识点都施加同等失败证据。

- 学生答案若显示其掌握了相关概念但出现算术失误，应避免直接将整个概念标记为不会。

- 关联知识点可作为进一步验证候选：系统可以生成一题验证题，而不是自动传播负面掌握度。

- 诊断必须保存 evidence_type、strength/confidence、rationale 和对应 attempt。

## 9.2 Beta-Binomial 掌握度模型

V1 使用可解释的 Beta-Binomial 估计。对每个知识点维护 alpha 和 beta 参数，初始先验建议为 alpha0 = 2、beta0 = 2。掌握度点估计为 alpha / (alpha + beta)。

```text
theta_g ~ Beta(alpha_g, beta_g)
mastery_g = alpha_g / (alpha_g + beta_g)
correct evidence: alpha_g += evidence_weight
incorrect evidence: beta_g += evidence_weight
```

权重应由评分结果和诊断置信度按明确规则确定。客观题完全正确/错误可使用默认单位权重；简答题若要使用部分得分，必须先定义得分到成功/失败证据的映射方式，不能由实现者临时随意设计。

- 每次更新写入 mastery_events，包含 old/new estimate、参数变化、证据来源和算法版本。

- 同一 attempt 对同一知识点的更新必须幂等。

- 对于多知识点题目，默认只对有证据支持的主要考查点更新；其他关联点可以进入待验证队列。

- 不要仅保存一个 mastery 数字；同时保存证据数量和不确定性相关信息，避免把少量样本造成的极端估计当作确定事实。

- 掌握度是学习决策的估计信号，不应被描述为学生真实能力的精确测量。

## 9.3 缺口状态与置信度

| 状态/概念 | 含义 | 建议行为 |
| --- | --- | --- |
| suspected | 有初步错误证据，但不确定性较高 | 安排低成本验证题。 |
| confirmed | 多个独立证据支持存在薄弱点 | 提高复习优先级，提供讲解与针对性练习。 |
| improving | 近期证据显示表现改善 | 继续间隔复测，避免过早清除。 |
| resolved/provisional | 已有较强正向证据，但仍可能遗忘 | 降低优先级，保留低频复测。 |
| uncertain | 证据不足或题目映射不可靠 | 优先收集证据，不做强诊断。 |

状态阈值应配置化并带版本记录。不要在缺少证据时声称某个缺口已经被“证明解决”。

# 10. 复习选择策略与学习计划

## 10.1 复习题目选择

V1 使用可解释的启发式策略，而非真正的 MCTS。选择策略应同时考虑薄弱程度、缺口置信度、考试相关性、距上次复习的时间、测试覆盖率和探索价值。

```text
priority_g = (1 - mastery_g) ** alpha
* exam_relevance_g
* evidence_confidence_g
* recency_factor_g
```

公式中的每个因子应有明确范围、默认值和测试。对于证据置信度低或测试次数少的知识点，不能简单因当前掌握度高而永久排除。每轮选择应保留探索配额，例如在复习题和探索题之间配置比例；具体比例应可配置，并通过策略日志记录选择理由。

## 10.2 三类复习动作

| 动作 | 目标 | 例子 |
| --- | --- | --- |
| 复测已确认缺口 | 确认是否真正改善 | 针对近期反复出错的公式使用生成新题。 |
| 验证不确定缺口 | 区分概念不会与偶然失误 | 对同一概念换一种问法进行短题测试。 |
| 探索覆盖不足知识点 | 避免只盯着已知错误，提升整体覆盖 | 抽取尚未测试或长时间未复习的叶子知识点。 |

## 10.3 学习计划

- 计划输入可包括考试日期、每日可用分钟数、目标分数、复习范围、优先知识点和当前掌握度。

- 任务类型可以包括学习资料、复习笔记、练习、错题回顾、验证测试和间隔复测。

- 每个任务应有估计时长、日期、优先级、状态和目标知识点。

- 每天排定任务总时长必须不超过每日可用时间；若有可选任务，应明确标注可选而不是算入强制计划。

- 重新生成计划时创建新版本，不覆盖历史版本；已完成任务的历史状态必须保留。

- 计划生成结果必须验证日期、时长、任务目标引用和时间约束。

# 11. 持久化后台任务

## 11.1 任务状态

| 状态 | 含义 |
| --- | --- |
| queued | 等待执行。 |
| running | 当前被 worker 领取执行。 |
| retry_wait | 临时失败，等待到 run_after 后重试。 |
| succeeded | 成功完成。 |
| failed | 超过重试次数或发生不可重试错误。 |
| cancelled | 被明确取消（若 V1 提供取消能力）。 |

## 11.2 Worker 行为

- worker 从 SQLite 原子领取一个可执行任务，设置状态、锁定时间和尝试次数。

- 任务处理器必须按类型路由，并校验 payload schema。

- 临时网络错误、超时、限流可按有限次数指数退避；确定性输入错误或鉴权错误应尽快失败。

- 应用启动时检查过期的 running 任务，并根据任务幂等性将其重新排队或标记为需要人工处理。

- 每个任务记录 progress、开始/结束时间、错误码和安全的错误摘要。

- 不把 API key、完整文件内容或不必要的学生答案放进 payload_json。

- SQLite 单进程任务系统只适用于本地单实例；不能声称具备多实例并发调度或高可用能力。

## 11.3 典型任务类型

- document.parse

- knowledge_framework.build

- quiz.generate

- attempt.grade_short_answer

- attempt.diagnose_gaps

- study_plan.generate

# 12. API 接口规范

以下接口为 V1 建议契约。Codex 可以补充分页、过滤和统一响应字段，但不得移除核心能力或泄露内部答案数据。所有请求和响应都应由 Pydantic schema 校验。长任务应返回 job_id，由客户端轮询任务状态。

## 12.1 通用接口

| 方法与路径 | 用途 | 备注 |
| --- | --- | --- |
| GET /api/health | 健康检查 | 不依赖 LLM 可用性；返回应用和数据库状态。 |
| GET /api/settings | 读取非敏感配置 | 不得返回 API key 原文。 |
| PUT /api/settings | 更新配置 | 密钥更新应采用专门的安全输入语义；响应只返回已配置状态。 |
| POST /api/settings/test-llm | 测试 LLM 配置 | 不泄露密钥；明确区分鉴权、网络和模型错误。 |
| GET /api/jobs/{job_id} | 查询任务状态 | 返回 status、progress、错误摘要、时间戳。 |

## 12.2 课程接口

| 方法与路径 | 用途 |
| --- | --- |
| POST /api/courses | 创建课程。 |
| GET /api/courses | 列出课程。 |
| GET /api/courses/{course_id} | 读取课程详情。 |
| PATCH /api/courses/{course_id} | 更新课程信息。 |
| DELETE /api/courses/{course_id} | 删除课程；必须定义关联数据清理策略。 |
| GET /api/courses/{course_id}/dashboard | 返回材料处理、知识点覆盖、掌握度和待复习摘要。 |

## 12.3 材料接口

| 方法与路径 | 用途 | 返回/行为 |
| --- | --- | --- |
| POST /api/courses/{course_id}/materials | 上传材料 | 返回 document_id 与 job_id。 |
| GET /api/courses/{course_id}/materials | 列出课程材料 | 包含状态、警告和错误码。 |
| GET /api/materials/{material_id} | 材料详情 | 包含页数和解析摘要。 |
| DELETE /api/materials/{material_id} | 删除材料 | 处理文件、页面、片段与来源引用一致性。 |
| GET /api/courses/{course_id}/search?q=... | 搜索课程材料 | 结果包含片段和出处页码。 |
| GET /api/chunks/{chunk_id} | 读取片段 | 返回文本与来源信息。 |

## 12.4 知识框架接口

| 方法与路径 | 用途 |
| --- | --- |
| POST /api/courses/{course_id}/knowledge/build | 启动知识框架构建；返回 job_id；允许提供教材目录参考等参数。 |
| GET /api/courses/{course_id}/knowledge | 读取当前活动框架；返回树结构和来源摘要。 |
| GET /api/knowledge/{knowledge_point_id} | 读取知识点详情；包含来源页码、关系和版本信息。 |
| GET /api/courses/{course_id}/knowledge/versions | 列出框架版本；包含状态与激活时间。 |

## 12.5 测验与作答接口

| 方法与路径 | 用途 | 关键约束 |
| --- | --- | --- |
| POST /api/courses/{course_id}/quiz/generate | 生成测验 | 接受知识点范围、数量、难度和题型约束；返回 job_id 或 quiz_id。 |
| GET /api/quizzes/{quiz_id} | 读取测验 | 提交前隐藏答案键、rubric 和内部解释。 |
| POST /api/quizzes/{quiz_id}/submit | 提交整份测验 | 逐题验证；支持幂等键。 |
| POST /api/questions/{question_id}/answer | 单题作答（可选） | 与整份提交共享一致的判分和幂等规则。 |
| POST /api/questions/{question_id}/variant | 生成变式题 | 提供题目 ID 和变式要求，不向生成模型暴露历史答案正确性。 |
| GET /api/courses/{course_id}/wrongbook | 错题本 | 返回错题、诊断证据和后续复习状态。 |

## 12.6 学习计划接口

| 方法与路径 | 用途 |
| --- | --- |
| POST /api/courses/{course_id}/plan | 生成新计划版本；输入考试日期、每日分钟数、目标分数和范围。 |
| GET /api/courses/{course_id}/plans | 列出计划版本；保留历史计划。 |
| GET /api/plans/{plan_id} | 读取计划详情；包含任务、目标知识点和时长。 |
| PATCH /api/tasks/{task_id} | 更新任务状态或少量可编辑字段；校验状态迁移和所属关系。 |

## 12.7 统一错误格式

```text
{
"error": {
"code": "NO_EXTRACTABLE_TEXT",
"message": "The PDF contains no extractable text.",
"details": {
"document_id": "...",
"pages_without_text": [1, 2, 3]
},
"request_id": "..."
}
}
```

错误响应不得包含 traceback、密钥、完整内部提示词或敏感服务器路径。状态码应区分输入错误、资源不存在、冲突、未配置依赖、临时服务错误和后台任务失败。

# 13. 配置、日志、安全与错误处理

## 13.1 网络绑定

```text
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

默认启动命令必须绑定 127.0.0.1，不得在默认文档中使用 0.0.0.0。当前版本无认证，仅适用于本机可信环境；不得将其描述为可安全直接暴露到局域网或公网。若未来加入反向代理、隧道或远程访问，必须重新评估认证、授权、CSRF、速率限制和文件访问安全。

## 13.2 日志

- 使用结构化日志，至少记录 request_id、job_id、业务对象 ID、错误码和耗时。

- 日志中不得记录 API key、Authorization 头或完整密钥配置。

- 默认避免记录完整学生答案、完整上传文档和完整提示词。

- 错误摘要应足够排查问题，但不包含秘密或无关个人信息。

- 后台任务错误应持久化简明错误码与摘要；完整 traceback 只进入受控的本地日志。

## 13.3 安全与稳健性

- 校验上传大小、文件类型、MIME、页数和解析资源限制。

- 防止路径穿越、任意文件覆盖和通过用户输入指定存储路径。

- LLM_BASE_URL 如果未来可能由不可信用户控制，需要防范 SSRF；V1 应将配置限定为本地可信配置。

- 对 SQL 查询使用 ORM 参数化机制，不把用户输入拼接成 SQL。

- 对外返回的 JSON 使用明确响应 schema，避免 ORM 内部字段被意外序列化。

- 设置合理超时和有限重试；外部 API 永远可能失败。

- 删除课程或材料时执行一致性检查，避免残留任务继续处理已删除资源。

## 13.4 错误分类建议

| 错误码示例 | 场景 | 处理方式 |
| --- | --- | --- |
| INVALID_FILE_TYPE | 文件类型不允许 | 拒绝上传。 |
| FILE_TOO_LARGE | 超过大小限制 | 拒绝上传。 |
| NO_EXTRACTABLE_TEXT | PDF 无可用文本 | 任务失败并保留页码状态；不做 OCR。 |
| PARTIAL_EXTRACTION | 部分页面无文本 | 保留成功页，材料 completed_with_warnings。 |
| LLM_NOT_CONFIGURED | 缺少 LLM 配置 | 返回配置错误，不启动无效调用。 |
| LLM_AUTH_FAILED | LLM 鉴权失败 | 不重试或仅极少重试，隐藏凭据。 |
| LLM_TIMEOUT | LLM 请求超时 | 按任务策略有限重试。 |
| LLM_OUTPUT_INVALID | 模型输出不符合 schema | 有限重试或失败并保存摘要。 |
| RESOURCE_NOT_FOUND | 资源不存在 | 返回 404。 |
| IDEMPOTENCY_CONFLICT | 同一幂等键对应不同请求 | 返回冲突，不重复执行。 |

# 14. 测试策略与验收标准

## 14.1 测试分层

- 单元测试：解析器边界、schema 校验、客观题判分、掌握度更新、选择策略、计划时长约束。

- 集成测试：数据库事务、迁移、文件存储、后台任务领取/重试/恢复和 LLM mock。

- API 测试：状态码、错误格式、答案隔离、幂等性、课程和材料生命周期。

- 端到端测试：从上传材料到生成知识框架、生成测验、提交答案、更新掌握度和生成计划的完整链路。

- LLM 相关测试应使用 mock 或固定 fixture；普通 CI 测试不得依赖真实 API key 或外部网络。

## 14.2 必须覆盖的测试

| 领域 | 必须覆盖的场景 |
| --- | --- |
| PDF | 可提取文本 PDF；整份无文本 PDF；部分页面有文本、部分页面无文本；页码正确；成功页面不因其他页失败而丢失。 |
| PPTX | 多页文本顺序正确；空白幻灯片处理；来源 slide number 保留。 |
| 多选题 | 完全匹配得满分；选项顺序变化仍满分；漏选为 0；多选为 0；选错为 0；非法 ID 拒绝；重复 ID 拒绝；空提交按定义处理。 |
| 答案隔离 | 提交前 quiz API 不返回答案键、rubric 或隐藏解释。 |
| 幂等性 | 重复提交同一答案不创建重复 attempt、不重复更新掌握度；不同请求复用同一幂等键时返回冲突。 |
| 后台任务 | 成功、临时失败重试、超过次数失败、应用重启后 running 任务恢复。 |
| 知识框架 | 新版本成功后原子切换；新版本失败不影响旧活动版本；来源引用校验。 |
| 掌握度 | 正确/错误证据更新方向正确；同一证据不重复应用；多知识点题不盲目传播失败证据。 |
| 计划 | 每日计划时长不超限；新版本不覆盖旧版本；任务目标引用有效。 |
| 安全 | 默认启动绑定 127.0.0.1；日志与响应不泄露密钥；路径穿越输入被拒绝。 |

## 14.3 完成定义

只有在数据库迁移、核心 API、核心服务、必要测试和 README 均可运行的前提下，才能称为某阶段完成。不能仅凭代码文件已创建或接口返回静态假数据就报告完成。所有未实现能力必须在 README 和 API 行为中明确说明。

# 15. Codex 分阶段开发计划

| 阶段 | 目标 | 交付与验收 |
| --- | --- | --- |
| Stage 0 | 项目骨架与规范 | 创建目录、pyproject、配置、日志、错误模型、Alembic、pytest、AGENTS.md、README；全新环境可安装并启动健康检查。 |
| Stage 1 | 数据库与基础 API | 完成模型初版、首个迁移、health、settings、course CRUD；测试迁移与 CRUD。 |
| Stage 2 | 材料存储与解析 | 完成安全上传、PPTX/PDF 解析、逐页状态、分块和课程搜索；覆盖 OCR 禁止规则和部分成功场景。 |
| Stage 3 | 持久化后台任务 | 完成任务状态机、worker、有限重试、崩溃恢复、幂等处理和 job 查询 API。 |
| Stage 4 | LLM 适配与知识框架 | 完成 OpenAI 兼容适配器、结构校验、知识点树、来源映射、关系、版本构建和原子激活。 |
| Stage 5 | 题目生成与测验判分 | 完成生成、去重、测验快照、答案隔离、客观题判分、简答题 rubric 评分和提交幂等。 |
| Stage 6 | 诊断与掌握度 | 完成证据记录、缺口状态、Beta-Binomial 更新、事件审计和复习目标选择。 |
| Stage 7 | 学习计划 | 完成计划版本、任务生成、时长限制、任务状态更新和相关 API。 |
| Stage 8 | 端到端与文档 | 完成端到端测试、错误处理、安全检查、README、配置示例与验收清单。 |

## 15.1 Codex 执行纪律

- 每个阶段开始前先阅读 AGENTS.md 和现有代码，不得覆盖已有实现而不检查。

- 一次聚焦一个阶段，先给出计划，再实现，再运行测试，再汇报结果。

- 不得伪造测试通过、命令输出或外部 API 调用结果。

- 依赖新增必须说明用途，并优先使用成熟、必要的依赖。

- 发现需求歧义时优先遵循本文已明确的约束；真正阻塞时提出一个具体问题，不要擅自更改产品决策。

- 阶段结束时报告：修改文件、迁移、运行命令、测试结果、已知限制、下一阶段建议。

- 不要在默认启动命令或示例中使用 0.0.0.0。

# 附录 A：AGENTS.md 建议内容

```text
# StudyMate Backend Development Rules
## General
- Use Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite, Alembic, and pytest.
- Keep API routes thin. Put business logic in services and persistence queries in repositories.
- Use typed request/response schemas. Do not expose ORM models directly.
- All schema changes must be managed through Alembic migrations.
- Do not claim a feature works unless it is implemented and tested.
- Keep functions focused and add tests for business rules and regressions.
## PDF parsing
- OCR is not supported in the initial release.
- Extract text directly from PDFs only.
- If a page has no extractable text, record `no_extractable_text` and preserve its page number.
- If some pages parse successfully and others do not, preserve successful pages and report partial completion.
- Never fabricate extracted text or claim that OCR was performed.
- Use a stable error code such as `NO_EXTRACTABLE_TEXT` when the document has no usable text.
## Multiple-choice grading
- Objective questions are graded deterministically on the backend.
- Multiple-choice answers receive full credit only when the student's selected option set exactly matches the answer key.
- Option order does not matter.
- Missing, additional, or incorrect options result in zero points.
- Validate option identifiers and reject malformed submissions.
- Do not use an LLM to override objective grading results.
## LLM
- Route all LLM calls through the shared adapter.
- Validate all structured model output before persisting it.
- Treat uploaded materials and student answers as untrusted input.
- Never expose API keys in responses, logs, prompts, or ordinary settings storage.
- Do not provide historical answer keys or correctness labels to question-generation prompts.
- Use bounded retries and explicit timeout handling.
## Knowledge framework and mastery
- Version knowledge frameworks; activate a new version only after validation succeeds.
- Failed framework builds must not replace the active framework.
- Preserve historical quiz snapshots and attempts.
- A wrong answer must not automatically mark every associated knowledge point as weak.
- Mastery updates must be auditable and idempotent.
## Jobs
- Persist jobs in SQLite and implement restart recovery.
- Handlers must be idempotent.
- Do not store secrets or full uploaded files in job payloads.
- Do not claim multi-instance or high-availability support.
## Network and security
- The backend must bind to `127.0.0.1` by default.
- Do not use `0.0.0.0` in default startup commands or documentation.
- The initial release has no authentication and is intended only for local trusted use.
- Do not describe the application as safe for direct LAN or public exposure.
- Validate upload size/type and protect against path traversal.
## Verification
- Add tests for scanned PDFs and partially extractable PDFs.
- Add grading tests for exact match, reordered options, missing options, extra options, and invalid option identifiers.
- Verify that the documented default startup command binds only to `127.0.0.1`.
- Run the relevant test suite before reporting a stage as complete.
```

# 附录 B：开发完成检查清单

- [ ] 项目可在全新 Python 3.12+ 环境中安装、迁移和启动。

- [ ] 默认服务地址为 http://127.0.0.1:8000，未在默认示例中使用 0.0.0.0。

- [ ] Alembic 初始迁移和后续迁移可正常执行。

- [ ] 上传文件名不会直接决定磁盘路径，路径穿越输入被阻止。

- [ ] PPTX/PDF 页码和来源信息被保存。

- [ ] 无文本 PDF 明确失败；部分无文本 PDF 保留可提取页面并报告警告；未实现 OCR。

- [ ] 后台任务具有持久化状态、有限重试和进程重启恢复。

- [ ] 知识框架版本验证失败不会影响当前活动版本。

- [ ] 题目、测验快照、作答、评分和知识点映射可追溯。

- [ ] 提交前 API 不泄露标准答案和 rubric。

- [ ] 多选题仅按选项集合完全匹配判分，不给部分分。

- [ ] 简答题使用明确 rubric，模型输出经过 schema 和范围校验。

- [ ] 同一作答不会重复更新掌握度。

- [ ] 多知识点题目的错误证据不会无差别传播到全部知识点。

- [ ] 掌握度变更有事件记录和算法版本。

- [ ] 复习选择兼顾薄弱点与探索覆盖，选择理由可记录。

- [ ] 计划任务总时长符合每日时间约束，重新生成不覆盖历史版本。

- [ ] 日志、API 响应和普通设置表不泄露 API key。

- [ ] README 包含安装、迁移、启动、配置、测试、限制和常见错误。

- [ ] 核心单元测试、集成测试和端到端测试通过，未通过项有明确说明。

# 最终实施建议

请 Codex 从 Stage 0 开始，逐阶段实现。不要一次性生成一个庞大但未经验证的代码库。先建立可运行骨架与数据库迁移，再逐步完成材料、任务、知识框架、题目、诊断和计划闭环。每个阶段以自动化测试和可复现命令作为完成依据。
