# v5 知识流水线真模型验收报告（2026-10-21）

**执行者**：接手 agent（Claude/DSH），基于交接文档 `v5-knowledge-pipeline-handoff-2026-10-21.md` §5①。
**模型**：`deepseek-chat`（`.env` 配置，key 来自环境变量；未改 `.env`、未写 DB settings）。
**环境**：conda `studymate`（Python 3.13.16），后端 `uvicorn 127.0.0.1:8000`（新起进程），DB `data/studymate.db` @ head `20261021_0010`。
**代码状态**：验收期间未改任何源码；`git status` 与交接时一致（20 个文件，未提交）。

---

## 0. 结论摘要

| 验收点 | 结果 | 关键数字 |
|---|---|---|
| 后端测试基线 | ✅ | 59 passed（需绕开沙箱 TEMP，见 §6.1） |
| 187 页课程构建 | ✅ 完成 | **159.9s**（服务端），85 次 LLM，0 失败 |
| 425 页课程构建 | ⚠️ 首跑失败 / 续跑成功 | 首跑 **258.9s** 失败（`LLM_TIMEOUT`），续跑 **184.0s** 成功 |
| 断点缓存 | ✅ 通过 | 二次构建 **2.1s / 0 次调用 / 548 个节点 ID 全复用**；425 页续跑命中 132/220 |
| 章节树质量 | ❌ **未达标** | 一级容器 **83 / 209** 个（合同要求 ≤20），且都是幻灯片标题 |
| 截止时间语义 | ❌ **与文档不符** | 88 个超时被记成"已完成"，最终码是 `LLM_TIMEOUT` 而非 `JOB_DEADLINE_EXCEEDED` |
| 掌握度孤儿率 | ⚠️ 已量化 | 187 页 **2/2 = 100%**（分母仅 2）；425 页 **13/14 = 92.9%** |
| 成本 | — | 305 次成功调用，输入 22.9 万字符 / 输出 68.5 万字符（粗估 ¥3–5） |

**一句话**：工程侧（并发、缓存、断点续跑、原子激活、`max_attempts=1`）全部按设计工作；**Stage A 对"无书签的幻灯片型 PDF"退化成逐页索引**，导致 425 页课程得到 209 个一级容器，直接违反设计复盘 §4.6 的验收线；截止保护在临界点会把超时钳到几秒并批量失败，失败码与进度语义都不符合交接文档。

---

## 1. 被验收的两个课程（库内实际数据）

| 课程 | id | 文档 | 页数 / chunk | v4 旧树 |
|---|---|---|---|---|
| 计算机网络·运输层 | `204637ae…` | `ch4_MAC子层` 184 页 + 3 页示例 | **187 / 186** | 98 节点，0 层平铺 |
| 真实模型验收 10-20 11:09 | `96d00dc9…` | ch1 118 + ch3 120 + ch4 184 + 示例 3 | **425 / 424** | 309 节点，0 层平铺 |

> **交接文档的页数有误**：文中说主课程 `204637ae` 是 "400+ 页"，实际 187 页；425 页的是验收课程 `96d00dc9`（4 个文档）。本次两个都跑了。

---

## 2. 构建结果

### 2.1 187 页课程（`204637ae`）

| 项 | 首次 | 二次（同一课程重建） |
|---|---|---|
| job | `48c3f3f4…` | `3105003b…` |
| 耗时（服务端） | **159.9s**（13:20:45.7 → 13:23:25.6） | **2.1s**（13:24:14.1 → 13:24:16.1） |
| 阶段 | outline → extract（85 单元）→ activate | outline → activate（全缓存） |
| LLM 调用 | 85（全部 `succeeded`，均值 5.44s） | **0** |
| 节点 | 548（1 根 + 83 L1 容器 + 10 L2 容器 + 423 L2 叶 + 31 L3 叶） | 548，**548/548 `knowledge_node_id` 完全相同** |
| 失败/重试 | 0；`attempts=1, max_attempts=1` | 同 |

### 2.2 425 页课程（`96d00dc9`）

| 项 | 首跑 | 续跑 |
|---|---|---|
| job | `5a2744b0…` | `3db4a48d…` |
| 结果 | **failed** `LLM_TIMEOUT` | **succeeded** |
| 耗时（服务端） | 258.9s | **184.0s** |
| LLM 调用 | 220 次尝试：132 成功 / **88 超时** | 132 次缓存命中 + 88 次调用（全成功） |
| 缓存 | 失败 job 的 132 条 section 缓存**保留** | 续跑消息显示"已抽取 132/220 个片段（缓存）" |
| 节点 | — | 1441（1 根 + 209 L1 + 15 L2 容器 + 1154 L2 叶 + 63 L3 叶） |

