# StudyMate 真实模型验收测试报告与解决方案

- 报告日期：2026-10-20
- 测试环境：Windows + conda `studymate`（Python 3.13）+ Node 24 + SQLite + DeepSeek OpenAI-compatible API
- 前端：`http://127.0.0.1:5173`（Vite dev server）
- 后端：`http://127.0.0.1:8000`（uvicorn，读取 `StudyMate/.env`）
- 测试类型：真实模型 API 全链路、直接 LLM 请求复现、SQLite 数据核查、无头 Chrome 页面核验、前端单测
- 结论：**解析、知识框架、客观题出题/判分/掌握度/错题/复习目标/计划链路通过；简答题出题与简答批改被后端结构化输出校验阻断；大材料知识框架存在平铺结构缺陷。**

---

## 1. 执行摘要

### 1.1 一句话结论

真实模型主链路已经能跑通到「计划任务」；但**简答题出题、简答题批改是 P0 阻断**，根因在模型输出 schema、提示词和归一化层，不在前端。另一个独立问题是**多批次知识框架被合并成一层平铺列表**（旧课程 98 个叶子全部直接挂根节点），前端因此变成超长单列；当前前端已做单行截断，但缺少分组/折叠。

### 1.2 关键结果

| 环节 | 结果 | 证据 |
|---|---|---|
| 上传 PDF + 解析 | 通过 | 3 页，解析 job 2 秒完成 |
| 真实知识框架构建 | 通过 | 5 个叶子，18 秒，v1 active，来源可定位第 1 页 |
| 真实出题（3 种题型，`deepseek-flash`） | 失败 | `LLM_OUTPUT_INVALID`，3 次内部重试仍 ValidationError |
| 真实出题（纯客观题，`deepseek-flash`） | 失败 | 选择题被模型塞入非法 `rubric` |
| 真实出题（纯客观题，`deepseek-chat`） | 通过 | 4 题，6 秒 |
| 提交 + 客观题判分 | 通过 | 0/4（故意选错），`deterministic` |
| 幂等重放 | 通过 | 同一 `submission_id` |
| 掌握度 / 错题本 / 复习目标 | 通过 | 4 / 4 / 3 条 |
| 复习计划 / 任务状态 | 通过 | v1，10 个任务，每天 ≤ 90 分钟，pending→completed |
| **简答题出题** | **失败** | rubric criteria 字段不匹配，3 次重试失败 |
| **简答题真实批改** | **失败** | 模型返回的 grading 字段与 schema 完全不同；另有总分/分项精确相等校验 |
| 前端失败兜底 | 通过 | 「模型输出异常，可重试」显示正确，无需改前端 |
| 知识框架平铺（旧课程） | 问题 | 1 个根 + 98 个一级叶子，96/2 来自两份 PDF，`section_label` 全空 |
| 前端单测 | 通过 | 13 个文件、51 个用例全部通过 |

### 1.3 优先级建议

| 优先级 | 事项 | 归属 |
|---|---|---|
| P0 | 出题 rubric schema / 归一化 / 提示词修复 | 后端 |
| P0 | 简答批改 schema / 归一化 / 总分一致性修复 | 后端 |
| P1 | 多批次知识框架按文档保留层级 | 后端 |
| P1 | 知识页分组、折叠、计数、分批展开、平铺兜底 | 前端 |
| P1 | `llm_call` 可观测记录 | 后端 |
| P1 | 重试语义：瞬时错误 vs schema 错误、job 外层重试 | 后端 |
| P2 | 模型兼容矩阵、fallback 死代码、计划任务标题本地化 | 后端/内容 |

---

## 2. 测试范围、环境与数据

### 2.1 环境与配置

- 后端配置：`LLM_BASE_URL=https://api.deepseek.com`，`LLM_API_KEY` 已配置（本文不记录密钥），`LLM_TIMEOUT_SECONDS=60`，`LLM_MAX_RETRIES=2`。
- 测试过程中模型从 `deepseek-flash` 切换为 `deepseek-chat`：
  - `deepseek-flash` 可以完成知识框架构建；
  - 但它在客观题里也会给每题附加非法 `rubric`，导致出题失败；
  - `deepseek-chat` 对纯客观题会正确返回 `"rubric": null`，因此客观题链路可用。
- `response_format={"type":"json_object"}` 已确认由适配器实际发送（`app/llm/openai_compatible.py:100-111`），不是本次失败原因。
- 适配器内部最多重试 3 轮（`LLM_MAX_RETRIES=2`），每轮超时 60 秒；job 层 `max_attempts=2`，但失败 job 的 `attempts` 仍为 1（外层重试未发生）。

### 2.2 测试数据

**新验收课程**：

- 名称：`真实模型验收 10-20 11:09`
- ID：`96d00dc9-9c7a-49df-bec6-0b22219563d5`
- 材料：`f1-sample.pdf`，3 页（第 2 页为扫描页/无文本）
- 知识框架：v1 active，5 个叶子
- 测验：4 道客观题（2 单选 + 2 多选），已提交
- 掌握度：4 条（均 0.40，各 1 次证据）
- 错题本：4 条
- 复习目标：3 个
- 计划：v1 active，10 个任务，每天 ≤ 90 分钟

**旧课程（平铺框架问题所在）**：

- 名称：`计算机网络·运输层`
- ID：`204637ae-a9a0-4708-832c-97a33351d133`
- 材料：`运输层课件示例.pdf`（3.8KB）+ `ch4_MAC子层_v2.0(5).pdf`（8.5MB）
- 活动框架：v2 `61e2b0ff-7cec-44e0-aaf7-f99fccc8a57d`
- 节点：1 个根（level 0）+ 98 个叶子（level 1），全部直接挂在根下
- 来源分布：`ch4_MAC子层_v2.0(5).pdf` → 96 个知识点；`运输层课件示例.pdf` → 2 个
- `section_label`：99/99 为空
- 叶子标题长度：平均 78.3 字，最长 80 字，最短 9 字

