// 类型化端点（schema.d.ts 由 openapi/openapi.json 生成，npm run gen:types）
import type { components } from './schema'
import { request } from './client'

export type Health = components['schemas']['HealthResponse']
export type Settings = components['schemas']['SettingsResponse']
export type Course = components['schemas']['CourseResponse']
export type CourseCreate = components['schemas']['CourseCreateRequest']
export type CourseUpdate = components['schemas']['CourseUpdateRequest']
export type MaterialSummary = components['schemas']['MaterialSummaryResponse']
export type MaterialDetail = components['schemas']['MaterialDetailResponse']
export type MaterialUploadResult = components['schemas']['MaterialUploadResponse']
export type MaterialPage = components['schemas']['MaterialPageResponse']
export type ChunkDetail = components['schemas']['ChunkDetailResponse']
export type ChunkSearchResult = components['schemas']['ChunkSearchResult']
export type Job = components['schemas']['JobResponse']
export type KnowledgeBuildResult = components['schemas']['KnowledgeBuildResponse']
export type KnowledgeFramework = components['schemas']['KnowledgeFrameworkResponse']
export type KnowledgeTreeNode = components['schemas']['KnowledgeTreeNodeResponse']
export type KnowledgeNodeDetail = components['schemas']['KnowledgeNodeDetailResponse']
export type KnowledgeSource = components['schemas']['KnowledgeSourceResponse']
export type KnowledgeRelation = components['schemas']['KnowledgeRelationResponse']
export type KnowledgeVersion = components['schemas']['KnowledgeVersionResponse']
export type MasteryState = components['schemas']['MasteryStateResponse']
export type QuizGenerateResult = components['schemas']['QuizGenerateResponse']
export type QuizDetail = components['schemas']['QuizDetailResponse']
export type QuizQuestion = components['schemas']['QuizQuestionResponse']
export type QuizSubmission = components['schemas']['QuizSubmitResponse']
export type QuizQuestionResult = components['schemas']['QuizQuestionResultResponse']
export type KnowledgeGap = components['schemas']['KnowledgeGapResponse']
export type ReviewTarget = components['schemas']['ReviewTargetResponse']
export type StudyPlanSummary = components['schemas']['StudyPlanSummaryResponse']
export type StudyPlanDetail = components['schemas']['StudyPlanDetailResponse']
export type StudyTask = components['schemas']['StudyTaskResponse']
export type StudyTaskTarget = components['schemas']['StudyTaskTargetResponse']

export function getHealth() {
  return request<Health>('/api/health')
}

export function getSettings() {
  return request<Settings>('/api/settings')
}

// ---- 课程 ----

export function listCourses() {
  return request<Course[]>('/api/courses')
}

export function createCourse(body: CourseCreate) {
  return request<Course>('/api/courses', { method: 'POST', body: JSON.stringify(body) })
}

export function getCourse(courseId: string) {
  return request<Course>(`/api/courses/${courseId}`)
}