> 首跑失败发生在 **260s 左右**：进度从 132 直接跳到 220，是剩余预算被钳到几秒后一批调用瞬时超时。

---

## 3. 逐项判定

### 3.1 章节树质量：未达标

**证据**

- 187 页课程：83 个一级容器，其中大量是幻灯片标题——`MAC子层在哪里？`、`常见的接入情形`、`性能分析（续）`、`某时由谁来访问共享信道呢？`，还有一个叫 **`1`** 的容器（页码被当成标题）。
- 425 页课程：209 个一级容器，同样逐页：`课程的任务、目的和基本要求`、`网络分类（按地域规模）`、`40G/100G 以太网`…

**合同要求**（`backend-knowledge-design-review-2026-10-20.md`）

- L1079：`真实 4 份材料：顶层 chapter 数在合理范围（例如 ≤ 20），不是 309；每个叶子至少 level 2`
- L933：`文档文件名不作为容器标题`

**根因（读代码 + 实测 PDF 确认）**

1. `ch4_MAC子层`（184 页）`get_toc()` = **0 条**；`ch1_引言`（118 页）也是 0 条；`ch3_数据链路`（120 页）有 120 条，但全是**逐页幻灯片标题**。
2. 无书签时走 `knowledge_outline_service._pdf_heading_outline()`：**每页只取一个候选**——`classify_heading()` 命中的编号行，或字号 ≥ 正文中位数 +1.5 的第一行。幻灯片每页标题都是大字号 → **每页 = 一个 section**。
3. `_llm_outline_fallback()` 只在 `sections` 为空（`len(candidates) < 2`）时触发；83 个候选让它永不执行，而它才是设计里"只输出章节目录 + 页码范围"的那一步。

**结论**：这不是模型不会分层，而是启发式把"每页标题"当成了章节，且没有二次聚合到 chapter 层。Stage B/C 的表现是对的（叶子质量明显好于 v4，例如 `慢启动门限ssthresh`、`选择重传的按需重传与逐个确认`），坏在 Stage A 的粒度。

### 3.2 耗时：通过（但有前提）

- 187 页 **159.9s**，在 5 分钟预算内，余量约 40%。
- 425 页首跑 258.9s 撞线失败，续跑 184.0s 成功；**两段合计 443s**，超过单次 270s 预算——425 页在 `deepseek-chat` + 并发 3 下，一次跑完不现实。

### 3.3 断点缓存：通过

- 同课程重建：**2.1s、0 次 LLM、548 个节点 ID 完全复用**（38–75 倍提速）。
- 失败 job 的缓存保留，续跑只补 88 个缺口；缓存表 `knowledge_section_cache` 现 305 行，全部 `prompt_version=knowledge-framework-v5`、`model_name=deepseek-chat`。

### 3.4 截止时间与失败语义：与文档不符

**交接文档承诺**：`270s 总截止…超时是干净的 JOB_DEADLINE_EXCEEDED 失败且缓存保留`。

**实测**：

- 最终 `error_code = LLM_TIMEOUT`，`error_summary = "LLM request timed out."`，不是 `JOB_DEADLINE_EXCEEDED`。
- 88 个 section 超时发生在临近截止的窗口：单次超时按"剩余预算 ÷ 内层重试数"钳制，剩余 10s 时每次调用只有几秒，必然超时。
- **进度虚报**：`completed_units` 达到 `220/220`、`message` 写"已抽取 220/220 个片段"，但其中 88 个是失败。进度统计的是"已尝试"而不是"已成功"。
- 未发生静默降级（job 明确 failed，框架未激活），这条红线守住了。

### 3.5 掌握度孤儿率：已量化

| 课程 | gap states | 匹配到新 active 叶子 | 孤儿率 |
|---|---|---|---|
| 187 页 | 2 | 0 | **100%**（分母仅 2，统计意义弱） |
| 425 页 | 14 | 1 | **92.9%** |

**原因（逐条核对 14 个旧节点）**：

