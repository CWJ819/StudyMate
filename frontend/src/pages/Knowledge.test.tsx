// 知识框架页：404 空态 / 树 + 掌握度叠加 / 节点详情 + 来源内联展开 / 构建流 / 失败态
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import {
  frameworkActive,
  jobFailed,
  jobSucceeded,
  nodeDetailKn2,
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
      built
        ? HttpResponse.json(frameworkActive)
        : HttpResponse.json(
            {
              error: { code: 'RESOURCE_NOT_FOUND', message: 'no framework', request_id: 'r1' },
            },
            { status: 404 },
          ),
    ),
  )
  server.use(
    http.post('*/api/courses/c1/knowledge/build', () => {
      built = true
      return HttpResponse.json(
        { job_id: 'job-ok', framework_version_id: 'fv1', status: 'building' },
        { status: 201 },
      )
    }),
  )
  server.use(http.get('*/api/jobs/job-ok', () => HttpResponse.json(jobSucceeded)))

  renderKnowledge()
  expect(await screen.findByText('还没有知识框架')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '构建知识框架' }))
  // job 成功 → 失效刷新 → 框架出现
  expect(await screen.findByText('慢启动与拥塞避免', {}, { timeout: 3000 })).toBeTruthy()
})

test('已有框架：渲染树与掌握度叠加，选中节点看详情与来源展开', async () => {
  server.use(
    http.get('*/api/knowledge/:nodeId', ({ params }) =>
      params.nodeId === 'kn2' ? HttpResponse.json(nodeDetailKn2) : HttpResponse.json({
        ...nodeDetailKn2,
        knowledge_node_id: String(params.nodeId),
        title: '运输层',
        content: null,
        sources: [],
        relations: [],
      }),
    ),
  )
  renderKnowledge()

  // 树 + 版本头
  expect(await screen.findByText('慢启动与拥塞避免')).toBeTruthy()
  expect(screen.getByText('4 个知识点')).toBeTruthy()
  // 掌握度叠加：kn2 有记录，kn3 未测验
  expect(screen.getByText('0.42·3')).toBeTruthy()
  expect(screen.getByText('未测验')).toBeTruthy()

  // 点选叶子节点 → 详情
  fireEvent.click(screen.getByText('慢启动与拥塞避免'))
  expect(await screen.findByText(/慢启动阶段 cwnd 指数增长/)).toBeTruthy()
  expect(screen.getByText(/出处（1）/)).toBeTruthy()

  // 来源 → 内联展开显示 chunk 完整原文，再次点击收起
  const sourceButton = screen.getByRole('button', { name: /运输层讲义\.pdf · 第 18 页/ })
  fireEvent.click(sourceButton)
  expect(await screen.findByText(/完整原文，比搜索摘要长/)).toBeTruthy()
  expect(sourceButton.getAttribute('aria-expanded')).toBe('true')
  fireEvent.click(sourceButton)
  expect(screen.queryByText(/完整原文，比搜索摘要长/)).toBeNull()
  expect(sourceButton.getAttribute('aria-expanded')).toBe('false')
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
  await screen.findByText('慢启动与拥塞避免')

  fireEvent.click(screen.getByRole('button', { name: '版本列表' }))
  // 等第二行（v2）出现，避免把页头的 v3 当成列表行
  expect(await screen.findByText('v2')).toBeTruthy()
  expect(screen.getAllByText('v3').length).toBeGreaterThanOrEqual(2)
  expect(screen.getByText('失败', { exact: false })).toBeTruthy()
})
