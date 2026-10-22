# v5 修复记录：Stage A 结构闸门 + 截止/调度语义（2026-10-21）

承接 `v5-real-model-acceptance-2026-10-21.md` 的两个 P0 缺陷。改动**未提交**，提交由用户执行。

## 0. 修复前后对照

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 187 页课程 | 161.8s / 85 次调用 / **83 个一级容器** | 首建 24.2s（大纲未缓存）/ 重建 **2.1s、0 次调用**；**9 个一级容器** |
| 425 页课程 | 260.5s 失败（88 次超时）→ 续跑 184.0s，合计 444s | **165.1s 一次成功**，55 次调用，0 次超时；重建 **10.7s、0 次调用** |
| 425 页一级容器 | 209 个（逐页标题） | **15 个**（大纲章节） |
| 树深度 | 3 层但一级是幻灯片标题 | 4 层（根 → 章 → 节 → 叶），叶子全部 ≥ level 2 |
| 失败语义 | `LLM_TIMEOUT`，进度虚报 220/220 | 预算不足时 **`JOB_DEADLINE_EXCEEDED` 且不发请求**；进度只计成功 |
| 后端测试 | 59 passed | **77 passed**（+18 条回归） |

## 1. P0-1：Stage A 统一结构闸门

**新增纯函数**（`app/services/knowledge_outline_service.py`）

- `validate_outline_quality(sections, page_count) -> OutlineQuality`：**三条解析路径共用**
  - `top_level > max(20, ceil(pages / 12))` → `too_many_top_level`
  - 页数 ≥ 20 且一级数/页数 ≥ 0.5 → `per_page_headings`
  - 一级 > 8 且没有任何 level-2 → `no_hierarchy`
  - 页码式/编号残渣标题占比 > 10% → `invalid_titles`
- `is_meaningful_outline_title()`：拒绝纯数字、`4.2`、`第 3 章` 这类残渣；**不按字符数一刀切**（`TCP`、`概述` 仍有效）。

**解析流程**（`_resolve_document_outline`）

```
PDF 书签 → 过闸；不过 → 字号/编号启发 → 过闸；不过 → LLM 兜底（同样过闸）
LLM 兜底：最多 2 次，第 2 次带结构反馈（"returns 21 chapters, at most 20 allowed"）
两次都不过 → KNOWLEDGE_OUTLINE_FAILED（details 带 reasons/top_level/limit），
绝不退回"一页一章节"的平铺树
```

**候选提取**（`_heading_candidates`）：每页收集编号行 + 明显大字号行，保留字号/来源；高频页眉按出现比例剔除；相邻重复标题只留首个。候选提取与章节判定分离。

**page_inventory**：优先给真实标题（含大字号候选），无标题页才给摘录；按 32k 字符预算截取，截断时显式置 `inventory_truncated=true` 并写日志，不静默丢页。

**大纲缓存（新表 `knowledge_outline_cache`，迁移 `20261021_0011`）**

- 键 = `OUTLINE_PARSER_VERSION + 文档内容指纹(页号/状态/原文) + prompt 版本 + 模型 + provider`；
- 命中即复用同一份章节划分 → section 缓存键（含路径与页码区间）保持稳定；
- 未命中且过闸才写回；缓存读写失败只记日志，不影响构建。

**section 缓存键**（按用户要求）现在包含：`outline_parser_version`、规范化 section 路径、页码区间、窗口内容哈希、抽取 prompt 版本、模型名、provider 哈希。

## 2. P0-2：全局截止与调度

**预算模型**（`BuildBudget`，Stage A 与 Stage B 共享同一实例）

- `available = remaining - finalization_reserve(10s)`；
- `available < min_request_window`（`max(30s, 内层重试次数 × 15s)`）→ **不发请求**，直接 `JOB_DEADLINE_EXCEEDED`；
- 单次尝试超时 = `min(provider_timeout, available / 内层重试次数)`，下限 15s（**不再是 5s**）；
- 适配器内部重试次数被计入窗口计算，避免"外层以为还有预算、内层已经跑飞"。

**有界提交**（`_extract_windows`）

- 线程池内最多 `SECTION_EXTRACT_CONCURRENCY=3` 个任务；完成一个才补一个，不再一次提交 200+；
- 共享 `stop_event`：失败或预算耗尽后不再提交，未提交的全部取消；
- 在途请求不强行 kill（httpx 同步调用），由请求级超时兜底；结果仍写缓存供续跑。

