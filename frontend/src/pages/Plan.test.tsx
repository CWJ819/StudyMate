// 复习计划：生成表单提交体与容量错误 / 按天分组合计分钟数 / 终态只读 / 非 active 只读
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { planDetailActive } from '../test/fixtures'
import { PlanPage } from './Plan'
import { addDaysISO, todayISO } from '../lib/date'

function renderPlan() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/courses/c1/plan']}>
        <Routes>
          <Route path="/courses/:courseId/plan" element={<PlanPage />} />
          <Route path="/courses/:courseId/knowledge" element={<div>knowledge</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function taskRow(title: string) {
  const row = screen.getByText(title).closest('[data-task-id]')
  expect(row).toBeTruthy()
  return within(row as HTMLElement)
}

function expectDisabled(el: HTMLElement, disabled: boolean) {
  expect((el as HTMLInputElement).disabled).toBe(disabled)
}

test('生成表单：全选叶子时省略 knowledge_node_ids（后端缺省=全部，避开 100 个上限）', async () => {
  let body: Record<string, unknown> | null = null
  const created = { ...planDetailActive, id: 'pl2', version_number: 3, tasks: [] }
  server.use(
    http.post('*/api/courses/c1/plan', async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json(created, { status: 201 })
    }),
    // 生成后页面会按新 id 拉详情
    http.get('*/api/plans/pl2', () => HttpResponse.json(created)),
  )

  renderPlan()
  expect(await screen.findByText('v2 计划', {}, { timeout: 3000 })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '生成新计划' }))

  // 改一下考试日期，其余用默认（60 分钟 / 85 分 / 全选）
  fireEvent.change(screen.getByLabelText(/考试日期/), {
    target: { value: addDaysISO(todayISO(), 21) },
  })
  fireEvent.click(screen.getByRole('button', { name: '生成计划' }))

  await screen.findByText('v3 计划', {}, { timeout: 3000 })
  expect(body).toEqual({
    exam_date: addDaysISO(todayISO(), 21),
    daily_minutes: 60,
    target_score: 85,
  })
})

test('生成表单：预算紧张时「按时间预算选」只提交可覆盖的叶子', async () => {
  let body: Record<string, unknown> | null = null
  const created = { ...planDetailActive, id: 'pl3', version_number: 4, tasks: [] }
  server.use(
    http.post('*/api/courses/c1/plan', async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json(created, { status: 201 })
    }),
    http.get('*/api/plans/pl3', () => HttpResponse.json(created)),
  )

  renderPlan()
  await screen.findByText('v2 计划', {}, { timeout: 3000 })
  fireEvent.click(screen.getByRole('button', { name: '生成新计划' }))
  fireEvent.change(screen.getByLabelText(/考试日期/), { target: { value: todayISO() } })
  fireEvent.change(screen.getByLabelText(/每日分钟数/), { target: { value: '15' } })
  fireEvent.click(screen.getByRole('button', { name: /按时间预算选/ }))
  fireEvent.click(screen.getByRole('button', { name: '生成计划' }))

  await screen.findByText('v4 计划', {}, { timeout: 3000 })
  const nodeIds = (body as { knowledge_node_ids?: string[] } | null)?.knowledge_node_ids
  expect(Array.isArray(nodeIds)).toBe(true)
  expect(nodeIds?.length).toBe(1)
})

test('容量不足（PLAN_CAPACITY_EXCEEDED）：显示需要/可用分钟数', async () => {
  server.use(
    http.post('*/api/courses/c1/plan', () =>
      HttpResponse.json(
        {
          error: {
            code: 'PLAN_CAPACITY_EXCEEDED',
            message: 'The requested plan cannot fit before the exam date within daily minutes.',
            details: { required_minutes: 600, available_minutes: 300 },
          },
        },
        { status: 409 },
      ),
    ),
  )

  renderPlan()
  await screen.findByText('v2 计划')
  fireEvent.click(screen.getByRole('button', { name: '生成新计划' }))
  fireEvent.click(screen.getByRole('button', { name: '生成计划' }))

  expect(await screen.findByText(/计划容量不足/)).toBeTruthy()
  expect(screen.getByText('到考前共需 600 分钟，可用 300 分钟')).toBeTruthy()
})

test('任务按天分组：每组显示合计分钟数且不超过每日上限', async () => {
  renderPlan()
  await screen.findByText('v2 计划')
  // 今天：t1 30 + t2 30；明天：t3 30 + t4 15 —— 都 ≤ 60
  expect(screen.getByText('合计 60 / 60 分钟')).toBeTruthy()
  expect(screen.getByText('合计 45 / 60 分钟')).toBeTruthy()
  expect(screen.getByText('今天', { exact: false })).toBeTruthy()
})

test('任务状态迁移：pending 有三个按钮，点「完成」发 PATCH；终态任务只读', async () => {
  let patchBody: { status?: string } | null = null
  server.use(
    http.patch('*/api/tasks/t1', async ({ request }) => {
      patchBody = (await request.json()) as { status?: string }
      return HttpResponse.json({ ...planDetailActive.tasks[0], status: 'completed' })
    }),
  )

  renderPlan()
  await screen.findByText('v2 计划')

  const pending = taskRow('Review 慢启动与拥塞避免')
  expect(pending.getByRole('button', { name: '开始' })).toBeTruthy()
  expect(pending.getByRole('button', { name: '跳过' })).toBeTruthy()
  fireEvent.click(pending.getByRole('button', { name: '完成' }))
  await waitFor(() => expect(patchBody).toEqual({ status: 'completed' }))

  // 终态（completed/skipped）无按钮、checkbox 禁用
  const completed = taskRow('Review 可靠传输：GBN 与 SR')
  expect(completed.queryByRole('button')).toBeNull()
  expectDisabled(completed.getByLabelText(/完成 Review 可靠传输/), true)
  const skipped = taskRow('Practice 可靠传输：GBN 与 SR')
  expect(skipped.queryByRole('button')).toBeNull()
  expectDisabled(skipped.getByLabelText(/完成 Practice 可靠传输/), true)
})

test('非 active 计划只读：切到 v1 后没有迁移按钮，并显示停用说明', async () => {
  renderPlan()
  await screen.findByText('v2 计划')

  const v1Button = Array.from(document.querySelectorAll('button')).find((b) =>
    b.textContent?.startsWith('v1'),
  )
  expect(v1Button).toBeTruthy()
  fireEvent.click(v1Button as HTMLElement)
  expect(await screen.findByText('v1 计划')).toBeTruthy()
  expect(screen.getByText(/此版本已停用/)).toBeTruthy()
  // 唯一任务是 completed：整卡只读，无任何迁移按钮
  expect(screen.queryByRole('button', { name: '开始' })).toBeNull()
  expect(screen.queryByRole('button', { name: '完成' })).toBeNull()
  expectDisabled(screen.getByLabelText(/完成 Review 慢启动/), true)
})
