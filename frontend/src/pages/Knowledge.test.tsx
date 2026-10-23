// 知识框架页（Phase 4 前端轮）：章节树 scored tree / 重难点 / 关系图 / 整合记录。
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import {
  frameworkActive,
  graphFixture,
  highlightsFixture,
  jobFailed,
  jobSucceeded,
  mergeDecisionsFixture,
  nodeDetailKn2,
  scoredFramework,
} from '../test/fixtures'
import { KnowledgePage } from './Knowledge'

function renderKnowledge() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/courses/c1/knowledge']}>
        <Routes>
          <Route path="/courses/:courseId/knowledge" element={<KnowledgePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('未构建（404 RESOURCE_NOT_FOUND）：显示空状态而非报错，可发起构建', async () => {
  let built = false
  server.use(
    http.get('*/api/courses/c1/knowledge', () =>
      built ? HttpResponse.json(frameworkActive) : HttpResponse.json(
        { error: { code: 'RESOURCE_NOT_FOUND', message: 'no framework', request_id: 'r1' } },
        { status: 404 },
      ),
    ),
    http.get('*/api/courses/c1/knowledge/tree', () =>
      built ? HttpResponse.json(scoredFramework) : HttpResponse.json(
        { error: { code: 'RESOURCE_NOT_FOUND', message: 'no framework', request_id: 'r1' } },
        { status: 404 },
      ),
    ),
    http.post('*/api/courses/c1/knowledge/build', () => {
      built = true
      return HttpResponse.json(
        { job_id: 'job-ok', framework_version_id: 'fv1', status: 'building' },
        { status: 202 },
      )
    }),
    http.get('*/api/jobs/job-ok', () => HttpResponse.json(jobSucceeded)),
  )

  renderKnowledge()
  expect(await screen.findByText('还没有知识框架')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '构建知识框架' }))
  const treeSection = await screen.findByRole('tree', { name: '知识框架树' })
  expect(await within(treeSection).findByText('运输层')).toBeTruthy()
})

test('章节树：scored tree 展示重要度，详情展示分数块与 aliases', async () => {
  server.use(
    http.get('*/api/knowledge/kn2', () =>
      HttpResponse.json({ ...nodeDetailKn2, aliases: ['拥塞窗口控制'] }),
    ),
  )
  renderKnowledge()

  const treeSection = await screen.findByRole('tree', { name: '知识框架树' })
  expect(await within(treeSection).findByText('运输层')).toBeTruthy()
  expect(screen.getByText('2 个知识点')).toBeTruthy()
  expect(within(treeSection).getByText('重要度 0.82')).toBeTruthy()

  fireEvent.click(within(treeSection).getAllByRole('button', { name: '展开' })[0]!)
  expect(await within(treeSection).findByText('慢启动与拥塞避免')).toBeTruthy()
  fireEvent.click(within(treeSection).getByText('慢启动与拥塞避免'))

  expect(await screen.findByText(/慢启动阶段 cwnd 指数增长/)).toBeTruthy()
  expect(screen.getByText('别名')).toBeTruthy()
  expect(screen.getByText('拥塞窗口控制')).toBeTruthy()
  expect(screen.getAllByText('0.53').length).toBeGreaterThan(0)
  expect(screen.getByText('重要度')).toBeTruthy()
  expect(screen.getByText('难度')).toBeTruthy()
})

test('重难点：排序切换、未测验灰显、点击标题跳回树并选中', async () => {
  renderKnowledge()
  await screen.findByRole('tree', { name: '知识框架树' })

  fireEvent.click(screen.getByRole('tab', { name: '重难点' }))
  expect(await screen.findByText('慢启动与拥塞避免')).toBeTruthy()
  expect(screen.getByText('可靠传输：GBN 与 SR')).toBeTruthy()
  expect(screen.getAllByText('未测验').length).toBeGreaterThan(0)

  const gapButton = screen.getByRole('button', { name: '掌握缺口' })
  fireEvent.click(gapButton)
  expect(gapButton.getAttribute('aria-pressed')).toBe('true')
  fireEvent.change(screen.getByRole('combobox', { name: '显示数量' }), { target: { value: '10' } })

  fireEvent.click(await screen.findByRole('button', { name: '慢启动与拥塞避免' }))
  expect(await screen.findByText(/慢启动阶段 cwnd 指数增长/)).toBeTruthy()
  expect(screen.getByRole('tab', { name: '章节树' }).getAttribute('aria-selected')).toBe('true')
})