**终态原因**

- 首个**根因**失败决定 job 错误码；取消/超时产生的辅助错误不覆盖它；
- 保留原始码：`LLM_TIMEOUT` / `LLM_REQUEST_FAILED` / `KNOWLEDGE_EXTRACTION_FAILED` / `JOB_DEADLINE_EXCEEDED`；
- `AppError` 包装 `LLMTemporaryError` 的结果，构建 job `max_attempts=1`，不再自动重跑。

**进度与观测**

- `completed_units` 只统计成功（缓存命中算成功）；`total_units` 固定；
- 新增诊断计数 `failed_units / skipped_units / cancelled_units / terminal_reason`；
- `llm_calls` 区分真实调用与未启动任务：`attempt=0, status=skipped_deadline, latency=NULL`；被取消的不入表。

## 3. 真实验收（同一批课件）

| 场景 | 耗时 | LLM 调用 | 结果 |
|---|---|---|---|
| 187 页首建 | 24.2s（16/23 命中旧 section 缓存） | 1 大纲 + 7 抽取 | 9 章 / 20 节 / 185 叶 |
| 187 页重建 | **2.1s** | **0** | 215 个节点 ID 全复用，树完全一致 |
| 425 页首建 | **165.1s** | 4 大纲（ch1 首次 21 章被拒→反馈重试通过）+ 51 抽取 | **15 章 / 48 节 / 430 叶** |
| 425 页重建 | **10.7s** | **0** | 494 个节点 ID 全复用，树完全一致 |

树样本（425 页）：`第3章 运输层`、`第一章引言`、`数据链路层的设计问题`、`差错检测和纠正`、`基本数据链路协议`、`滑动窗口协议`、`数据链路协议实例`、`第四章介质访问子层`、`多路访问协议`、`以太网`、`数据链路层交换`、`无线局域网`……

大纲日志（425 页构建）：4 个文档中 3 个走 LLM 兜底；ch1 首次返回 21 个一级章节（上限 20）被闸门拒绝，第二次带反馈通过——修复尝试在生产路径上真实生效。

## 4. 已知遗留（未在本次改动范围内）

1. ~~**章首未覆盖页不进抽取窗口**~~：**已于 2026-10-22 修复，且原判断有误**——`_plan_windows` 对"没有小节的章"本来就会给整章一个窗口（`knowledge_pipeline.py:648-652`），184 页 ch4 第 1 章 1–11 页一直在抽；真正漏的是每章章首过渡页和节间空洞（实测 v9 为 178/184 页在窗口内）。详见 §7。
2. **孤儿学习数据**：187 页 2/2、425 页 14 条中 safe_auto 5、squash_only 2、no_match 7。明细见 `v5-orphan-audit-2026-10-21.md`；**未删除、未自动迁移**。
3. **大纲非确定性已被缓存固定**：换模型、改 `OUTLINE_PARSER_VERSION` 或清空 `knowledge_outline_cache` 会重新生成大纲，section 缓存随之失效（这是预期行为）。
4. **前端错误文案**仍缺 `KNOWLEDGE_OUTLINE_FAILED` / `JOB_DEADLINE_EXCEEDED` / `KNOWLEDGE_BUILD_IN_PROGRESS` 的中文文案（本轮未动前端）。

## 5. 迁移与运维

- 迁移 head：`20261021_0011`（新增 `knowledge_outline_cache`，含 `document_id` 索引）；dev 库已升级。
- 强制重算大纲：`delete from knowledge_outline_cache;`（或在同库改 `OUTLINE_PARSER_VERSION`）。
- 强制重算抽取：清 `knowledge_section_cache`，或换模型（键含模型名）。
- 观测：`select purpose, status, count(*), avg(latency_ms) from llm_calls group by 1,2;`

## 6. 回归测试清单（新增 18 条）

`tests/unit/test_knowledge_outline_quality.py`

- 逐页书签被判失败（三个 reason 同时命中）、合格章节大纲通过、页码标题被拒；
- 30 页逐页书签 → 触发 LLM 兜底 → 得到 3 章；
- LLM 输出 40 章 → 重试一次（带反馈）→ 仍不合格 → `KNOWLEDGE_OUTLINE_FAILED`；
- 大字号标题进入 page_inventory；大纲缓存命中后不再调用模型；
- 预算不足时 `ensure_call_possible` 抛 `JOB_DEADLINE_EXCEEDED`；超时下限 15s；预算按适配器实际生效的设置（含设置页 DB 覆盖）计算。

