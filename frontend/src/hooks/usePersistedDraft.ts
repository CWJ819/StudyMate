// localStorage 持久化状态（测验草稿/幂等键/最近 quiz_id）
// JSON 序列化；隐私模式等存储异常时静默退化为纯内存状态。
import { useCallback, useState } from 'react'
import type { QuizSubmission } from '../api/endpoints'

export function loadJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw == null ? null : (JSON.parse(raw) as T)
  } catch {
    return null
  }
}

export function saveJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 存储不可用时丢弃，不影响当前会话
  }
}

export function removeKey(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    // 忽略
  }
}

export function usePersistedDraft<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => loadJson<T>(key) ?? initial)
  const update = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved = typeof next === 'function' ? (next as (p: T) => T)(prev) : next
        saveJson(key, resolved)
        return resolved
      })
    },
    [key],
  )
  return [value, update] as const
}

// ---- 测验本地存储的键与形状 ----

export interface QuizDraft {
  /** 第一次点“提交”时生成；失败重试复用（plan §4.3） */
  idempotencyKey: string | null
  answers: Record<string, { selected_option_ids?: string[]; text?: string }>
  /** 首次提交时冻结的答案快照：重试必须同键同答案，结果页只显示这份，不受活草稿编辑影响 */
  submittedAnswers?: Record<string, { selected_option_ids?: string[]; text?: string }>
  /** 提交成功后保存响应；刷新后仍能看结果 */
  submission?: QuizSubmission
}

export const quizDraftKey = (quizId: string) => `studymate:quiz-draft:${quizId}`
export const recentQuizKey = (courseId: string) => `studymate:recent-quiz:${courseId}`
export const quizJobKey = (quizId: string) => `studymate:quiz-job:${quizId}`
