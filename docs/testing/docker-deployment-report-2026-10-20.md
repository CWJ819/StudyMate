# Docker 部署与真实使用流程验收报告

- 报告日期：2026-10-20
- 测试环境：Windows + Docker Desktop 29.8.2（Linux 容器，WSL2）+ conda `studymate`（Python 3.13.16 / Node 24.13.0）
- 构建上下文：`StudyMate/`
- 镜像：`studymate:local`，约 283 MB
- 运行方式：`LLM_BASE_URL=mock://local`，单容器，`7860:7860`，命名卷 `studymate-test-data:/mnt/workspace/studymate`
- 结论：**镜像构建成功；API + SPA 在 7860 正常；课程 → 上传解析 → 知识框架 → 六题测验 → 幂等提交 → 掌握度/错题本 → 复习目标 → 计划 → 任务完成的全流程通过；容器重启后数据保留；页面设置可保存并影响下一次 LLM 调用。**

## 1. 构建与启动

```bash
cd StudyMate
docker build -t studymate:local .
docker run -d --name studymate-test -p 7860:7860 \
  -v studymate-test-data:/mnt/workspace/studymate \
  -e LLM_BASE_URL=mock://local studymate:local
```

第一次构建在 `pip install --constraints` 处失败：pip 只支持 `-c/--constraint`，不支持 `--constraints`。改为 `-c /tmp/constraints.txt` 后构建成功。最终阶段输出：

- 前端：`npm ci` 安装 227 个包，`tsc --noEmit && vite build` 通过。
- 后端：`pip install -c deploy/constraints.txt .` 安装 30 个包，wheel 构建成功。
- 启动日志：Alembic 从空库升级到 `20261018_0009`，uvicorn 监听 `0.0.0.0:7860`。

## 2. 镜像内容与端口

- `EXPOSE 7860`，`PORT=7860`，`APP_ENV=production`。
- 数据路径：`/mnt/workspace/studymate/studymate.db` 与 `uploads/`。
- 镜像内没有 `.env`，没有 `data/`，没有 SQLite；`frontend/dist`、`alembic.ini`、`serve.py` 均存在。
- `GET /api/health` → `200 {"status":"ok","application":"ok","database":"ok","environment":"production"}`。
- `GET /` → SPA `index.html`；静态 JS 资源 200；`/openapi.json`、`/docs` 正常。
- 容器资源：约 99 MiB 内存、0.4% CPU（空闲采样）。

## 3. 真实使用流程

测试材料使用 `tests/fixtures/f1-sample.pdf`（3 页，第 2 页无文本），通过 API 和页面共同操作。

| 步骤 | 结果 |
|---|---|
| 创建课程「计算机网络（Docker 验收）」 | 201 |
| 未构建知识框架时查询 `GET /knowledge` | 404 `RESOURCE_NOT_FOUND`（空状态） |
| 上传 PDF + 解析 job | 201 → job `succeeded`；材料 `completed_with_warnings`，`no_text_pages=[2]` |
| 内容检索 `q=拥塞` / chunk 详情 | 1 条命中，页码 1，可定位到 `f1-sample.pdf` |
| 构建知识框架 job | `succeeded`；v1 `active`，2 个叶子，节点详情带 `page_number`/`chunk_id` 来源 |
| 生成 6 题混合测验 | job `succeeded`；`single_choice`/`multiple_choice`/`short_answer` 各 2 题 |
| 提交测验 | 200，4.0/8.0；简答题走 `rubric_llm`，其余 `deterministic` |
| 同幂等键重复提交 | 返回同一 `submission_id` |
| 新幂等键再提交 | 409 `QUIZ_NOT_OPEN` |
| 掌握度 / 错题本 / 复习目标 | 2 条掌握度、2 条 `low_score` 缺口、2 个 `weak_mastery` 目标 |
| 生成计划 | v1，4 个任务；每日 60 分钟；`pending → completed` 成功 |
| 终态任务回退 | 409 `INVALID_TASK_STATUS_TRANSITION` |
| 删除被框架引用的材料 | 409 `MATERIAL_IN_USE` |
| 容器重启后 | 课程、测验、计划、掌握度、上传文件仍在；`/api/health` 仍 200 |

## 4. 页面与设置

用系统 Edge + Playwright 1.64.1 无头模式访问 `http://127.0.0.1:7860`：

- 首页课程列表、总览（倒计时/今日任务/薄弱点/掌握度）、资料、知识框架、复习、复习计划、设置、全局检索均正常渲染。
- 演示横幅显示「演示模式 — 内置假模型，数据保存在本机」；原「操作不保存」与实际持久化行为不符，已修正。
- 计划页勾选待开始任务后变为「已完成」（PATCH 返回 200，页面重新拉取计划）。
- 设置页把模型名改为 `mock-stage8-ui` 并保存，提示「已保存，下一次出题/材料解析即使用新配置」；随后生成 1 题测验成功，证明保存的覆盖值被下一次 LLM 调用采用。
- 设置页不渲染 `database_url`/`storage_root`；API Key 仍只显示配置状态，不接受页面写入。
- 浏览器控制台只有 `/favicon.ico` 404，无 `pageerror`。

截图保存在工作区 `.deploy-test/screens/`：`02-dashboard.png`、`05-review.png`、`06-plan.png`、`07-settings.png`、`08-search.png`。

## 5. 环境注意事项

- 本机 Docker Desktop 原本配置了手工代理 `http://127.0.0.1:7897`，该代理不可用会导致拉取基础镜像失败。测试时临时把 `ProxyHTTPMode` 改为 `system`、清空 overrides，构建完成后已恢复原配置。
- `npm ci` 对 `jsdom@30.1.3` 等开发依赖提示 `EBADENGINE`（要求 Node `^24.15.0`，镜像固定 `24.13.0`），不影响 `vite build`；运行时镜像不包含这些开发依赖。
- 测试使用 mock LLM，题目为英文模板题；本报告验证的是部署、数据流和页面交互，不代表真实模型的内容质量。
- 测试容器 `studymate-test` / 卷 `studymate-test-data` 保留在本地，Docker Desktop 已停止；不需要时可执行：
  `docker rm -f studymate-test && docker volume rm studymate-test-data`。
