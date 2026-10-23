# Scripts

这里放**需要手动执行、会请求运行中后端**的辅助脚本，不属于 pytest 套件。

- `smoke/f4_plans.py`：F4 计划接口冒烟，使用固定课程 ID，会修改开发库中的计划/任务。
- `smoke/f5_full_chain.py`：F5 全链路冒烟（建课 → 上传 → 建框架 → 出题 → 提交 → 掌握度 → 复习目标 → 计划 → 清理课程），使用 `tests/fixtures/f1-sample.pdf`。
- `smoke/p0_real_model.py`：P0 真实模型验收（三题型出题 → 含简答提交 → 幂等重放），需要真实 DeepSeek 配置和 8001 端口的临时后端，会创建并提交测验。
- `seed_demo_data.py`：在冻结结构上播种演示数据——默认两门本地课各生成 2 场 10 题单选、固定随机种子作答，断言掌握度/错题本/评分排序生效；也可用 `--course-id --expected-version --expected-leaves --api-base --token-env` 对线上课播种（token 只从环境变量读取，不打印）。只调测验与掌握度接口，不触发知识构建、不改设置，会写入目标库。
- `audit_framework.py`：只读审计一门课 active 框架的版本/图一致性（总 version 行、唯一 node 数、重复叶、不可达 version、重复逻辑边）；支持 `sqlite:///` 库，SQLite 上强制 `query_only`，用于跨 section 对齐修复前后的同口径对照。
- `fixtures/make_sample_pdf.py`：重新生成 `tests/fixtures/f1-sample.pdf`（3 页，第 2 页无文本）。

运行前先启动后端：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后在仓库根目录执行：

```bash
python scripts/smoke/f4_plans.py
python scripts/smoke/f5_full_chain.py
python scripts/smoke/p0_real_model.py
python scripts/audit_framework.py --course-id <course-uuid>
```

`p0_real_model.py` 默认请求 `http://127.0.0.1:8001/api`；运行前用同一份 `.env` 在 8001 启动一个临时后端，避免污染 8000 的开发库。