> 说明：本次验收在测试库中进行，没有删除测试课程；旧课程仍保留两个 open 测验（`b60025c8-...`、`1d491e1f-...`）。所有操作均为本地测试数据。

### 2.3 测试方法

1. 用真实后端 API 跑完整链路脚本：建课 → multipart 上传 → 轮询解析 job → 构建知识框架 → 出题 → 拉题 → 提交 → 幂等重放 → 掌握度/错题/复习目标 → 计划 → 任务状态。
2. 对失败路径直接构造与后端相同的 LLM payload，调用 DeepSeek，保存原始响应，再用后端 Pydantic 模型复现校验错误。
3. 查询 SQLite 的 `jobs`、`quizzes`、`knowledge_framework_versions`、`knowledge_node_versions`、`knowledge_sources`、`student_gap_states`、`study_task_targets` 等表，核对时间线与数据形态。
4. 用无头 Chrome 打开真实页面并截图，核对前端实际渲染。
5. 运行前端全量单测与 `tsc --noEmit`。

### 2.4 复现产物

- `C:\Users\86159\Desktop\hackathon\.tmp\real_e2e_objective_result.json`：客观题全链路结果
- `.tmp/short_answer_result.json`：未生成——脚本在 502 处退出；失败响应见 `.tmp/grading_raw.json` 和 3.3.2
- `C:\Users\86159\Desktop\hackathon\.tmp\quiz_raw.json`：出题原始响应
- `C:\Users\86159\Desktop\hackathon\.tmp\grading_raw.json`：批改原始响应
- 截图：`real-dashboard.png`、`real-knowledge.png`、`real-review.png`、`real-plan.png`、`old-knowledge.png`（均在 `.tmp/`）

---

## 3. 测试结果

### 3.1 结果总表

| # | 场景 | 结果 | 说明 |
|---|---|---|---|
| T1 | 健康检查 / 设置 | 通过 | `llm_base_url=https://api.deepseek.com`，`llm_auth_configured=true` |
| T2 | 上传 + 解析 | 通过 | 3 页，`job` 2 秒完成 |
| T3 | 知识框架构建（新课程） | 通过 | 5 个叶子，18 秒，来源第 1 页 |
| T4 | 出题：3 种题型（flash） | 失败 | rubric criteria 字段不匹配；3 次内部重试失败 |
| T5 | 出题：纯客观题（flash） | 失败 | 选择题被塞入非法 rubric（criteria 为字符串数组） |
| T6 | 出题：纯客观题（chat） | 通过 | 4 题，6 秒 |
| T7 | 提交 + 客观题判分 | 通过 | 0/4，`deterministic` |
| T8 | 幂等重放 | 通过 | 同一 `submission_id` |
| T9 | 掌握度 / 错题本 / 复习目标 | 通过 | 4 / 4 / 3 |
| T10 | 计划 / 任务状态 | 通过 | v1，10 任务，≤90 分钟/天，completed |
| T11 | 简答题出题 | **失败** | 与 T4 同一次 job 的简答维度：`LLM_OUTPUT_INVALID`，3 次重试失败 |
| T12 | 简答题批改 | **失败** | 502；字段不匹配 + 总分校验 |
| T13 | 前端失败兜底 | 通过 | 「模型输出异常，可重试」 |
| T14 | 前端单测 / 类型检查 | 通过 | 51 个用例，`tsc --noEmit` 通过 |
| T15 | 旧课程知识框架平铺 | 问题 | 98 个一级叶子，`section_label` 全空 |
| T16 | 知识页长列表 | 问题 | 98 行平铺，标题单行截断，无分组/折叠 |

### 3.2 通过项详情

- **T2 解析**：`f1-sample.pdf` 3 页，第 2 页无文本，解析状态如实记录；这是预期行为。
- **T3 知识框架**：真实模型 18 秒生成 5 个叶子，标题、内容、来源页码均落库；前端知识页可展开来源原文。
- **T6 客观题出题**：`deepseek-chat` 6 秒生成 4 题；题干和选项均为中文，覆盖慢启动、拥塞避免、GBN/SR、滑动窗口。
- **T7/T8 判分与幂等**：4 题全错（故意选择第一个/全选），得分 0/4；同 key 同答案重放返回同一 submission，未重复扣分。
- **T9 掌握度**：4 个节点均更新为 0.40（1 次错误证据）；错题本 4 条；复习目标 3 个。
- **T10 计划**：10 个任务，按天分组，单日 90 分钟；一个任务从 pending 迁移到 completed 成功。
- **T13 前端兜底**：出题失败时 `Quiz.tsx:561-569` 显示 `ErrorNotice`，`errors.ts:32` 将 `LLM_OUTPUT_INVALID` 映射为「模型输出异常，可重试」；前端行为正确。

### 3.3 失败项详情

#### 3.3.1 出题失败：简答题 rubric schema 不匹配

**时间线（本地时间，库内为 UTC）**：

| 时间 | job | 模型 | 题型 | 结果 | 耗时 |
|---|---|---|---|---|---|
| 11:10:08 | `f037eb66-...` | flash | 单选+多选+简答 | failed | 64s |
| 11:12:46 | `8d55bd7e-...` | flash | 纯客观 | failed | 58s |
| 11:15:15 | `03a93d5f-...` | chat | 纯客观 | **succeeded** | 6s |
| 11:19:37 | `6a7dfb58-...` | chat | 纯客观（另一个 agent 从 UI 重试） | failed | 37s |

- 03:15 的成功 job 就是新课程 4 条掌握度的来源；03:19 的失败是另一个 agent 在浏览器里点「重新出题」触发的，不是本轮 API 脚本。
- 每次失败 job 的 `attempts=1`、`max_attempts=2`，状态直接 failed；适配器内部已经重试 3 轮，所以单次失败耗时 37–64 秒。