- 2 条旧标题与新叶子**完全一致**（`TCP慢启动`、`802.11 帧的一般结构`）→ 复用成功/接近成功；
- 1 条仅空白不同（`最短有效帧长 64 字节的由来`），`normalize_title_key` 语义下可救；
- 其余 11 条是**完全不同的话题措辞**（`TCP丢包事件响应` vs `丢包信号的严重程度区分`、`回退N步与选择重传` vs `回退 N 步的累计确认与重传`）——v4/v5 两套提示词产出的标题本来就不一样。
- 旧 `stable_key` 形如 `课程 > 第3章 > 题目`，v5 是 `v1:sha256(…)`；标题不匹配时身份规则只能新建节点，孤儿是**设计内已接受**的结果，但 93% 意味着现有学生的掌握度几乎全部失效。

### 3.6 成本与观测

- `llm_calls` 共 393 行：305 成功（均值 5551ms）+ 88 失败（输入 6.6 万字符基本浪费）。
- 成功调用输入 229,313 字符、输出 685,255 字符；按 deepseek-chat 粗估 **¥3–5**。
- `builder_version='v5'`、`source_fingerprint` 已落库，旧版本保持 `inactive`。

---

## 4. 与交接文档的差异清单

| 交接文档说 | 实测 |
|---|---|
| 主课程 400+ 页 | 187 页；425 页的是验收课程（4 文档） |
| 超时是干净的 `JOB_DEADLINE_EXCEEDED` | 是 `LLM_TIMEOUT`，且发生在 88 个批量钳制超时之后 |
| 进度 `completed_units` 反映抽取进度 | 失败单元也计入完成（220/220 时仍有 88 个失败） |
| 章节树 3–4 层、章名来自原文 | 层数是 3，但一级容器是逐页标题，不是章节 |

---

## 5. 建议下一步（按优先级）

1. **修 Stage A 的粒度（阻断项，Phase 1 的真正缺口）**
   - 幻灯片型 PDF（无书签、每页都有大字号标题）应把逐页标题**聚合到章/节**，而不是直接当容器；
   - 可用的强信号：目录页（`本章内容`/`4.1 信道分配问题` 这类编号行）、`classify_heading` 命中的编号序列；
   - 或者：候选数超过阈值（如 20）时**强制走 LLM outline 兜底**，让它把 page_inventory 归并成 ≤20 章的目录；
   - 验收线沿用合同 L1079：顶层 ≤20、无 level-1 叶子、无页码/`本章目标` 这类容器。
2. **修截止语义**：预算不足时不要继续发调用，直接抛 `JOB_DEADLINE_EXCEEDED`；`completed_units` 只统计成功；失败后 `attempts`/状态要能区分"超时失败"与"到期停止"。
3. **孤儿率**：短期接受（诚实显示"旧掌握度未迁移"）；中期给标题匹配加"去空白+去标点+同义词"兜底，或允许人工映射。
4. **Phase 2 前置**：树结构不对时先不要建类型化关系——关系会挂在错误的容器上。

---

## 6. 复现

### 6.1 本机沙箱的两个坑（会挡住 pytest）

```powershell
# 1) DSH 沙箱把 TEMP 指到 0o700 受保护 DACL 的目录，pytest 建 basetemp 会 PermissionError
$env:TEMP = "C:\Users\86159\Desktop\hackathon\.dsh-tmp\tmp2"; $env:TMP = $env:TEMP
# 2) CPython 对 mkdir(mode=0o700) 写受保护 DACL，需把 0o700 抬成 0o777（插件在仓库外，不改代码）
$env:PYTHONPATH = "C:\Users\86159\Desktop\hackathon\.dsh-tmp"
python -m pytest -q -p no:cacheprovider -p dsh_tmpfix   # 59 passed
```

### 6.2 构建与轮询

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# POST /api/courses/{id}/knowledge/build  → 轮询 GET /api/jobs/{job_id}
# 阶段：outline → extract(completed_units/total_units) → merge → activate
```

### 6.3 验收 SQL

```sql
-- 树的层级分布（把 <fv> 换成 active 版本 id）
select level, is_leaf, count(*) from knowledge_node_versions
where framework_version_id='<fv>' group by 1,2 order by 1;

-- LLM 观测
select purpose, status, count(*), round(avg(latency_ms)), sum(input_chars), sum(output_chars)
from llm_calls group by 1,2;

-- 孤儿率
select count(*) total,
       sum(case when v.id is null then 1 else 0 end) orphan
from student_gap_states s
left join knowledge_node_versions v
  on v.knowledge_node_id = s.knowledge_node_id
 and v.framework_version_id = '<fv>' and v.is_leaf = 1
where s.course_id = '<course>';
```