`tests/unit/test_knowledge_pipeline_scheduling.py`

- 10 个窗口只提交 3 个（有界）、失败即停、其余计为取消；
- 预算耗尽：0 次请求、1 跳过、其余取消、错误码 `JOB_DEADLINE_EXCEEDED`；
- 成功计数、缓存命中计为完成且不重复调用；
- provider 失败后不被后续取消错误覆盖。

`tests/integration/test_knowledge.py`

- 30 条逐页书签 → 单章树 + 重建 0 次调用；
- 3 节只有 1 节成功 → `completed_units=1/3`、`progress<70`、`llm_calls` 记为 1 成功 2 失败；
- 预算不足 → `JOB_DEADLINE_EXCEEDED`、`completed_units=0`、观测表只有 `skipped_deadline`。

## 7. 2026-10-22 追加：章首/章尾/节间空洞吸收

### 7.1 问题（更正 §4.1 的旧判断）

旧记录说"184 页 ch4 第 1 章 1–11 页因为没有小节而不进窗口，约 6% 内容丢失"。复核代码后不成立：`_plan_windows` 对没有子节的章会给整章一个窗口（`knowledge_pipeline.py:648-652`），这 11 页一直在抽。

真正的缺口用 DB 实测（v9 `19df34c7`，按 `knowledge_section_cache` 里的窗口区间统计）：

- 184 页文档：窗口覆盖 178/184，漏的是每章章首过渡页 1 页（12、37、43、47、77、137）；
- 425 页课程 120 页文档：还漏 66、110（节与节之间的洞）；
- 占比 1%–3%，不是 6%。这些页既进不了窗口，也过不了 `_collect_leaves` 的 `valid_pages` 校验。

### 7.2 改法

`absorb_chapter_lead_in()`（`knowledge_outline_service.py`，纯函数、7 条单测）在 Stage A 解析完、`merge_document_outlines` 之前，按文档把每章页码铺成连续区间：

- 章区间补齐为 `[章起始, 下章起始-1]`（末章到文档末页）；
- 章内小节按声明起点铺满整章：首节前移到章起始、中间节延伸到下一节起点之前、末节后延到章末尾；
- 只改页码，不改标题/层级/条目数；书签名录这类本来就严丝合缝的大纲是恒等变换。

关键是**单点**：合并（`page_ranges`）、窗口规划（`_plan_windows`）、来源校验（`_collect_leaves`）读的是同一份区间，不会出现"进得了 payload、过不了校验"的错位。没有递增 `OUTLINE_PARSER_VERSION`：大纲缓存存的是模型原始 payload，仍然有效；section 缓存键本来就含页码区间，区间变了的窗口自然失效。

### 7.3 验证

- 结构（确定性，离线重算规划）：187 页课 23 个窗口铺满 184+3 页；425 页课 51 个窗口铺满 425 页；两课重叠页均为 0。
- 187 页课（deepseek-chat，`f18938e4`）：重建 14.8s、2 次调用（其余 21 个窗口命中历史缓存），216 节点（9 章 / 37 二级 / 170 叶），比 v9 多 2 叶。新吸收的页 12/37/43 分别产出「ALOHA 协议的两个版本」「位图协议在控制访问协议中的定位」「…的作用」；47/77/137 是章分隔页，进了窗口但没有可抽取内容（无叶子，属正常）。
- 身份：v9 → `f18938e4` 复用 185/215 节点，30 个叶子因首节多 1 页、标题变化而换 ID——**挂在这些叶子上的掌握度会孤儿化**，是这一改动的预期代价。
- 425 页课（deepseek-flash，`83e65147`）：51 个窗口、51 次调用、206s；但该版本在"节间补洞"落地前构建，120 页文档第 66/110 页仍未进树，下次重建才会补齐（离线重算的规划已是 0 未覆盖）。
- 测试：全量 **84 passed**（新增 7 条：章首前移、章尾后延、无小节章不动、跨章补洞与越界收敛、节间铺满、幂等、书签路径端到端）。

### 7.4 运维注意

