// 类型化端点（schema.d.ts 由 openapi/openapi.json 生成，npm run gen:types）
import type { components } from './schema'
import { request } from './client'

export type Health = components['schemas']['HealthResponse']
export type Settings = components['schemas']['SettingsResponse']
export type SettingsUpdate = components['schemas']['SettingsUpdateRequest']
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
export type KnowledgeScoredTree = components['schemas']['KnowledgeScoredTreeResponse']
export type KnowledgeScoredTreeNode = components['schemas']['KnowledgeScoredTreeNodeResponse']
export type KnowledgeHighlightItem = components['schemas']['KnowledgeHighlightItemResponse']
export type KnowledgeHighlights = components['schemas']['KnowledgeHighlightsResponse']
export type KnowledgeGraph = components['schemas']['KnowledgeGraphResponse']
export type KnowledgeGraphNode = components['schemas']['KnowledgeGraphNodeResponse']
export type KnowledgeGraphEdge = components['schemas']['KnowledgeGraphEdgeResponse']
export type KnowledgeMergeDecision = components['schemas']['KnowledgeMergeDecisionResponse']
export type KnowledgeAliasLock = components['schemas']['KnowledgeAliasLockResponse']
export type LLMCallSummary = components['schemas']['LLMCallSummaryResponse']
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

/** 保存服务地址/模型名/API Key 等运行时配置（Key 只写本机 local_secrets.json，不回传） */
export function updateSettings(body: SettingsUpdate) {
  return request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) })
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
  // ModelScope's gateway rejects DELETE; use the POST alias.
  return request<void>(`/api/courses/${courseId}/delete`, { method: 'POST' })
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
  // ModelScope's gateway rejects DELETE; use the POST alias.
  return request<void>(`/api/materials/${materialId}/delete`, { method: 'POST' })
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

/** 读取时评分树（scoring-v2）；未构建同样 404 RESOURCE_NOT_FOUND */
export function getKnowledgeTree(courseId: string) {
  return request<KnowledgeScoredTree>(`/api/courses/${courseId}/knowledge/tree`)
}

export function getKnowledgeHighlights(
  courseId: string,
  params: { limit?: number; order?: 'importance' | 'difficulty' | 'gap' } = {},
) {
  const query = new URLSearchParams()
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.order != null) query.set('order', params.order)
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return request<KnowledgeHighlights>(`/api/courses/${courseId}/knowledge/highlights${suffix}`)
}

export function getKnowledgeGraph(courseId: string) {
  return request<KnowledgeGraph>(`/api/courses/${courseId}/knowledge/graph`)
}

export function listKnowledgeMergeDecisions(courseId: string) {
  return request<components['schemas']['KnowledgeMergeDecisionsResponse']>(
    `/api/courses/${courseId}/knowledge/merge-decisions`,
  )
}

export function listKnowledgeAliasLocks(courseId: string) {
  return request<KnowledgeAliasLock[]>(`/api/courses/${courseId}/knowledge/alias-locks`)
}

export function addKnowledgeAliasLock(
  courseId: string,
  body: components['schemas']['KnowledgeAliasLockRequest'],
) {
  return request<components['schemas']['KnowledgeAliasLockResponse']>(
    `/api/courses/${courseId}/knowledge/alias-locks`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

/** 魔搭网关拒绝 DELETE；线上统一走 POST /alias-locks/delete（幂等） */
export function deleteKnowledgeAliasLock(
  courseId: string,
  body: components['schemas']['KnowledgeAliasLockRequest'],
) {
  return request<void>(`/api/courses/${courseId}/knowledge/alias-locks/delete`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getJobLLMCalls(jobId: string) {
  return request<LLMCallSummary>(`/api/jobs/${jobId}/llm-calls`)
}

export function getKnowledgeNode(nodeId: string) {
  return request<KnowledgeNodeDetail>(`/api/knowledge/${nodeId}`)
}

export function listKnowledgeVersions(courseId: string) {
  return request<KnowledgeVersion[]>(`/api/courses/${courseId}/knowledge/versions`)
}

export function listMastery(courseId: string) {
  return request<MasteryState[]>(`/api/courses/${courseId}/mastery`)
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