**模型原始输出（短答 rubric）**：

```json
{
  "question_type": "short_answer",
  "rubric": {
    "max_points": 5,
    "criteria": [
      {"description": "正确说明超时后 ssthresh 减半并重新慢启动", "points": 2},
      {"description": "正确说明 3 个重复 ACK 触发快重传与快恢复", "points": 2},
      {"description": "能对比超时与快重传的恢复方式", "points": 1}
    ]
  }
}
```

**后端校验错误**：

```text
questions.2.rubric.criteria.0.criterion_id: missing
questions.2.rubric.criteria.0.max_points: missing
questions.2.rubric.criteria.0.points: extra_forbidden
...（3 个 criteria 均相同）
```

**纯客观题 + flash 的额外问题**：

```json
{
  "question_type": "single_choice",
  "rubric": {"criteria": ["选择 A，说明一个 RTT 内窗口近似翻倍"], "max_points": 1}
}
```

`criteria` 是字符串数组，后端要求 `list[RubricCriterionCandidate]`，直接类型错误。`deepseek-chat` 对纯客观题返回 `"rubric": null`，所以 T6 能过。

**根因**：

1. 出题 prompt 的 `response_schema` 只列出了 `rubric` 字段名，没有给出 criteria 的字段结构，也没有说明「选择题必须 `rubric: null`、简答题才给 rubric」。模型只能猜。
2. 适配器的 `_normalize_quiz_payload` 只做了 `answer→answer_key_option_ids`、`choices→options` 等白名单改名，没有处理 rubric criteria 的 `points`/`point` 别名，也没有为缺失的 `criterion_id` 生成稳定 ID。
3. `QuizQuestionCandidate` 使用 `extra="forbid"`，`points` 这种常见别名会直接变成整卷 ValidationError。
4. `deepseek-flash` 的推理行为更倾向于给每道题都补 rubric；`deepseek-chat` 更符合「选择题 rubric 为 null」的预期，但短答题仍然失败。

#### 3.3.2 简答批改失败：字段完全不同 + 总分精确相等

**现象**：提交旧课程的 open 测验 `b60025c8-...`（含 1 道简答题），后端返回：

```json
{
  "error": {
    "code": "LLM_OUTPUT_INVALID",
    "message": "Short-answer grading score did not match the rubric breakdown.",
    "status_code": 502,
    "request_id": "5311d2da-a8fe-41ed-b0bf-ae1c44a0be1b"
  }
}
```

测验仍保持 open，未落库，符合失败不污染数据的设计。

**直接复现的模型原始输出**：

```json
{
  "points_awarded": 1.0,
  "max_points": 2.0,
  "criteria_results": [
    {
      "criterion_id": "mentions_topic",
      "points_awarded": 1.0,
      "max_points": 1.0,
      "met": true,
      "feedback": "Mentions 25G and 100G Ethernet concepts."
    },
    {
      "criterion_id": "mentions_material_support",
      "points_awarded": 0.0,
      "max_points": 1.0,
      "met": false,
      "feedback": "Does not mention IEEE 802.3by, the 2014 release, ..."
    }
  ],
  "overall_feedback": "Names the topic but omits the specific standard ..."
}
```

**后端期望**：

```json
{
  "score": 1.0,
  "criterion_scores": [
    {"criterion_id": "mentions_topic", "awarded_points": 1.0, "rationale": "..."}
  ],
  "feedback": "...",
  "rationale": "..."
}
```

- 字段名完全不同：`points_awarded` vs `awarded_points`，`criteria_results` vs `criterion_scores`，`overall_feedback` vs `feedback`。
- 适配器只对 quiz/knowledge 做归一化，没有 grading 归一化（`app/llm/openai_compatible.py:181-247`）。
- 另一条路径虽然 schema 通过了，但 `quiz_service.py:1106-1111` 要求模型给的 `score` 与所有 `criterion_scores.awarded_points` 之和**精确相等**（误差 1e-6）；LLM 常见的整体分与分项分不完全一致，就会 502。
- 批改 prompt（`app/llm/prompts/short_answer_grading.py`）只有 4 条规则，没有给出 JSON schema、字段名、criterion_id 必须来自 rubric、总分等于分项之和等约束。

#### 3.3.3 知识框架平铺：多批次合并结构丢失

**数据事实（旧课程活动框架 v2）**：

```text
总节点 99
  1 个根节点（level 0, is_leaf=false）
  98 个叶子（level 1, is_leaf=true），全部 parent = 根节点
  96 个来自 ch4_MAC子层_v2.0(5).pdf
   2 个来自 运输层课件示例.pdf
section_label 空：99 / 99
叶子标题长度：平均 78.3 字，最长 80 字
```

> 另一个 agent 描述为「98 个节点全在 depth 0」；更精确的说法是「1 个根在 depth 0，98 个叶子全部在 depth 1，直接挂根」。问题本质相同：没有文档层/章节层。

**代码路径**：

- `knowledge_service.py:604-664` `_merge_batch_candidates` 对每个候选节点调用 `_collect_source_backed_topics`，把所有层级的 topic 展平进 `merged_topics`。
- 新建的 topic 一律 `children=[]`，只保留根 → topic 一层。
- 去重使用全局 `seen_titles`，跨文档同名知识点会被误删。
- `_infer_section_label`（`knowledge_service.py:696`）已存在，但没有任何调用点；`section_label` 只做清洗，不推断。
- 每个批次内部的「文档→知识点」结构在合并阶段被丢弃。另一个 agent 判断「mock 提取器每个批次本来产出文档→知识点两层结构，是被合并阶段拍平的」与代码路径一致；该合并逻辑与模型无关，对真实 LLM 同样成立。

**前端放大**：