- 改动会让受影响窗口的 section 缓存失效（实测 187 页课 6 个章首节里 2 个必须重抽，其余命中历史缓存）。
- 设置页换模型 → 大纲缓存与 section 缓存同时失效（键都含模型名），重建退化为全量重抽：187 页 23 次 / 166s、425 页 51 次 / 206s。
- 425 页课曾有一次重建因 3 个并发请求同时撞 60s 超时而 `LLM_TIMEOUT`（29/51），当时另有 187 页构建在跑、共 6 路并发；单独重试 206s 成功。**不要在两门课同时重建**。
- 孤儿掌握度：187 页 2/2、425 页 13/14 已指向不存在的节点（换 flash 重建又新增 6 条）。未删除、未迁移。

## 8. 2026-10-22 追加：文档级伞形章（层级塌缩修复）

### 8.1 问题

教材每份 PDF 是一整章，Stage A 却常把文档内部小节当成顶级章：425 页课 4 份文档合并后 15 个"一级章"（其中 6 个是「数据链路层的设计问题」这类节名），187 页课 9 个（7 个节名）。面板第一屏全是平铺的节，层级信息丢失。

### 8.2 改法

新增纯函数 `wrap_document_outline()`（`knowledge_outline_service.py`），在 `_resolve_document_outline` 之后、`merge_document_outlines` 之前按文档收敛（**大纲缓存的读写没动**，缓存里仍是模型原始输出）：

1. 一级标题恰好一个匹配 `第X章`/`chapter N` → 它就是伞形章（页码扩到整份文档），其余一级降为二级；被降级一级的子节点只把页码并进父区间后丢弃；
2. 一个都不匹配 → 用 LLM 的 `root_title` 或文件名 `chN_名称` 造伞形章，原一级全部降二级；两者都拿不到就不 wrap；
3. 两个及以上匹配 → 多章合订本，原样返回。

降级节点的页码取"自身 ∪ 子节点"并集，首尾相接仍由 §7 的 `absorb_chapter_lead_in` 负责。`_resolve_document_outline` 改为返回 `(sections, root_title)` 以支持分支 2；`OUTLINE_PARSER_VERSION` 升到 `outline-parser-v3`。

顺带修的两处：
- `MasteryService.list_mastery` 跳过 activity 树里已不存在的节点（不再返回 `title=None` 的空行；DB 记录保留）。`_gap_response` 走历史版本标题，无需改；`select_review_targets` 只从活动叶子选，天然无孤儿。
- 前端 `Knowledge.tsx`：`section_label` 是标题前缀时不再重复渲染（"第3章第3章 运输层"）；选中容器节点时右侧渲染摘要卡（N 个小节 · M 个知识点 · 已测 K + 可点开的小节行），无新 API。

### 8.3 验收（deepseek-flash，`2026-10-22` 14:27–14:37）

- 顶层章数：425 页 15 → **4**（第3章 运输层 / 第一章引言 / 第三章 数据链路层基础 / 第四章介质访问子层）；187 页 9 → **2**。与预期一致。
- 窗口：425 页 24 个、187 页 8 个；两课均 0 未覆盖页、0 重叠页（`absorb_chapter_lead_in` 的铺满仍然成立）。
- 掌握度接口：两门课 `/mastery` 都返回 0 行（16 条记录全部指向旧节点，属孤儿），**零条 `title=None`**。
- 测试：后端 **93 passed**（新增伞形章 8 条单测 + 1 条集成用例：两个节级 L1 → 单章树）；前端 **63 passed**、`tsc --noEmit` 通过。
- 首次 425 页重建在 13/24 处 `LLM_TIMEOUT`（3 个并发同时撞 60s），重试从缓存续跑 146s 成功。

### 8.4 代价与待定

- **叶子密度下降**：425 页 466 → 244 节点（叶子 385 → 217）、187 页 224 → 82（叶子 177 → 72）；有出处页 85.9% → 73.9% / 90.4% → 74.9%。原因是合并小节让窗口数 51 → 24、23 → 8，而每个窗口的 `SECTION_MAX_LEAVES_HINT` 固定 10，叶子总量被"窗口数 × 10"封顶。这与"叶子数与现在相当（±10%）"的预期不符，需要在三选一里定：保持现状（树更粗）/ 按窗口体量放大 `max_leaves`（要升 prompt 版本并全量重抽）/ 保留孙节点为二级（窗口数回到 51 左右，但降级章名消失）。
- 大窗口也让单次调用更长（24 个窗口平均 20s+），270s 预算更紧；重建前不宜再并发跑别的构建。
- 身份：425 页 466 → 244 复用 44；187 页 225 → 83 复用 10——换层级 + 换模型导致大规模换 ID，掌握度全部孤儿化（未删除）。