test('关系图：按类型筛选、依据展开、点节点 chip 跳树', async () => {
  renderKnowledge()
  await screen.findByRole('tree', { name: '知识框架树' })

  fireEvent.click(screen.getByRole('tab', { name: '关系图' }))
  expect(await screen.findByText('全部 1')).toBeTruthy()
  expect(screen.getByText('慢启动与拥塞避免')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '前置 1' }))
  fireEvent.click(screen.getByRole('button', { name: '展开依据' }))
  expect(await screen.findByText('慢启动是可靠传输的前置概念。')).toBeTruthy()

  fireEvent.click(screen.getAllByRole('button', { name: '慢启动与拥塞避免' })[0]!)
  expect(await screen.findByText(/慢启动阶段 cwnd 指数增长/)).toBeTruthy()
})

test('整合记录：显示合并决策、加锁与解锁', async () => {
  let locks: { title_a: string; title_b: string }[] = []
  server.use(
    http.get('*/api/courses/c1/knowledge/alias-locks', () => HttpResponse.json(locks)),
    http.post('*/api/courses/c1/knowledge/alias-locks', async ({ request }) => {
      const body = (await request.json()) as { title_a: string; title_b: string }
      locks = [body]
      return HttpResponse.json({ course_id: 'c1', ...body })
    }),
    http.post('*/api/courses/c1/knowledge/alias-locks/delete', () => {
      locks = []
      return new HttpResponse(null, { status: 204 })
    }),
  )

  renderKnowledge()
  await screen.findByRole('tree', { name: '知识框架树' })
  fireEvent.click(screen.getByRole('tab', { name: '整合记录' }))

  expect(await screen.findByText('拥塞控制')).toBeTruthy()
  expect(screen.getByText('相似')).toBeTruthy()
  expect(screen.getByText(/0\.91/)).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '禁止再合并' }))
  expect(await screen.findByText('已锁定的标题对')).toBeTruthy()
  expect(screen.getByText('拥塞控制算法')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '解锁' }))
  expect(await screen.findByText('已解锁。')).toBeTruthy()
  await waitFor(() => expect(screen.queryByText('已锁定的标题对')).toBeNull())
})

test('构建失败：显示 job.error_code 的中文文案', async () => {
  server.use(
    http.get('*/api/courses/c1/knowledge', () =>
      HttpResponse.json({ ...frameworkActive, status: 'failed' }),
    ),
  )
  server.use(http.get('*/api/jobs/job-bad', () => HttpResponse.json(jobFailed)))
  localStorage.setItem('studymate:job:knowledge:c1', 'job-bad')

  renderKnowledge()
  expect(await screen.findByText('模型响应超时，稍后可重试（答案已保留）')).toBeTruthy()
  expect(screen.getByRole('button', { name: '重新构建' })).toBeTruthy()

  localStorage.removeItem('studymate:job:knowledge:c1')
})

test('版本列表：展示版本与状态', async () => {
  renderKnowledge()
  await screen.findByRole('tree', { name: '知识框架树' })

  fireEvent.click(screen.getByRole('button', { name: '版本列表' }))
  expect(await screen.findByText('v2')).toBeTruthy()
  expect(screen.getAllByText('v3').length).toBeGreaterThanOrEqual(2)
  expect(screen.getByText('失败', { exact: false })).toBeTruthy()
})

test('知识页 fixture 与端点形状一致（防类型漂移）', () => {
  expect(scoredFramework.scoring_version).toBe('scoring-v2')
  expect(highlightsFixture.basis.scoring_version).toBe('scoring-v2')
  expect(graphFixture.edges[0]!.relation_type).toBe('prerequisite')
  expect(mergeDecisionsFixture.decisions[0]!.method).toBe('fuzzy')
})