- 当前 `Knowledge.tsx:129` 已经有 `truncate` + `title={node.title}`，实测是**单行省略号**，不是另一个 agent 描述的「80 字标题多行换行」；如果看到多行，可能是旧构建/旧缓存。
- 但 98 行仍然全部渲染在 340px 左栏里，默认展开根节点和所有叶子（`Knowledge.tsx:283-297` 的 `depth <= 1` 逻辑），形成数屏长的单列；标题被截到约 20 字，必须悬停才能看全，且没有文档分组、计数、折叠。
- 截图 `.tmp/old-knowledge.png` 可见：98 行、单行省略、无层级。

---

## 4. 缺陷与根因汇总

| 编号 | 严重度 | 缺陷 | 根因 | 影响 |
|---|---|---|---|---|
| D1 | P0 | 简答题出题失败 | prompt 未给 rubric schema；归一化未处理 `points`/`criterion_id`；`extra=forbid` | 3 种题型无法出题；纯客观题在 flash 下也失败 |
| D2 | P0 | 简答批改失败 | grading prompt 无 schema；无 grading 归一化；总分要求精确相等 | 简答题无法提交/批改；实测 502（瞬时错误时可能 503） |
| D3 | P1 | 知识框架平铺 | `_merge_batch_candidates` 展平；全局去重；`section_label` 不推断 | 98 行单列，无文档/章节层级；大纲不可读 |
| D4 | P1 | 缺少 LLM 调用可观测 | 无 `llm_call` 表；job.error_summary 只有一句话 | 失败只能靠直接请求复现，无法从库中定位字段 |
| D5 | P1 | 重试语义不合理 | 内层 3×60s；job 外层 attempts=1 就终判；不区分瞬时/schema | 单次失败 37–64s；无效重试消耗 token |
| D6 | P2 | 模型兼容性未收口 | flash 给客观题加 rubric；chat 短答 rubric 仍错 | 换模型才能绕过部分问题，不是真正修复 |
| D7 | P2 | fallback 死代码 | `_is_llm_parse_error` 比较精确消息，实际消息带 `(ValidationError) after 3 attempt(s)` | 已有 deterministic fallback 永远不会触发 |
| D8 | P2 | 计划任务标题英文模板 | 计划生成使用 `Review/Practice <title>` 模板 | 中文界面出现英文任务名，影响演示观感 |

### 4.1 对另一个 agent 根因假设的核对

| 假设 | 核对结果 | 证据 |
|---|---|---|
| `extra="forbid"` 是最大嫌疑 | **部分成立，但不是唯一根因** | `points`/`point` 额外字段确实触发 `extra_forbidden`；但即使忽略额外字段，仍缺 `criterion_id`/`max_points`，且 `criteria` 可能是字符串数组，仍会类型错误 |
| 必填项苛刻（difficulty、knowledge_mappings、weight、rubric） | 成立 | 短答 rubric 的 `criterion_id`/`max_points` 缺失；knowledge_mappings 必须逐字符匹配 |
| 反馈重试信息量不够 | 成立 | `_validation_retry_instruction` 只回传字段路径+错误类型；3 次重试仍失败 |
| 没有 `llm_call` 日志表 | 成立 | 当前 SQLite 表清单无 `llm_call`；job 只存一句 error_summary |
| 知识框架 98 节点平铺 | 成立（措辞需修正） | 1 根 + 98 个 level-1 叶子，96/2 两份文档，section_label 全空 |
| 前端 80 字标题多行换行 | **不成立（当前工作区）** | `Knowledge.tsx:129` 已有 `truncate`；实测单行省略号。问题是 98 行平铺 + 截断，不是多行 |
| 前端失败兜底正确 | 成立 | `Quiz.tsx:561-569` + `errors.ts:32`；另一个 agent 在浏览器复现到「模型输出异常，可重试」，代码路径一致 |
| job `max_attempts` 没被用上 | 成立 | quiz job `attempts=1, max_attempts=2` 即 failed；适配器内部已重试 3 轮 |
| `response_format` 可能没落地 | **不成立** | `openai_compatible.py:103` 明确发送 `{"type":"json_object"}` |
| 重建会产生孤儿掌握度 | 成立 | mastery/plan targets 按 `knowledge_node_id` 存；分组改变 stable_key path，重建会生成新 node id |

---

## 5. 解决方案

### 5.1 P0：出题结构化输出修复

#### 5.1.1 提示词：给出完整示例和条件约束

在 `app/llm/prompts/quiz_generation.py` 的 `SYSTEM_PROMPT` 和 `_build_generation_payload` 的 `response_schema` 中增加：

- 选择题：`rubric` 必须为 `null`；`options` 至少 2 个；`answer_key_option_ids` 必须是 options 的子集。
- 简答题：`options`、`answer_key_option_ids` 为 `[]`；`rubric` 必须是对象，包含 `max_points` 和 `criteria`；每个 criterion 必须包含 `criterion_id`、`description`、`max_points`、`acceptable_phrases`。
- 提供一份完整示例 JSON（单选、多选、简答各一个），比字段名清单更有效。
- 明确 `knowledge_node_id` 必须逐字符复制提供的 ID；`weight` 在 (0,1]；`relation_role` 用 `primary`。
- 明确 `difficulty` 用请求里的值（当前只传 `"low"`）。

示例（简答）：

```json
{
  "question_type": "short_answer",
  "stem": "...",
  "options": [],
  "answer_key_option_ids": [],
  "reference_answer": "...",
  "rubric": {
    "max_points": 5,
    "criteria": [
      {
        "criterion_id": "c1",
        "description": "正确说明慢启动阶段 cwnd 每 RTT 翻倍",
        "max_points": 2,
        "acceptable_phrases": ["每个 RTT 翻倍", "指数增长"]
      }
    ]
  },
  "explanation": "...",
  "difficulty": "low",
  "knowledge_mappings": [
    {"knowledge_node_id": "<提供的 id>", "relation_role": "primary", "weight": 1.0}
  ],
  "source_chunk_ids": ["<提供的 chunk id>"],
  "source_page_numbers": [1]
}
```