export function updateCourse(courseId: string, body: CourseUpdate) {
  return request<Course>(`/api/courses/${courseId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function deleteCourse(courseId: string) {
  return request<void>(`/api/courses/${courseId}`, { method: 'DELETE' })
}

// ---- 材料 ----

export function listMaterials(courseId: string) {
  return request<MaterialSummary[]>(`/api/courses/${courseId}/materials`)
}

/** multipart 字段名必须是 file（client 对 FormData 不设 Content-Type） */
export function uploadMaterial(courseId: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<MaterialUploadResult>(`/api/courses/${courseId}/materials`, {
    method: 'POST',
    body: form,
  })
}

export function getMaterial(materialId: string) {
  return request<MaterialDetail>(`/api/materials/${materialId}`)
}

export function deleteMaterial(materialId: string) {
  return request<void>(`/api/materials/${materialId}`, { method: 'DELETE' })
}

// ---- 检索与 chunk ----

export function searchChunks(courseId: string, q: string) {
  return request<ChunkSearchResult[]>(
    `/api/courses/${courseId}/search?q=${encodeURIComponent(q)}`,
  )
}

export function getChunk(chunkId: string) {
  return request<ChunkDetail>(`/api/chunks/${chunkId}`)
}

// ---- 作业（失败原因查询用；轮询 hook 在 F2 引入）----

export function getJob(jobId: string) {
  return request<Job>(`/api/jobs/${jobId}`)
}

// ---- 知识框架 ----

export function buildKnowledge(
  courseId: string,
  body: { reference_outline?: string } = {},
) {
  return request<KnowledgeBuildResult>(`/api/courses/${courseId}/knowledge/build`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** 未构建时后端返回 404 RESOURCE_NOT_FOUND（界面按空状态处理） */
export function getKnowledge(courseId: string) {
  return request<KnowledgeFramework>(`/api/courses/${courseId}/knowledge`)
}

export function getKnowledgeNode(nodeId: string) {
  return request<KnowledgeNodeDetail>(`/api/knowledge/${nodeId}`)
}

export function listKnowledgeVersions(courseId: string) {
  return request<KnowledgeVersion[]>(`/api/courses/${courseId}/knowledge/versions`)
}

export type KnowledgeIdentityMatch = {
  current_node_id: string
  current_title: string
  previous_node_id: string | null
  previous_title: string | null
  confidence: number
  match_type: string
  safe_to_migrate: boolean
}

export function getKnowledgeIdentityDiagnostics(courseId: string) {
  return request<{
    current_version_id: string
    previous_version_id: string | null
    matches: KnowledgeIdentityMatch[]
  }>(`/api/courses/${courseId}/knowledge/identity-diagnostics`)
}

export function listMastery(courseId: string) {
  return request<MasteryState[]>(`/api/courses/${courseId}/mastery`)
}

export type MasteryChapterSummary = {
  node_version_id: string
  title: string
  level: number
  section_path: string[]
  total_leaves: number
  tested_leaves: number
  untested_leaves: number
  coverage: number
  average_mastery: number | null
  low_mastery_leaves: number
  weak_density: number
  priority: number
}

export function getMasteryOverview(courseId: string) {
  return request<{ chapters: MasteryChapterSummary[] }>(
    `/api/courses/${courseId}/mastery/overview`,
  )
}

// ---- 测验 ----

export function generateQuiz(
  courseId: string,
  body: {
    knowledge_node_ids?: string[]
    question_count?: number
    question_types?: string[]
    difficulty?: string
  },
) {
  return request<QuizGenerateResult>(`/api/courses/${courseId}/quiz/generate`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getQuiz(quizId: string) {
  return request<QuizDetail>(`/api/quizzes/${quizId}`)
}

export function submitQuiz(
  quizId: string,
  body: components['schemas']['QuizSubmitRequest'],
) {
  return request<QuizSubmission>(`/api/quizzes/${quizId}/submit`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ---- 复习 ----

/** 知识缺口（错题本），bar 裸数组 */
export function getWrongbook(courseId: string) {
  return request<KnowledgeGap[]>(`/api/courses/${courseId}/wrongbook`)
}

export function postReviewTargets(
  courseId: string,
  body: { limit?: number; exploration_ratio?: number },
) {
  return request<components['schemas']['ReviewTargetsResponse']>(
    `/api/courses/${courseId}/review-targets`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

// ---- 复习计划（生成是同步 201，无 job；新版会停用旧版）----

export function createPlan(
  courseId: string,
  body: {
    exam_date: string
    daily_minutes: number
    target_score: number
    knowledge_node_ids?: string[]
  },
) {
  return request<StudyPlanDetail>(`/api/courses/${courseId}/plan`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listPlans(courseId: string) {
  return request<StudyPlanSummary[]>(`/api/courses/${courseId}/plans`)
}

export function getPlan(planId: string) {
  return request<StudyPlanDetail>(`/api/plans/${planId}`)
}

export function updateTask(taskId: string, body: { status: string }) {
  return request<StudyTask>(`/api/tasks/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}