## 9. 2026-10-22 追加：Phase 2 类型化关系（含 max_leaves 随窗口缩放）

### 9.1 改法

- **Schema**（`app/llm/schemas.py`）：`KnowledgeRelationV5`（`source_ref` / `target_ref` / `relation_type` / `confidence` / `evidence`），`RELATION_TYPES` 六类（prerequisite / derives / causes / contrasts_with / applies_to / counterexample_of），`KnowledgeSectionExtractionV5.relations` 默认空。
  **六类没有写成 `Literal`**：schema 是逐字段严格校验，模型给一个陌生类型就会让整个窗口 `ValidationError` → 重抽 → 可能整窗失败，与"无效关系丢弃、构建不失败"直接冲突。改为宽松字段 + 流水线过滤（`relation_type` 非六类即丢）。
- **Prompt**：`FRAMEWORK_PROMPT_VERSION` 升 `knowledge-framework-v6`；system prompt 增加 relations 契约与六类定义、只准连本次输出叶子、自环/双向重复禁止、每叶 ≤3 条、总数 ≤叶子数、confidence 诚实估计；叶子提示改为"遵守 payload 的 max_leaves 预算"（原为固定 8–12）。
- **max_leaves 缩放**：`compute_max_leaves_hint()`（纯函数）= `clamp(normalized_chars // 1400, 10, 20)`，在 `_window_payload` 注入。窗口切分不变（仍是 `SECTION_WINDOW_CHAR_LIMIT` 28000），缓存键不变。**该公式对幻灯片型课件的实测值为常数 10，已由 §10 改为按页缩放。**
- **流水线**：ref 只在叶子通过质量过滤 + 来源校验之后才可被解析（引用了被丢弃叶子的关系一起丢）；自环/越界 confidence/未知类型丢弃；`(source,target,type)` 与 `(target,source,type)` 视为同边、保留 confidence 更高那条的**方向**；section 内按每叶 ≤3 条封顶（高置信度优先）。`BuildDiagnostics` 新增 `relations_kept` / `relations_dropped`（dropped 含去重输家与超限者）。
- **落库**：`_persist_leaves` 返回"规范化标题 → node_version_id"，每个 section 的叶子落完后写关系行（`KnowledgeNodeRelation`，版本作用域，随框架版本整体重写；端点缺失/合并成同一节点/重复边丢弃）。
- **Mock**：`_build_mock_section_v5_candidate` 用自己构造的 leaf ref 产 1–2 条合法关系（不足两个叶子时返回空，自环会被丢弃）。
- **API**：新增 `GET /api/courses/{id}/knowledge/graph` → `{framework_version_id, nodes:[{knowledge_node_id,title,section_path,is_leaf}], edges:[{source,target,relation_type,confidence,evidence}]}`（只出 active 版本、只含有关系的节点；`source/target` 都是 `knowledge_node_id`）。详情接口 `relations` 形状不变，前端 `Knowledge.tsx` 已能渲染，**本轮前端零改动**。

### 9.2 验收（deepseek-flash，`2026-10-22` 15:05–15:22）

- 187 页课 v13 `c7efb1c9`：2 章 / 8 节 / **66 叶**；8 窗口 8 次调用 100s；**49 条关系**（0.74 条/叶），5 种类型，confidence 0.65–0.95（中位 0.85），49/49 带 evidence，0 个非法端点；有出处页 69.5%。
- 425 页课 v12 `c3317cfd`：4 章 / 24 节 / **218 叶**；首轮 16/24 处 `LLM_TIMEOUT`（225s），重试命中 16 个缓存窗口 + 8 次新调用、136s 成功；**142 条关系**（0.65 条/叶），六类全部出现，confidence 0.60–0.95（中位 0.85），136/142 带 evidence，0 个非法端点；有出处页 69.9%。
- 缓存续跑：187 页课再重建 **2s、0 次 LLM 调用**，关系随缓存 payload 一起重建（仍是 63 节点 / 49 边）。
- 图端点：187 页 63 节点 / 49 边，425 页 180 节点 / 142 边；`section_path` 为「第3章 运输层 > 可靠传输：GBN 与 SR」两级；详情接口返回 1 条以上的关系。
- 测试：后端 **106 passed**（新增 11 条关系/预算单测 + 2 条集成：mock 关系落库与图端点、坏关系不失败）；前端 **63 passed**、`tsc --noEmit` 通过。