#### 5.1.2 归一化：兼容常见别名，不发明评分事实

在 `_normalize_quiz_payload` 中增加：

- rubric：
  - `points` / `point` / `score` → `max_points`；
  - 缺 `criterion_id` 时生成 `c{index}`（稳定、可复现）；
  - `criteria` 是字符串数组时，转成 `{criterion_id, description, max_points: 1}`；
  - 选择题出现 rubric 时置 `null`（选择题不参与 rubric 评分）。
- `options: null` → `[]`；`answer_key_option_ids: null` → `[]`。
- `difficulty` 缺失/为空 → 使用请求的 difficulty。
- `question_type` 别名：`single` / `multiple` / `short`，以及中文 `单选` / `多选` / `简答`，统一映射到 `single_choice` / `multiple_choice` / `short_answer`。
- `knowledge_mappings`：
  - 字符串数组 → 每项 `{knowledge_node_id: str, relation_role: "primary", weight: 1.0}`；
  - 缺 `relation_role` → `primary`；缺 `weight` → `1.0`；
  - 校验 ID 必须属于 supplied nodes；无效 ID 不静默替换，记录并重试该题/整卷。
- `source_page_numbers` 字符串 → 整数数组；`source_chunk_ids` 字符串 → 数组。
- 常见“贴心”额外键（`answer`、`analysis`、`topic`、`points_awarded` 等）：先按白名单改名，剩余未知键剥离并记录；只对 LLM 响应模型放宽 `extra`（`ignore` 或先 strip），领域/API 模型继续保持 `forbid`。

**不要**按选项序号自动回退 answer key：客观题判分依赖正确答案，猜答案会造成错误判分。另一个 agent 建议「按序号回退或丢该题保整卷」；本报告只采纳「丢该题/重试该题」，不采纳「按序号回退」。答案 key 与 options 对不齐时，应将该题判为不可用并重试生成，或整卷失败并记录原因。

#### 5.1.3 校验策略

- 先做结构归一化，再 `model_validate`；不要直接对原始输出 `model_validate`。
- 对每题做语义校验：
  - 单选恰好 1 个正确答案，且属于 options；
  - 多选至少 2 个正确答案，且都属于 options；
  - 简答 rubric 的 criteria 非空、max_points > 0、总分等于题目 max_score（可由后端计算）。
- 单题不合格时，只重试该题或丢弃该题并补题；不要因为一道题让整卷失败（除非题量不足）。
- 记录每次原始输出和校验错误，便于排查。

#### 5.1.4 测试

- 用本次真实原始响应做 fixture：
  - `rubric.criteria[*].points`；
  - `criteria` 为字符串数组；
  - `options: null`；
  - `difficulty` 缺失；
  - `knowledge_mappings` 为字符串数组。
- 单测：归一化后能通过 `QuizGenerationCandidate`。
- 集成：fake LLM 返回上述 payload，job 应成功或只重试单题。
- 回归：3 种题型 + 纯客观题 + flash/chat 两种模型。

### 5.2 P0：简答批改修复

#### 5.2.1 提示词

在 `short_answer_grading.py` 中给出完整 schema 和示例：

```json
{
  "score": 1.0,
  "criterion_scores": [
    {"criterion_id": "mentions_topic", "awarded_points": 1.0, "rationale": "..."}
  ],
  "feedback": "...",
  "rationale": "..."
}
```

明确：

- `criterion_id` 必须来自输入 rubric，不能发明；
- 每个 `awarded_points` 在 `[0, criterion.max_points]`；
- `score` 必须等于所有 `awarded_points` 之和；
- `feedback` 简短具体，`rationale` 说明总分依据。

#### 5.2.2 归一化

在适配器中增加 grading 归一化：

- `points_awarded` → `awarded_points`；
- `criteria_results` → `criterion_scores`；
- `overall_feedback` → `feedback`；
- `reason` / `explanation` → `rationale`；
- 缺 `score` 时由后端按分项求和；
- 缺 `criterion_id` 时按 rubric 顺序映射（仅当数量一致且顺序可信）；否则报错并记录；
- `max_points` 额外字段剥离。

#### 5.2.3 分数一致性

- 后端以 `sum(criterion_scores.awarded_points)` 作为最终分数，而不是信任模型给的 `score`；
- 如果模型 `score` 与分项和不一致，记录 warning 并以分项和为准；
- 对 `awarded_points` 做 clamp 到 `[0, criterion.max_points]`，总分 clamp 到 `[0, max_score]`；
- 只有无法映射 criterion、或某项超限且无法修复时，才返回 502；
- 错误信息要包含 criterion id、模型分数、分项和，便于排查。

#### 5.2.4 测试

- fixture：`points_awarded` / `criteria_results` / `overall_feedback` 原始输出；
- 单测：归一化后通过 `ShortAnswerGradingCandidate`；总分由分项和覆盖；
- 集成：提交含简答的 quiz，返回 200，`grading_method=rubric_llm`，分数与分项一致；
- 回归：模型给的总分与分项和不一致时，不 502，按分项和落库并记录 warning。

### 5.3 P1：知识框架层级修复

#### 5.3.1 后端合并算法

在 `_merge_batch_candidates` 中：

1. 收集 topic 时记录 `topic.sources[0].document_id`。
2. 按文档分桶：`dict[document_id, list[topic]]`。
3. 每个文档桶内：
   - 用 `_normalize_title_key` 做文档内去重（跨文档同名保留）；
   - `_is_quality_knowledge_topic` 过滤；
   - 按最小来源页码排序；
   - `section_label` 为空时调用 `_infer_section_label(title + " " + content)`，失败则留空。
4. 每个文档生成一个父节点：
   - `title = document.filename`；
   - `children = 该文档 topics`；
   - `sources = []`（父节点是分组，不直接挂原文；叶子仍有 sources）；
   - `ref = f"doc_{document.id}"`。
