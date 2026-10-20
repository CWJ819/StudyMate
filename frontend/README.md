# StudyMate 前端

课程复习智能体的 Web 前端：课程与资料 → 知识框架 → 测验与掌握度 → 复习计划与总览。

技术栈：React 19 + Vite 8 + TypeScript 5.9 + Tailwind CSS 4（`@theme` token）+ @tanstack/react-query 5 + react-router（HashRouter，后端只需 `StaticFiles(html=True)` 不需要 SPA fallback）。视觉基线为「今日清单」方向（纸白底 `#FBFBF9`、主色 `#0969DA`、水平课程 tab、边框分区无阴影），token 定义在 `src/styles.css`。

## 环境与命令

Node ≥ 24（本机在 conda 环境 `studymate` 内运行 npm）。所有依赖固定精确版本，`npm install` 即可复现。

```bash
npm install
npm run dev         # 开发服务器 http://localhost:5173，/api 代理到 127.0.0.1:8000
npm run test        # vitest（jsdom + msw），55 个用例
npm run typecheck   # tsc --noEmit
npm run build       # typecheck + vite build → dist/
npm run gen:types   # 由 openapi/openapi.json 重新生成 src/api/schema.d.ts
```

后端契约快照存放在 `openapi/openapi.json`；后端接口变更后先更新快照再 `gen:types`，`src/api/endpoints.ts` 里的类型与函数跟着改。错误码 → 中文文案集中在 `src/api/errors.ts`（有全量覆盖测试，后端新增码没补文案会红）。

## 与后端联调

```bash
# 后端（StudyMate 仓库根目录；首次或换库先 alembic upgrade head）
LLM_BASE_URL=mock://local python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`LLM_BASE_URL=mock://local` 是内置假模型：解析/出题/批改即时生成、不消耗 API 配额，页面顶部显示演示横幅，设置页（`#/settings`）解释退出方法。不配置 `LLM_BASE_URL` 时，涉及模型的功能会提示“尚未配置模型”。

## 目录结构

```text
src/
├─ api/        # client（信封错误/请求编号）、endpoints（类型化接口）、errors、status（状态→文案）
├─ components/ # AppShell（横幅/顶栏/全局检索/tab）、Drawer、ConfirmDialog、EmptyState、ErrorNotice
├─ hooks/      # useJob（轮询/超时/重试态）、usePersistedDraft（测验草稿与幂等键）
├─ lib/        # date（本地 YYYY-MM-DD）、tree（collectLeaves）
├─ pages/      # Courses / Dashboard / Materials / MaterialDetail / Knowledge / Quiz / Review / Plan / Settings
└─ test/       # msw handlers + fixtures（形状对齐后端 schema）
```

## 已知边界

- 检索是子串匹配（无相关度排序），客户端先显示 20 条再“显示更多”。
- 测验正确答案不随接口下发，结果页只展示你的答案与判分反馈。
- 掌握度是依据作答记录的估计值；“未测验”灰条 ≠ 薄弱。
- 未做 Playwright / 暗色模式 / i18n（延后，见 frontend-plan §7/§10）。
