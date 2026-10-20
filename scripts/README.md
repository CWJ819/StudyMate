# Scripts

这里放**需要手动执行、会请求运行中后端**的辅助脚本，不属于 pytest 套件。

- `smoke/f4_plans.py`：F4 计划接口冒烟，使用固定课程 ID，会修改开发库中的计划/任务。
- `smoke/f5_full_chain.py`：F5 全链路冒烟（建课 → 上传 → 建框架 → 出题 → 提交 → 掌握度 → 复习目标 → 计划 → 清理课程），使用 `tests/fixtures/f1-sample.pdf`。
- `fixtures/make_sample_pdf.py`：重新生成 `tests/fixtures/f1-sample.pdf`（3 页，第 2 页无文本）。

运行前先启动后端：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后在仓库根目录执行：

```bash
python scripts/smoke/f4_plans.py
python scripts/smoke/f5_full_chain.py
```