5. 根节点仍为课程名；relations 改为文档内相邻 topic 的 `related`，跨文档不强行连边（或保留但标注低置信）。
6. 保持 `KnowledgeFrameworkCandidate` 的树形结构，`_persist_candidate_node` 会自动计算 level/is_leaf。

注意：`_persist_candidate_node` 对「叶子且无 sources」会报错；文档父节点有 children，不会触发。叶子必须保留 sources。

已知取舍：本方案会把 LLM 输出的更深层级压到「文档 → 知识点」两层；如果将来要保留章节/小节层级，应改为收集子树，而不是只收集 source-backed topics。本次先解决 98 个叶子平铺的问题。

需要补一条后端测试：多批次、多文档合并后，输出必须是「根 → 文档父节点 → 知识点」三层，且 96/2 分组正确、叶子来源不丢。

#### 5.3.2 稳定 ID 与掌握度连续性

- 当前 `_persist_candidate_node` 的 `stable_key` 由 `path`（根标题 + 父标题 + 标题）组成；插入文档父节点会改变叶子的 stable_key，导致重建后 `knowledge_nodes` 新建、mastery/plan targets 指向旧 ID。
- 若希望保留掌握度：
  - 为叶子使用独立于树位置的 `stable_key`：`course_id + 标题 + 主来源 document_id + 首个 page_number`，或内容哈希；
  - 或增加 `node_identity` 表做旧→新 ID 映射；
  - 或在重建时迁移 `student_gap_states` / `study_task_targets` / `knowledge_gaps`。
- 若只是演示库：可接受孤儿，重建后重新做一次小测验即可。

#### 5.3.3 前端知识页

当前状态：`truncate` 已有，标题单行省略；缺 grouping/collapse/counts。

建议实现：

- **分组**：
  - 后端返回 document 父节点后，左栏显示「📄 文件名 · N 个知识点 · 已测 M」分组头（粗体）；
  - 默认只展开根，document 组默认收起；
  - 组头可点击展开/折叠，箭头 + `aria-expanded`；
  - 组头显示 `N` / `已测 M` 徽标。
- **全部展开/全部收起**：卡头按钮，操作所有组和根。
- **叶子行**：
  - 小一号字号，缩进参考线；
  - 标题继续单行 `truncate` + `title` tooltip；
  - 行内显示 `P{page_number}`（等宽字体），来自 `sources[0]`；
  - 点击行仍选中右侧详情。
- **分批展开**：组内默认显示前 20 条，底部「展开其余 N 条 ▾」；避免 96 条一次性撑开。
- **平铺兜底**：
  - 检测 `tree.length === 1 && tree[0].children.every(isLeaf)`；
  - 按 `sources[0].document_id` 现场分组；filename 用 `sources[0].filename`；
  - 没有 source 的归入「未标注来源」；
  - 合成组只影响展示，不改变后端数据；选中/掌握度仍按叶子 ID 查找；
  - 后端分组上线后，此兜底自然闲置，保留兼容旧框架。
- **性能**：98 行不需要虚拟化；如果未来 >500 行，再考虑 `react-window` 或分页。
- **测试**：
  - 现有多层 fixture：默认只展开根/文档层；
  - 分组计数、已测计数；
  - 全部展开/收起；
  - 组内 20 条截断 + 展开其余；
  - 平铺兜底分组；
  - 标题 truncate/tooltip、来源页码；
  - 选中详情和掌握度高亮不回归。

#### 5.3.4 数据重建与验证

1. 备份 `StudyMate/data/studymate.db`。
2. 重建旧课程框架（UI「重新构建」或 `POST /api/courses/{id}/knowledge/build`）。
3. 检查新树：根 → 2 个文档父节点（96 / 2）→ 叶子；`section_label` 尽量非空；叶子仍有来源。
4. 检查副作用：
   - 旧课程当前 `student_gap_states` 有 2 条（旧节点），新验收课程有 4 条；重建后这些旧节点 ID 不再对应新树，掌握度列表会出现孤儿/未测验观感；
   - 旧 `knowledge_gaps` 按旧 `node_version_id`，错题本可能为空或只显示旧数据；
   - `study_task_targets` 指向旧 `knowledge_node_id`，旧计划任务仍存在但不再对应新树；
   - 需要重新做一次小测验并重新生成计划。
5. 如果要保留掌握度：按 5.3.2 做 stable key 迁移，或在重建前导出/重建后映射。
6. 验收：旧课程知识页从 98 行平铺变为 2 个可折叠文档组；展开后每组的叶子可分页/分批；标题可读；来源页码可见。

如果暂时不想丢现状，可以先只上前端「平铺兜底分组」，不重建后端框架；等前端兜底验收通过、后端稳定 ID 方案确定后再重建。这样不会产生孤儿掌握度，但旧框架仍然是平铺数据。

### 5.4 P1：LLM 调用可观测

另一个 agent 指出架构 v2.2 承诺过 `llm_call` 日志表，但当前库里没有；本次核查确认 SQLite 表清单中确实没有该表。这是本次失败定位困难的直接原因之一。

新增 `llm_calls` 表（或等价日志）：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `job_id` / `quiz_id` / `course_id` | 关联 |
| `request_id` | 请求编号，和错误信封一致 |
| `model` / `provider` / `prompt_version` | 模型与提示词版本 |
| `attempt` | 第几轮重试 |
| `status` | success / invalid / http_error / timeout |
| `http_status` | 上游 HTTP 状态 |
| `latency_ms` | 耗时 |
| `finish_reason` | stop / length / ... |
| `prompt_tokens` / `completion_tokens` | 用量 |
| `raw_response` | 截断后的原始内容（如 8KB） |
| `validation_errors` | 完整 ValidationError 列表（loc/type/msg） |
| `created_at` | 时间 |

要求：

