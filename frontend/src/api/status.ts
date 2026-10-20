// 材料与页面状态 → 展示元数据；未知值回退显示原文（与 gap_type 同一原则）
import type { MaterialPage } from './endpoints'

export interface StatusMeta {
  label: string
  dot: string // 状态点颜色
}

const MATERIAL_STATUS: Record<string, StatusMeta> = {
  queued: { label: '排队', dot: 'bg-ink3' },
  processing: { label: '处理中', dot: 'bg-accent' },
  completed: { label: '完成', dot: 'bg-success' },
  completed_with_warnings: { label: '有警告完成', dot: 'bg-warning' },
  failed: { label: '失败', dot: 'bg-error' },
}

export function materialStatus(status: string): StatusMeta {
  return MATERIAL_STATUS[status] ?? { label: status, dot: 'bg-ink3' }
}

/** 材料是否仍在异步解析（列表轮询条件） */
export function isPending(status: string): boolean {
  return status === 'queued' || status === 'processing'
}

const PAGE_STATUS: Record<string, string> = {
  extracted: '已提取',
  empty: '空白页',
  no_extractable_text: '无可用文本',
}

export function pageStatus(status: string): string {
  return PAGE_STATUS[status] ?? status
}

export function pageStatusLabel(page: MaterialPage): string {
  return page.extraction_status === 'extracted'
    ? `已提取 ${page.text_length} 字`
    : pageStatus(page.extraction_status)
}

/** 上传预检：扩展名 .pdf/.pptx + 大小不超过 maxBytes（服务端为准，这里只挡明显问题） */
export function validateUploadFile(
  file: { name: string; size: number },
  maxBytes: number,
): string | null {
  const lower = file.name.toLowerCase()
  if (!lower.endsWith('.pdf') && !lower.endsWith('.pptx')) {
    return '只支持 .pdf / .pptx 课件'
  }
  if (file.size > maxBytes) {
    return `文件超出大小上限（${Math.floor(maxBytes / 1024 / 1024)} MB）`
  }
  if (file.size === 0) {
    return '文件是空的'
  }
  return null
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${Math.floor(bytes / 1024)} KB`
  return `${bytes} B`
}

// ---- 知识框架与作业状态（字面量取自 app/services/knowledge_service.py、job_repository.py）----

export const FRAMEWORK_STATUS: Record<string, StatusMeta> = {
  building: { label: '构建中', dot: 'bg-accent' },
  active: { label: '生效', dot: 'bg-success' },
  failed: { label: '失败', dot: 'bg-error' },
}

export function frameworkStatus(status: string): StatusMeta {
  return FRAMEWORK_STATUS[status] ?? { label: status, dot: 'bg-ink3' }
}

const JOB_STATUS: Record<string, string> = {
  queued: '排队',
  running: '运行中',
  retry_wait: '重试中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export function jobStatusLabel(status: string): string {
  return JOB_STATUS[status] ?? status
}

/** 作业终态：停止轮询 */
export function isJobTerminal(status: string): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

// ---- 测验与复习状态（字面量取自 app/schemas/quiz.py、mastery_service.py）----

const QUIZ_STATUS: Record<string, StatusMeta> = {
  building: { label: '出题中', dot: 'bg-accent' },
  open: { label: '待作答', dot: 'bg-ink2' },
  submitted: { label: '已提交', dot: 'bg-success' },
  failed: { label: '生成失败', dot: 'bg-error' },
}

export function quizStatus(status: string): StatusMeta {
  return QUIZ_STATUS[status] ?? { label: status, dot: 'bg-ink3' }
}

const GRADING_METHOD: Record<string, string> = {
  deterministic: '客观判分',
  rubric_llm: '模型批改',
}

export function gradingMethodLabel(method: string): string {
  return GRADING_METHOD[method] ?? method
}

/** gap_type 未知值回退显示原文（plan §5 复习行） */
const GAP_TYPE: Record<string, string> = {
  low_score: '近期答错',
  exploration_untested: '探索未测',
  weak_mastery: '估计偏低',
  coverage_check: '覆盖检查',
}

export function gapTypeLabel(gapType: string): string {
  return GAP_TYPE[gapType] ?? gapType
}

// ---- 计划与任务（字面量与迁移规则取自 app/services/plan_service.py）----

const PLAN_STATUS: Record<string, StatusMeta> = {
  active: { label: '进行中', dot: 'bg-success' },
  inactive: { label: '已停用', dot: 'bg-ink3' },
}

export function planStatus(status: string): StatusMeta {
  return PLAN_STATUS[status] ?? { label: status, dot: 'bg-ink3' }
}

const TASK_STATUS: Record<string, StatusMeta> = {
  pending: { label: '待开始', dot: 'bg-ink3' },
  in_progress: { label: '进行中', dot: 'bg-accent' },
  completed: { label: '已完成', dot: 'bg-success' },
  skipped: { label: '已跳过', dot: 'bg-ink3' },
}

export function taskStatus(status: string): StatusMeta {
  return TASK_STATUS[status] ?? { label: status, dot: 'bg-ink3' }
}

/** 终态任务只读：completed/skipped 不能再迁移 */
export function isTaskTerminal(status: string): boolean {
  return status === 'completed' || status === 'skipped'
}

/** 当前状态下允许迁往的状态（用于按钮）；终态为空 */
export function taskTransitions(status: string): string[] {
  if (status === 'pending') return ['in_progress', 'completed', 'skipped']
  if (status === 'in_progress') return ['completed', 'skipped']
  return []
}

const TASK_TRANSITION_LABEL: Record<string, string> = {
  in_progress: '开始',
  completed: '完成',
  skipped: '跳过',
}

export function taskTransitionLabel(to: string): string {
  return TASK_TRANSITION_LABEL[to] ?? to
}

const TASK_TYPE: Record<string, string> = {
  review: '复习',
  practice: '练习',
}

export function taskTypeLabel(taskType: string): string {
  return TASK_TYPE[taskType] ?? taskType
}