### 9.3 偏差：max_leaves 缩放对本教材**无效**（结论，已由 §10 修正）

实测每个窗口的规范化正文只有 178–10785 字（幻灯片型 PDF 约 220 字/页），`chars // 1400` 最大只有 7，全部落到下限 10——公式一次都没生效。结果叶子数 425 页 217 → **218**、187 页 72 → **66**，没有回到 350 / 150。

分 section 看更清楚：187 页课 8 个节里 5 个正好打满 10（30–60 页的大节），另 3 个只有 7/5/4 条（3–6 页、291–693 字的薄节）。也就是说瓶颈是"窗口数 × 预算"里的预算对写满的大节偏低，而薄节本来没内容。

可选（都要再全量重抽一次，约 24 次调用）：

1. **按页数缩放**（如 `clamp(窗口页数 // 2, 10, 20)`）：大节 46/60/48 页 → 20，小节仍 10；粗估 187 页 95–110 叶、425 页 300 上下。
2. **按页切窗口**（如每 12 页一个窗口）再配 10 的预算：425 页约 35 个窗口 → 320 叶上下，但调用数 +50%、270s 预算更紧。
3. **保持现状**：树最干净，密度接受 218/66。

注意：`max_leaves` 不在 section 缓存键里（键＝解析器版本 + 路径 + 页码区间 + 内容哈希 + prompt/模型/provider；预算由内容哈希间接决定）。**改预算公式时要同时升 prompt 版本或把预算并进缓存键**，否则重建会命中旧缓存、看起来"改了没效果"。

### 9.4 遗留

- 关系只连**同一个窗口/节内**的叶子（模型看不到别的节），跨节边没有；同节内两个不同 ref 若标题相同会被合并成一个叶子，那条边会以自环形式丢弃。
- 关系是版本作用域：每次重建整体重写，不做跨版本合并；掌握度 16 条仍全部孤儿（`/mastery` 0 行）。
- 大纲层（wrap / absorb / 大纲缓存读写）本轮未改。

## 10. 2026-10-22 追加：max_leaves 改按页缩放 + hint 并入缓存键（收尾）

### 10.1 改法

- `compute_max_leaves_hint(page_count)` = `clamp(page_count // 2, 10, 20)`，字符维度整体移除（`SECTION_CHARS_PER_LEAF` 删除）。
- 新增 `count_window_pages(units)`：同一文档取 `max(page_end) - min(page_number) + 1`，多文档窗口按各文档页跨度相加；`_window_payload` 用它算 hint。窗口切分仍只看字符（`SECTION_WINDOW_CHAR_LIMIT` 28000），两者互不影响。
- `_section_cache_key(..., max_leaves=...)` 的 payload 追加 `|leaves:{hint}`，`_plan_windows` 先构建 payload 再算键。**`FRAMEWORK_PROMPT_VERSION` 保持 `knowledge-framework-v6`**：提示词文本没改，版本号只反映提示词；预算进键后调参不需要再升版本。
- 设置页 `llm_timeout_seconds` 60 → **90**（纯设置，不改代码）；`BuildBudget` 本来就用适配器实际生效的设置计算超时与最小预算窗口。

### 10.2 验收（deepseek-flash，`2026-10-22` 16:25–17:02）