- 适配器在每次请求后写一条；失败也写。
- 脱敏：不记录 API Key、Authorization、完整学生答案/课件原文（可截断/哈希）。
- 保留策略：按天/大小清理，避免 SQLite 膨胀。
- 可选：`GET /api/jobs/{id}` 增加 `llm_calls` 摘要，前端错误详情可展开；但不要把原始响应暴露给浏览器。
- 验收：本次失败重跑一次，能在 `llm_calls` 直接看到 `rubric.criteria.0.criterion_id missing`，不需要再写诊断脚本。

### 5.5 P1：重试、超时与模型策略

- **区分错误类型**：
  - 网络/超时/429/5xx：适配器内重试，指数退避 + jitter；
  - schema/ValidationError：最多 1 次“修复重试”，带完整错误列表和示例；仍失败则快速失败，不做 3×60s；
  - 鉴权 401/403：不重试。
- **job 外层重试**：
  - 当前 quiz job `max_attempts=2`，`attempts=1` 即 failed；应让瞬时错误递增 attempts 并重试，schema 错误可标记 terminal 或有限重试；
  - 另一个 agent 提到 `max_attempts=3`，本次 quiz job 实际是 2；无论 2 还是 3，结论相同：外层重试没有被用上；
  - 不要让适配器内层 3 次 × job 外层 2 次造成 6 次重复调用。
- **超时**：
  - 每次 60s × 3 轮，单题失败拖 1 分钟；建议单次 30–45s，或总预算 90s；
  - 对大模型 JSON 输出设置合理 `max_tokens`（如 4096–8192），检查 `finish_reason == "length"`；不要用 `max_tokens=1` 做连通性测试（会得到空 content + reasoning）。
- **temperature**：适配器当前已固定 `temperature=0`，没有继续下调空间；重试时应改为「更小的 schema + 更明确的示例 + 完整错误列表」，而不是重复同一 prompt。
- **模型矩阵**：
  - `deepseek-chat`：客观题通过；短答出题/批改待后端修复；
  - `deepseek-flash`：知识框架通过；客观题因 rubric 附加失败；修复归一化后应重测；
  - 在 README/设置页注明推荐模型与已知限制。
- **死代码**：
  - `_is_llm_parse_error` 的精确消息比较与适配器实际消息不一致；修复或删除，避免误以为有 fallback。
  - 如果保留 deterministic fallback，明确它只用于“模型完全不可用/解析失败”的演示兜底，不能静默替代真实判分。

### 5.6 P2：其他改进

- 计划任务标题 `Review TCP慢启动` / `Practice ...` 是英文模板；建议用知识点标题 + 中文动作（「复习」「练习」），或至少本地化。
- 知识页统计 `framework.data.nodes.length` 是顶层节点数；分组后应显示叶子总数，避免「2 个知识点」的误解。
- `section_label` 推断要加中文测试：`第3章`、`4.1`、`Chapter 4`、`IEEE 802.3by`（避免把标准号误当章节号）。
- 错误信封已经包含 `request_id`；前端错误详情可展示并支持复制，便于和后端日志对齐（设计参考已有 `request_id` 方案）。

---

## 6. 实施顺序与工作量

| 阶段 | 内容 | 预估 |
|---|---|---|
| 0 | 配置切到 `deepseek-chat`（临时）；出题 prompt + rubric 归一化 + fixtures | 4–6h |
| 0 | 简答批改 prompt + 归一化 + 总分重算 + tests | 3–5h |
| 1 | `llm_calls` 表/日志 + 失败详情 | 3–4h |
| 1 | 知识树按文档分组 + 单测 + 稳定 key 评估 | 4–6h |
| 1 | 前端知识页分组/折叠/计数/分批/兜底 + tests | 6–8h |
| 1 | 数据重建/迁移演练 | 2–4h（演示库）/ 1–2d（真实数据） |
| 2 | 重试语义、超时、模型矩阵、计划标题本地化 | 3–5h |

总计约 3–4 个开发日（后端 + 前端并行可压缩到 2 天左右）。

另一个 agent 的粗略估计是 A1+B 约 2 小时、A2/C 约 1.5 小时；本报告的估计更保守，因为包含了真实模型回归、归一化 fixture、前端知识页改造和数据迁移演练。实际排期建议以本报告的 3–4 天为准，若只做 P0 修复可压缩到 1 天。

---

## 7. 验收清单

### 7.1 后端

- [ ] 3 种题型真实出题连续 3 次成功（flash/chat 至少各 1 次）。
- [ ] 纯客观题在 flash 下也能成功（或明确只支持 chat 并写入配置校验）。
- [ ] 简答题 rubric 的 `criterion_id`/`max_points` 正确落库。
- [ ] 简答批改返回 200，`grading_method=rubric_llm`，分数等于分项和。
- [ ] 模型总分与分项和不一致时不 502，按分项和落库并记 warning。
- [ ] `llm_calls` 能查到失败请求的原始响应和 ValidationError。
- [ ] 瞬时错误会重试，schema 错误快速失败/有限重试，job attempts 正确递增。
- [ ] 多批次知识树输出「根 → 文档 → 知识点」；96/2 两份文档分组正确；叶子来源保留。
- [ ] `section_label` 对中文/英文编号有测试，不误伤标准号。
- [ ] 重建后稳定 ID/迁移策略明确；mastery/wrongbook/plan 不出现不可解释的孤儿。

### 7.2 前端

- [ ] 知识页默认只展开根/文档层，文档组可折叠。
- [ ] 组头显示文件名、知识点数、已测数。
- [ ] 全部展开/全部收起可用。
- [ ] 组内默认 20 条，可展开其余；98 条不再一次性铺满。
- [ ] 叶子标题单行截断 + tooltip；来源页码 `P18` 可见。
- [ ] 平铺旧框架自动按文档分组；无来源归入「未标注来源」。
- [ ] 选中详情、掌握度高亮、来源展开不回归。
- [ ] 51 个既有测试 + 新增测试全部通过，`tsc --noEmit` 通过。

### 7.3 端到端

