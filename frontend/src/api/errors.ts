// 错误码 → 中文文案与可重试标记（docs/frontend-plan.md §4.1）
// 未知 code 返回 null，界面回退显示后端英文 message 原文。

const RETRYABLE_CODES: ReadonlySet<string> = new Set([
  'LLM_TIMEOUT',
  'LLM_NETWORK_ERROR',
  'LLM_UPSTREAM_TEMPORARY',
  'LLM_OUTPUT_INVALID',
  // 前端合成的网络错误码，不属于后端契约
  'NETWORK_ERROR',
])

const MESSAGES: Record<string, string> = {
  VALIDATION_ERROR: '输入有误，请检查标红的字段',
  RESOURCE_NOT_FOUND: '内容不存在（或尚未创建）',
  MATERIALS_NOT_READY: '材料还未解析完成，请稍后再试',
  LLM_NOT_CONFIGURED: '尚未配置模型，请先在设置中配置',
  LLM_AUTH_FAILED: '模型鉴权失败，请检查 API Key',
  FILE_TOO_LARGE: '文件超出大小上限',
  INVALID_FILE_TYPE: '不支持的文件类型',
  INVALID_FILENAME: '文件名不合法',
  DOCUMENT_TOO_MANY_PAGES: '文档页数超出上限',
  // 2026-10-19 真后端冒烟发现：材料部分页提取失败时的材料级/页级错误码
  PARTIAL_EXTRACTION: '部分页面未能提取文本（详见逐页解析）',
  NO_EXTRACTABLE_TEXT: '该页没有可提取的文本（扫描图或图片页）',
  MATERIAL_IN_USE: '材料正被知识框架引用，不能删除',
  QUIZ_NOT_OPEN: '测验不在可作答状态，请刷新后重新出题',
  QUIZ_ALREADY_SUBMITTED: '测验已提交，不能重复提交',
  IDEMPOTENCY_CONFLICT: '重复请求冲突，请刷新页面',
  INVALID_OPTION_IDENTIFIER: '题目选项数据异常（程序错误）',
  QUIZ_GENERATION_INSUFFICIENT_UNIQUE: '可用题目不足，请减少题量或调整出题范围',
  LLM_OUTPUT_INVALID: '模型输出异常，可重试',
  LLM_REQUEST_FAILED: '模型请求失败，请稍后重试',
  LLM_TIMEOUT: '模型响应超时，稍后可重试（答案已保留）',
  LLM_NETWORK_ERROR: '模型服务网络异常，稍后可重试（答案已保留）',
  LLM_UPSTREAM_TEMPORARY: '模型服务暂时不可用，稍后可重试（答案已保留）',
  INVALID_PLAN_CONSTRAINTS: '计划参数不合法（考试日期不能早于今天）',
  PLAN_CAPACITY_EXCEEDED: '计划容量不足：请增加每日分钟数或推迟考试日期',
  INVALID_TASK_STATUS: '任务状态不合法',
  INVALID_TASK_STATUS_TRANSITION: '任务已完成或已跳过，不能再修改',
  DATABASE_SCHEMA_OUTDATED: '数据库结构过期，请执行 alembic upgrade head',
  INTERNAL_SERVER_ERROR: '服务器内部错误，请稍后重试',
  NETWORK_ERROR: '网络错误，请检查连接后重试',
  HTTP_404: '接口不存在（前后端契约不一致）',
  HTTP_405: '请求方法不被允许（前后端契约不一致）',
}

export function isRetryable(code: string): boolean {
  return RETRYABLE_CODES.has(code)
}

export function messageFor(code: string): string | null {
  return MESSAGES[code] ?? null
}