- 187 页课 v15 `51131589`（v16 `898d016e` 为同结构零调用重建）：2 章 / 8 节 / **98 叶**（66 → 98，+48%）；8 窗口 8 次调用 149s；**64 条关系**（0.65/叶），5 种类型，confidence 0.70–0.95，64/64 带 evidence，0 非法端点；有出处页 **86.1%**（此前 69.5%）。
- 425 页课 v15 `58c36554`（v16 `3d81fa03`）：4 章 / 23 节 / **258 叶**（218 → 258，+18.3%）；24 个窗口分三轮完成——首轮 12/24 `LLM_TIMEOUT`（214s）、次轮 20/24 超时（198s）、第三轮命中 20 个缓存 + 4 次调用 145s 成功，全程 24 次有效调用无重复；**174 条关系**（0.67/叶），六类里用了 5 类，confidence 0.65–0.95（中位 0.85），173/174 带 evidence，0 非法端点；有出处页 **78.8%**（此前 69.9%）。
- 预算与填充：24 个窗口的 `max_leaves` 合计 287，实际 258（90.6%）。未填满的主要是 1–4 页的薄窗（预算 10 但只有 1–2 个知识点）；「本章目标」这类目录型节被质量过滤成 0 叶后整节被裁掉。425 页课比验收线 260 少 2 条（0.8%）——**用户已裁定接受 258，不再加码**；按当前公式再抽一次会命中缓存、结果不变。
- 零调用重建：两门课都 **10–11s、0 次 LLM 调用**，关系随缓存 payload 重建，边数保持 64 / 174。
- 测试：后端 **108 passed**（新增 2 条：多文档页跨度相加、同内容不同 hint 产生不同 cache_key；预算边界改为按页断言）。

### 10.3 结构冻结

- **冻结决定（2026-10-22 用户裁定）**：接受 425 页课 258 叶（该课验收线 260，仅差 0.8%），不追加公式调整；以下范围自此刻冻结，演示数据（重新出题、作答、挂掌握度）在冻结后的结构上做。
- 冻结范围：大纲层（wrap / absorb / 大纲缓存读写）、窗口规划（`SECTION_WINDOW_CHAR_LIMIT` 与按 section 切窗）、`max_leaves` 公式（`clamp(页数 // 2, 10, 20)`）、`FRAMEWORK_PROMPT_VERSION`（`knowledge-framework-v6`）。
- 冻结基线：187 页课 v16 `898d016e`（2 章 / 8 节 / 98 叶 / 64 关系）、425 页课 v16 `3d81fa03`（4 章 / 23 节 / 258 叶 / 174 关系），两课零调用重建 10–11s。
- 若将来确实要调 hint：键里已有 `leaves:{hint}`，重建会自动全量重抽，不会误命中旧预算的缓存。

## 11. 2026-10-22 追加：Phase 3 importance / difficulty 评分（读取时计算）

### 11.1 改法

- **纯函数模块** `app/services/knowledge_scoring.py`（不依赖 ORM / 会话）：`score_leaves()`、`prerequisite_chain_depths()`、`highlight_gap()`、`rank_highlights()` + 数据类 `LeafScoringInput` / `RelationEdge` / `LeafScore` / `HighlightCandidate`。权重是模块常量（`IMPORTANCE_WEIGHTS` / `DIFFICULTY_WEIGHTS`），调参不迁移、不重建，下次请求生效。
- **重要性** `I = 0.3·E + 0.3·C + 0.2·F + 0.2·R`。E=该叶 distinct 来源页数（document_id + page_number）；C=关系度数（出边 prerequisite 记 2——“被依赖=基础性”，其余已存在的边记 1）；F=content 字符数；R=`question_knowledge` 映射到该叶的题目数（同题多角色只算一次）。四分量先各自除以全体叶最大值（该列全零置 0）再加权，保证 I∈[0,1]；没有测验时 R 全 0，公式自动退化。
- **难度** `D = 0.5·前置链深度 + 0.3·前置入度 + 0.2·F`。前置链深度沿 prerequisite 边反向（依赖者 → 被依赖者）记忆化 DFS；on-stack 集合防环，遇环按当前路径长度截断；节点与前置边排序后遍历，结果与输入顺序无关。前置入度 = 该叶的 prerequisite 前置数量。
- **解释**：每叶返回 `components`（四分量原值）与 `reasons`（贡献前二：`component` / `value` 原值 / `normalized` / `contribution`）。
- **仓储**：`KnowledgeRepository` 新增 `count_source_pages_by_node`、`count_question_mappings_by_node`、`list_version_relations`；都限定在传入的框架版本内。
- **服务**：`KnowledgeService.get_scored_tree()` / `get_highlights()`；掌握度复用 `MasteryRepository.list_states`（孤儿记录匹配不到 active 叶子，自然忽略）；抽出 `_section_paths()` 供 graph / highlights 共用，`_require_active_framework()` 统一 404。
- **API**：
  - `GET /api/courses/{id}/knowledge/tree` → `{framework_version_id, version_number, scoring_version, tree}`。树节点与 `KnowledgeTreeNodeResponse` 同形，另加 `importance` / `difficulty`（容器取后代最大值）与叶子的 `components`（容器为 null）；只返回 `tree`，不含旧端点的 `nodes` 副本；不带掌握度（前端已单独拉 `/mastery` 按 node id join）。
  - `GET /api/courses/{id}/knowledge/highlights?limit=20&order=importance|difficulty|gap` → `{items:[{knowledge_node_id,title,section_path,importance,difficulty,mastery_estimate,evidence_count,untested,reasons}], basis:{scoring_version:"scoring-v1", weights:{importance,difficulty}}}`。`limit` 默认 20、上限 50；`order` 非法或 `limit` 越界都是 422 `VALIDATION_ERROR`。`gap = importance × (1 − mastery_estimate)`；未测验（无 state）`mastery_estimate=null`、`untested=true`，在 gap 排序中排在所有已测验之后。`evidence_count` 是掌握度证据数（作答次数），不是出处页数。
  - 旧 `GET /knowledge`、`GET /knowledge/{id}`、`GET /knowledge/graph` 契约不变。