- [ ] 新课程：上传 → 框架 → 3 种题型出题 → 作答 → 提交 → 掌握度 → 错题 → 复习目标 → 计划 → 任务完成，全绿。
- [ ] 旧课程：重建框架 → 知识页 2 个文档组可折叠 → 出题/作答 → 掌握度落回新节点。
- [ ] 失败场景：模型输出非法时，前端显示可读错误 + request_id；后端有 `llm_calls` 记录。
- [ ] 演示模式/真实模式标识不混淆；真实失败不静默降级。

---

## 8. 复现步骤（最小）

### 8.1 简答题出题失败

```powershell
# 后端已配置真实 Key，启动后在 StudyMate 目录运行
python - <<'PY'
import json, urllib.request
BASE='http://127.0.0.1:8000/api'
course='96d00dc9-9c7a-49df-bec6-0b22219563d5'
body=json.dumps({'question_count':3,'question_types':['single_choice','multiple_choice','short_answer'],'difficulty':'low'}).encode()
req=urllib.request.Request(f'{BASE}/courses/{course}/quiz/generate', data=body, method='POST', headers={'Content-Type':'application/json'})
print(urllib.request.urlopen(req).read().decode())
PY
# 轮询 GET /api/jobs/{job_id}，终态 failed，error_code=LLM_OUTPUT_INVALID
```

### 8.2 简答批改失败

```powershell
# 取旧课程 open quiz b60025c8-...，按题目提交；简答题会给真实模型批改
# 返回 502 LLM_OUTPUT_INVALID / score did not match the rubric breakdown
```

### 8.3 知识框架平铺数据核查

```sql
select count(*), level, is_leaf
from knowledge_node_versions
where framework_version_id='61e2b0ff-7cec-44e0-aaf7-f99fccc8a57d'
group by level, is_leaf;
-- 期望：1 行 (0,0)，98 行 (1,1)
```

---

## 9. 风险与待决

1. **生产模型选择**：`deepseek-flash` 成本/速度更好，但对 rubric 更“积极”；`deepseek-chat` 客观题稳定。需要产品决定是否固定 chat，或把 flash 兼容性纳入验收。
2. **`extra="ignore"` 的范围**：只对 LLM 响应模型放宽，还是全局？全局会掩盖字段拼写错误；建议只对 `app/llm/schemas.py` 的候选模型放宽，并记录被忽略键。
3. **答案键修复的边界**：绝不能按选项序号猜正确答案；只能重试/丢弃该题。需要明确“整卷失败”与“单题重试”的产品行为。
4. **稳定 ID 迁移**：知识树分组会改变 stable_key；如果掌握度需要跨版本保留，必须设计映射；否则每次重建都会“清零”掌握度。
5. **中文 section_label 推断**：正则要覆盖「第3章」「4.1」「Chapter 4」，同时避免把 `802.3by`、年份、页码误判为章节。
6. **数据重建**：旧课程 98 节点重建后，旧 mastery/gap/plan 指向旧 ID；演示库可接受，真实数据必须先迁移或备份。
7. **可观测存储**：原始响应可能含课件/学生答案，必须截断、脱敏、限制保留时间，避免 SQLite 膨胀和隐私问题。
8. **前端默认展开策略**：文档组默认收起会多一次点击，但能显著缩短首屏；需要在可用性测试中确认。

---

## 10. 附录

### 10.1 Job 时间线（库内 UTC，界面本地时间 +8）

| job id | 类型 | 模型 | 状态 | attempts | 耗时 | 备注 |
|---|---|---|---|---|---|---|
| `f037eb66-28e8-415b-9c36-5b0f01b511a2` | quiz.generate | flash | failed | 1/2 | 64s | 3 种题型 |
| `8d55bd7e-1365-43a0-9607-0ea3c6415edd` | quiz.generate | flash | failed | 1/2 | 58s | 纯客观 |
| `03a93d5f-3044-476c-a0fb-a489626fc9e6` | quiz.generate | chat | succeeded | 1/2 | 6s | 纯客观，4 题 |
| `6a7dfb58-833c-4865-8a33-dac1342296d3` | quiz.generate | chat | failed | 1/2 | 37s | 另一个 agent UI 重试 |

### 10.2 新课程数据

- course id：`96d00dc9-9c7a-49df-bec6-0b22219563d5`
- quiz id：`576c3978-b6ab-4542-9427-a6624dec4300`
- submission id：`383e01c6-f292-4daf-bb7c-71f753ee6e2a`
- plan id：`ec2d3ca6-ad00-4f3c-995a-00288ac73a25`
- 得分：0/4（故意选错）
- 掌握度：4 条，0.40；错题本 4 条；复习目标 3 个

### 10.3 旧课程框架统计

- framework version：`61e2b0ff-7cec-44e0-aaf7-f99fccc8a57d`（v2 active）
- 节点：1 根（level 0）+ 98 叶（level 1）
- 来源：96 个 `ch4_MAC子层_v2.0(5).pdf`，2 个 `运输层课件示例.pdf`
- `section_label`：99/99 空
- 标题长度：平均 78.3，最大 80

### 10.4 前端测试

- `npx vitest run --configLoader native --pool=threads`：13 个文件、51 个用例全部通过
- `npx tsc --noEmit`：通过
- 说明：沙箱内 Vite 默认 forks pool 会因 `spawn EPERM` 失败，改用 `--pool=threads` 是环境适配，不是产品问题。

### 10.5 配置说明

- 本轮为继续完成客观题链路，将 `StudyMate/.env` 的 `LLM_MODEL` 从 `deepseek-flash` 改为 `deepseek-chat` 并重启后端；该文件被 `.gitignore` 忽略。
- 密钥不出现在本报告、前端、日志或对话中。
- 当前后端为本次测试启动的进程；会话结束后若端口 8000 不通，可在 `StudyMate/` 下重新启动：
  ```powershell
  C:\Users\86159\anaconda3\envs\studymate\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```
