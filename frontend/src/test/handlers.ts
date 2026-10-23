import { http, HttpResponse } from 'msw'
import {
  chunkDetail,
  course1,
  frameworkActive,
  graphFixture,
  healthOk,
  highlightsFixture,
  knowledgeVersions,
  masteryStates,
  materialsC1,
  mergeDecisionsFixture,
  nodeDetailKn2,
  planDetailActive,
  planDetailInactive,
  plansC1,
  quizOpen,
  scoredFramework,
  searchResults,
  settingsMock,
  wrongbookGaps,
} from './fixtures'

/** 任务状态迁移表（与 app/services/plan_service.py 一致；终态自环） */
const TASK_TRANSITIONS: Record<string, Set<string>> = {
  pending: new Set(['pending', 'in_progress', 'completed', 'skipped']),
  in_progress: new Set(['in_progress', 'completed', 'skipped']),
  completed: new Set(['completed']),
  skipped: new Set(['skipped']),
}

const allTasks = [...planDetailActive.tasks, ...planDetailInactive.tasks]

export const handlers = [
  http.get('*/api/health', () => HttpResponse.json(healthOk)),
  http.get('*/api/settings', () => HttpResponse.json(settingsMock)),
  http.get('*/api/courses', () => HttpResponse.json([course1])),
  http.get('*/api/courses/c1', () => HttpResponse.json(course1)),
  http.get('*/api/courses/c1/materials', () => HttpResponse.json(materialsC1)),
  http.get('*/api/courses/c1/search*', () => HttpResponse.json(searchResults)),
  http.get('*/api/chunks/ch1', () => HttpResponse.json(chunkDetail)),
  // 知识框架
  http.get('*/api/courses/c1/knowledge', () => HttpResponse.json(frameworkActive)),
  http.get('*/api/courses/c1/knowledge/tree', () => HttpResponse.json(scoredFramework)),
  http.get('*/api/courses/c1/knowledge/highlights*', () => HttpResponse.json(highlightsFixture)),
  http.get('*/api/courses/c1/knowledge/graph', () => HttpResponse.json(graphFixture)),
  http.get('*/api/courses/c1/knowledge/merge-decisions', () => HttpResponse.json(mergeDecisionsFixture)),
  http.get('*/api/courses/c1/knowledge/alias-locks', () => HttpResponse.json([])),
  http.post('*/api/courses/c1/knowledge/alias-locks', async ({ request }) => {
    const body = (await request.json()) as { title_a: string; title_b: string }
    return HttpResponse.json({ course_id: 'c1', ...body })
  }),
  http.post('*/api/courses/c1/knowledge/alias-locks/delete', () => new HttpResponse(null, { status: 204 })),
  http.get('*/api/knowledge/:nodeId', ({ params }) =>
    params.nodeId === 'kn2'
      ? HttpResponse.json(nodeDetailKn2)
      : HttpResponse.json({
          ...nodeDetailKn2,
          knowledge_node_id: String(params.nodeId),
          title: '运输层',
          content: null,
          sources: [],
          relations: [],
        }),
  ),
  http.get('*/api/courses/c1/knowledge/versions', () => HttpResponse.json(knowledgeVersions)),
  http.get('*/api/courses/c1/mastery', () => HttpResponse.json(masteryStates)),
  // 测验与复习
  http.get('*/api/quizzes/qz1', () => HttpResponse.json(quizOpen)),
  http.get('*/api/courses/c1/wrongbook', () => HttpResponse.json(wrongbookGaps)),
  // 复习计划
  http.get('*/api/courses/c1/plans', () => HttpResponse.json(plansC1)),
  http.get('*/api/plans/:planId', ({ params }) =>
    params.planId === 'pl1'
      ? HttpResponse.json(planDetailActive)
      : params.planId === 'pl0'
        ? HttpResponse.json(planDetailInactive)
        : HttpResponse.json(
            { error: { code: 'RESOURCE_NOT_FOUND', message: 'Study plan not found.' } },
            { status: 404 },
          ),
  ),
  http.patch('*/api/tasks/:taskId', async ({ params, request }) => {
    const task = allTasks.find((t) => t.id === params.taskId)
    if (!task) {
      return HttpResponse.json(
        { error: { code: 'RESOURCE_NOT_FOUND', message: 'Study task not found.' } },
        { status: 404 },
      )
    }
    const body = (await request.json()) as { status: string }
    const allowed = TASK_TRANSITIONS[task.status] ?? new Set([task.status])
    if (!allowed.has(body.status)) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_TASK_STATUS_TRANSITION',
            message: 'Study task status transition is not allowed.',
            details: { from: task.status, to: body.status },
          },
        },
        { status: 409 },
      )
    }
    return HttpResponse.json({ ...task, status: body.status })
  }),
]