- 未改：构建流水线、section/outline 缓存、prompt 版本、`max_leaves`、§10.3 冻结范围内的任何文件；无迁移、无新依赖。

### 11.2 验收（两门已构建课程直接读端点，零 LLM 调用，2026-10-22 17:05–17:10）

- 425 页课 `3d81fa03`：tree 137ms、highlights 45–74ms；27 容器 + 258 叶，容器聚合 0 违例；258 叶中 0 个 importance=0，35 叶无关系边；`quiz_reinforcement` 合计 0（尚未作答）。
- 187 页课 `898d016e`：tree 39ms、highlights 34–45ms；10 容器 + 98 叶，聚合 0 违例；10 叶无关系边。
- 两课 `/mastery` 均 0 行 → `order=gap` 与 `order=importance` 完全同序，items 全部 `untested: true`（符合“未测验 ≠ 薄弱”）。
- 抽查排序：慢启动 425 页 #17/258、187 页 #23/98；CSMA/CD 425 页 #10、VLAN #2、海明码 #9；「拥塞避免」425 页 #131、187 页 #55（只被抽成 1 页 1 条关系）；关键词「差错检测」命中的是本章总结叶 #219，而同节 3.2 的主体叶（海明码 #9、海明距离 #49、CRC #63）排位正常。
- 结论与解读：评分是“抽取出处密度”的代理，没有教材语义先验；排位差异来自 E/C/F 的事实差异，不是权重 bug。演示时按“证据密度”口径解释，不说“教材重点”。

### 11.3 测试

- 单测 `tests/unit/test_knowledge_scoring.py`（18 条）：权重和为 1、按最大值归一化、全零分量除零保护、空输入退化、R 分量、出边 prerequisite×2、链/分叉/环深度（环有界且与调用顺序无关）、非 prerequisite 边与未知端点忽略、reasons 前二与全零回退、importance/difficulty 排序、gap 排序（未测验垫底）、无掌握度时 gap=importance、limit 上限、非法 order。
- 集成 `tests/integration/test_knowledge_scoring_api.py`（5 条，mock 构建）：tree 与旧 `/knowledge` 逐字段一致且容器=子级最大；叶子 components 四键；highlights 默认/难度序、limit、basis 权重；零掌握度 gap 退化；写入一条掌握度后 gap 把已测验叶排到最前、其余 untested；404（无 active 框架/未知课程）；422（order/limit）。
- 全量：后端 **131 passed**（108 + 18 + 5，约 58s）；前端 **63 passed**、`tsc --noEmit` 通过（前端本轮零改动）。

### 11.4 遗留

- R 分量要等演示前重新作答才非零；在那之前 `order=gap` 等于 importance，重难点视图的“掌握缺口”没有区分度。
- 评分不引入语义先验：教材重点但只被抽成 1 页、无关系的概念排名靠后；要改善只能动抽取（已冻结）或给权重/分量加先验（本轮未做，需产品确认）。
- 高亮榜按全课全局归一化，页面/关系更密的章节天然更容易上榜；按章内归一化需另开端点参数。
- `section_path` 与 graph 同口径（章→节标题，不含课程根）；容器 importance 是后代最大值而非平均，语义是“本章最重要”。
- 关系跨节缺失（Phase 2 遗留）会直接影响 C 分量：只连同一窗口/节内的叶，薄节叶子的 centrality 可能为 0。


