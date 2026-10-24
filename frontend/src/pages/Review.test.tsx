// 复习：掌握度升序 + 未测验灰 / gap_type 回退原文 / 空态 / 复习目标→出题闭环
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { masteryStates, quizOpen } from '../test/fixtures'
import { ReviewPage } from './Review'
import { QuizPage } from './Quiz'
import { deepestText } from '../test/matchers'

function renderReview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/courses/c1/review']}>
        <Routes>
          <Route path="/courses/:courseId/review" element={<ReviewPage />} />
          <Route path="/courses/:courseId/quiz" element={<QuizPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('掌握度列表：已测验按估计升序，未测验默认折叠成计数行、展开后显示灰条', async () => {
  server.use(
    http.get('*/api/courses/c1/mastery', () =>
      HttpResponse.json([
        ...masteryStates,
        {
          knowledge_node_id: 'kn-extra',
          title: 'UDP 特点',
          alpha: 8,
          beta: 2,
          mastery_estimate: 0.8,
          evidence_count: 5,
          updated_at: '2026-01-03T11:00:00Z',
        },
      ]),
    ),
  )
  renderReview()
  // 0.42 在 0.80 前；kn3（叶子、无记录）默认折叠
  expect(await screen.findByText(/0\.42 · 依据 3 次作答/)).toBeTruthy()
  expect(screen.getByText(/0\.80 · 依据 5 次作答/)).toBeTruthy()
  expect(screen.getByText(deepestText(/未测验 1 个（不代表薄弱）· 展开/))).toBeTruthy()
  expect(screen.queryByText('未测验', { exact: true })).toBeNull()
  // 顺序：0.42 行出现在 0.80 行之前
  const all = document.body.textContent ?? ''
  expect(all.indexOf('0.42')).toBeLessThan(all.indexOf('0.80'))

  // 展开后出现未测验灰条
  fireEvent.click(screen.getByRole('button', { name: /未测验 1 个/ }))
  expect(await screen.findByText('未测验', { exact: true })).toBeTruthy()
  expect(screen.getByText(/收起未测验/)).toBeTruthy()
})

test('错题本：已知 gap_type 显示中文，未知值回退原文；空列表有空态', async () => {
  renderReview()
  expect(await screen.findByText('近期答错')).toBeTruthy()
  expect(screen.getByText('some_future_type')).toBeTruthy() // 未知值回退原文
  expect(screen.getByText(/作答 5 · 低分 3 · 答对 2 · 最近得分 0.4/)).toBeTruthy()

  // 空态
  server.use(http.get('*/api/courses/c1/wrongbook', () => HttpResponse.json([])))
  const client2 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { unmount } = render(
    <QueryClientProvider client={client2}>
      <MemoryRouter initialEntries={['/courses/c1/review']}>
        <Routes>
          <Route path="/courses/:courseId/review" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  unmount()
  const client3 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client3}>
      <MemoryRouter initialEntries={['/courses/c1/review']}>
        <Routes>
          <Route path="/courses/:courseId/review" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText(/还没有知识缺口记录/)).toBeTruthy()
})

test('复习目标：POST review-targets 后以目标节点出题，并跳到测验页', async () => {
  let targetsBody: unknown
  let generateBody: { knowledge_node_ids?: string[] } | null = null
  server.use(
    http.post('*/api/courses/c1/review-targets', async ({ request }) => {
      targetsBody = await request.json()
      return HttpResponse.json({
        strategy_log_id: 'sl1',
        strategy_version: 'v1',
        targets: [
          {
            knowledge_node_id: 'kn2',
            node_version_id: 'nv2',
            title: '慢启动与拥塞避免',
            priority: 1,
            mastery_estimate: 0.42,
            evidence_count: 3,
            reason: 'low_score',
          },
          {
            knowledge_node_id: 'kn3',
            node_version_id: 'nv3',
            title: '可靠传输：GBN 与 SR',
            priority: 2,
            mastery_estimate: null,
            evidence_count: 0,
            reason: 'exploration_untested',
          },
        ],
      })
    }),
  )
  server.use(
    http.post('*/api/courses/c1/quiz/generate', async ({ request }) => {
      generateBody = (await request.json()) as NonNullable<typeof generateBody>
      return HttpResponse.json(
        { quiz_id: 'qz-review', job_id: 'job-ok', status: 'building' },
        { status: 202 },
      )
    }),
  )
  server.use(
    http.get('*/api/quizzes/qz-review', () =>
      HttpResponse.json({ ...quizOpen, quiz_id: 'qz-review' }),
    ),
  )

  renderReview()
  expect(await screen.findByText('练一轮薄弱点')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '生成复习测验' }))

  // 跳转后测验页出现，且两次请求都带了目标节点
  expect(await screen.findByText(/每经过一个 RTT/)).toBeTruthy()
  await screen.findByText('练一轮薄弱点').catch(() => null)
  expect(targetsBody).toEqual({ limit: 10, exploration_ratio: 0.3 })
  expect(generateBody!.knowledge_node_ids).toEqual(['kn2', 'kn3'])
  expect(localStorage.getItem('studymate:recent-quiz:c1')).toBe('qz-review')
})
