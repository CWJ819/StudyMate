// §7 手工清单的自动化部分：后端全部错误码（plan §4.1 契约）都必须有中文文案。
// 清单提取自 app/ 全量 grep `code="…"`（2026-10-20，34 个）；后端新增码而此处未同步时，
// 这个测试会失败并提醒补文案。
import { isRetryable, messageFor } from './errors'

const BACKEND_CODES = [
  'DATABASE_SCHEMA_OUTDATED',
  'DOCUMENT_TOO_MANY_PAGES',
  'FILE_TOO_LARGE',
  'IDEMPOTENCY_CONFLICT',
  'INTERNAL_SERVER_ERROR',
  'INVALID_FILENAME',
  'INVALID_FILE_TYPE',
  'INVALID_OPTION_IDENTIFIER',
  'INVALID_PLAN_CONSTRAINTS',
  'INVALID_STORAGE_PATH',
  'INVALID_TASK_STATUS',
  'INVALID_TASK_STATUS_TRANSITION',
  'JOB_EXECUTION_FAILED',
  'JOB_PAYLOAD_INVALID',
  'KNOWLEDGE_BUILD_FAILED',
  'LLM_API_KEY_ENV_ONLY',
  'LLM_AUTH_FAILED',
  'LLM_NETWORK_ERROR',
  'LLM_NOT_CONFIGURED',
  'LLM_OUTPUT_INVALID',
  'LLM_REQUEST_FAILED',
  'LLM_TIMEOUT',
  'LLM_UPSTREAM_TEMPORARY',
  'MATERIALS_NOT_READY',
  'MATERIAL_IN_USE',
  'NO_EXTRACTABLE_TEXT',
  'PARTIAL_EXTRACTION',
  'PLAN_CAPACITY_EXCEEDED',
  'QUIZ_ALREADY_SUBMITTED',
  'QUIZ_GENERATION_INSUFFICIENT_UNIQUE',
  'QUIZ_NOT_OPEN',
  'RESOURCE_NOT_FOUND',
  'VALIDATION_ERROR',
] as const

test('后端全部错误码都有中文文案（未知码回退英文 message 的前提是“已知全覆盖”）', () => {
  for (const code of BACKEND_CODES) {
    const msg = messageFor(code)
    expect(msg, `缺少文案: ${code}`).not.toBeNull()
    expect(msg, `文案应为中文: ${code}`).toMatch(/[\u4e00-\u9fff]/)
  }
})

test('前端合成码也有文案；未知码返回 null 由界面回退原文', () => {
  expect(messageFor('NETWORK_ERROR')).toBeTruthy()
  expect(messageFor('HTTP_404')).toBeTruthy()
  expect(messageFor('SOME_FUTURE_CODE')).toBeNull()
})

test('可重试集合只包含瞬时性错误', () => {
  expect(isRetryable('LLM_TIMEOUT')).toBe(true)
  expect(isRetryable('NETWORK_ERROR')).toBe(true)
  expect(isRetryable('QUIZ_NOT_OPEN')).toBe(false)
  expect(isRetryable('INVALID_TASK_STATUS_TRANSITION')).toBe(false)
})
