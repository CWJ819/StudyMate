// 知识框架页：404 空态 / 树 + 掌握度叠加 / 节点详情 + 来源内联展开 / 构建流 / 失败态 /
// 侧栏分组（层级树默认只展开根；平铺旧框架按来源文档分组 + 组内前 20 条分批，报告 §5.3.3）
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import {
  frameworkActive,
  frameworkFlat,
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
  // job 成功 → 失效刷新 → 框架出现（层级树默认只展开根，先看到文档层）
  expect(await screen.findByText('拥塞控制', {}, { timeout: 3000 })).toBeTruthy()
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

  // 树 + 版本头；默认只展开根（文档组收起）
  expect(await screen.findByText('拥塞控制')).toBeTruthy()
  expect(screen.getByText('4 个知识点')).toBeTruthy()
  expect(screen.queryByText('慢启动与拥塞避免')).toBeNull()

  // 组头计数徽标（后代 N 个 · 已测 M）
  expect(screen.getByText('2 个 · 已测 1')).toBeTruthy() // 根
  expect(screen.getByText('1 个 · 已测 1')).toBeTruthy() // 拥塞控制

  // 展开文档组 → 叶子可见 + 掌握度叠加 + 行内页码
  fireEvent.click(screen.getByRole('button', { name: '展开' }))
  expect(await screen.findByText('慢启动与拥塞避免')).toBeTruthy()
  expect(screen.getByText('0.42·3')).toBeTruthy()
  expect(screen.getByText('未测验')).toBeTruthy()
  expect(screen.getByText('P18')).toBeTruthy()

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

  // 全部收起 → 组折叠；全部展开 → 恢复（卡头按钮，操作所有组；断言限定在树内，
  // 选中节点的标题/关联还会出现在右侧详情面板里）
  const treeSection = screen.getByRole('tree', { name: '知识框架树' })
  fireEvent.click(screen.getByRole('button', { name: '全部收起' }))
  expect(within(treeSection).queryByText('慢启动与拥塞避免')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '全部展开' }))
  expect(await within(treeSection).findByText('慢启动与拥塞避免')).toBeTruthy()
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
  await screen.findByText('拥塞控制')

  fireEvent.click(screen.getByRole('button', { name: '版本列表' }))
  // 等第二行（v2）出现，避免把页头的 v3 当成列表行
  expect(await screen.findByText('v2')).toBeTruthy()
  expect(screen.getAllByText('v3').length).toBeGreaterThanOrEqual(2)
  expect(screen.getByText('失败', { exact: false })).toBeTruthy()
})

test('平铺兜底分组：按来源文档分组、默认收起、组内前 20 条 + 展开其余 + 行内页码', async () => {
  server.use(
    http.get('*/api/courses/c1/knowledge', () => HttpResponse.json(frameworkFlat)),
    http.get('*/api/courses/c1/mastery', () =>
      HttpResponse.json([
        {
          knowledge_node_id: 'knf-0',
          title: 'MAC 知识点 01',
          alpha: 3.2,
          beta: 6.8,
          mastery_estimate: 0.31,
          evidence_count: 2,
          updated_at: '2026-01-03T11:00:00Z',
        },
      ]),
    ),
    http.get('*/api/knowledge/:nodeId', ({ params }) =>
      HttpResponse.json({
        ...nodeDetailKn2,
        knowledge_node_id: String(params.nodeId),
        title: `节点 ${params.nodeId}`,
        content: null,
        sources: [],
        relations: [],
      }),
    ),
  )
  renderKnowledge()

  // 组头：文件名 + N 个 + 已测 M；无来源归「未标注来源」；默认收起（叶子不可见）
  const macGroup = await screen.findByRole('button', { name: /第4章 MAC子层\.pdf/ })
  expect(macGroup.getAttribute('aria-expanded')).toBe('false')
  expect(screen.getByText('22 个 · 已测 1')).toBeTruthy()
  expect(screen.getByText('3 个')).toBeTruthy()
  expect(screen.getByRole('button', { name: /未标注来源/ })).toBeTruthy()
  expect(screen.queryByText('MAC 知识点 01')).toBeNull()

  // 展开 → 前 20 条 + 「展开其余 2 条」；行内 P{page}、掌握度叠加、未测验灰、truncate tooltip
  fireEvent.click(macGroup)
  expect(await screen.findByText('MAC 知识点 01')).toBeTruthy()
  expect(screen.getByText('MAC 知识点 20')).toBeTruthy()
  expect(screen.queryByText('MAC 知识点 21')).toBeNull()
  expect(screen.getByText('P3')).toBeTruthy()
  expect(screen.getByText('0.31·2')).toBeTruthy()
  expect(screen.getAllByText('未测验').length).toBeGreaterThan(0)
  expect(screen.getByTitle('MAC 知识点 01')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: /展开其余 2 条/ }))
  expect(screen.getByText('MAC 知识点 22')).toBeTruthy()

  // 兜底分组不改节点 ID：选中叶子仍按 ID 查详情
  fireEvent.click(screen.getByText('MAC 知识点 05'))
  expect(await screen.findByText('节点 knf-4')).toBeTruthy()
})

test('平铺兜底分组：全部展开 / 全部收起', async () => {
  server.use(
    http.get('*/api/courses/c1/knowledge', () => HttpResponse.json(frameworkFlat)),
  )
  renderKnowledge()
  await screen.findByRole('button', { name: /第4章 MAC子层\.pdf/ })

  fireEvent.click(screen.getByRole('button', { name: '全部展开' }))
  expect(await screen.findByText('MAC 知识点 22')).toBeTruthy()
  expect(screen.getByText('未标注来源的知识点')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '全部收起' }))
  expect(screen.queryByText('MAC 知识点 01')).toBeNull()
  expect(screen.queryByText('未标注来源的知识点')).toBeNull()
})
