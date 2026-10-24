// 测验：提交体形状 / 幂等键复用 / 草稿与结果持久化 / 出题默认勾选叶子
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { quizOpen, quizSubmission } from '../test/fixtures'
import { deepestText } from '../test/matchers'
import { QuizPage } from './Quiz'

const RECENT_KEY = 'studymate:recent-quiz:c1'

function renderQuiz(route = '/courses/c1/quiz') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/courses/:courseId/quiz" element={<QuizPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('提交体形状：单选/多选发 selected_option_ids（空白发 []），简答发 text（空白发 ""），带幂等键', async () => {
  localStorage.setItem(RECENT_KEY, 'qz1')
  let submitted: {
    idempotency_key?: string
    answers?: Array<{ question_id: string; selected_option_ids?: string[]; text?: string }>
  } | null = null
  server.use(
    http.post('*/api/quizzes/qz1/submit', async ({ request }) => {
      submitted = (await request.json()) as NonNullable<typeof submitted>
      return HttpResponse.json(quizSubmission)
    }),
  )

  renderQuiz()
  expect(await screen.findByText(/每经过一个 RTT/)).toBeTruthy()

  // Q1 单选选第一项；Q2 留空；Q3 多选两项；Q4 简答留空
  fireEvent.click(screen.getByRole('button', { name: /^指数增长$/ }))
  fireEvent.click(screen.getByRole('button', { name: /^慢启动$/ }))
  fireEvent.click(screen.getByRole('button', { name: /^拥塞避免$/ }))
  fireEvent.click(screen.getByRole('button', { name: '提交答卷' }))

  expect(await screen.findByText(deepestText(/待批改 1/))).toBeTruthy()
  expect(submitted!.idempotency_key).toBeTruthy()
  const answers = submitted!.answers!
  expect(answers.find((a) => a.question_id === 'q1')!.selected_option_ids).toEqual(['q1o1'])
  expect(answers.find((a) => a.question_id === 'q2')!.selected_option_ids).toEqual([])
  expect(answers.find((a) => a.question_id === 'q3')!.selected_option_ids).toEqual([
    'q3o1',
    'q3o2',
  ])
  expect(answers.find((a) => a.question_id === 'q4')!.text).toBe('')
})

test('503 提交失败：保留答案，重试复用同一幂等键，成功后进入结果页', async () => {
  localStorage.setItem(RECENT_KEY, 'qz1')
  const keys: string[] = []
  let calls = 0
  server.use(
    http.post('*/api/quizzes/qz1/submit', async ({ request }) => {
      calls += 1
      const body = (await request.json()) as { idempotency_key: string }
      keys.push(body.idempotency_key)
      if (calls === 1) {
        return HttpResponse.json(
          {
            error: {
              code: 'LLM_TIMEOUT',
              message: 'llm timeout',
              details: null,
              request_id: 'r-to',
            },
          },
          { status: 503 },
        )
      }
      return HttpResponse.json(quizSubmission)
    }),
  )

  renderQuiz()
  expect(await screen.findByText(/每经过一个 RTT/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /^指数增长$/ }))
  fireEvent.click(screen.getByRole('button', { name: '提交答卷' }))

  // 503 → 可重试提示 + 答案保留说明
  expect(await screen.findByText(/模型响应超时/)).toBeTruthy()
  expect(screen.getByRole('button', { name: /指数增长/ }).getAttribute('aria-pressed')).toBe(
    'true',
  )

  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByText(deepestText(/待批改 1/))).toBeTruthy()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
})

test('提交快照：提交期间锁定作答控件，结果页只显示已提交答案（事后改草稿不影响）', async () => {
  localStorage.setItem(RECENT_KEY, 'qz1')
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  server.use(
    http.post('*/api/quizzes/qz1/submit', async () => {
      await gate
      return HttpResponse.json(quizSubmission)
    }),
  )

  const view = renderQuiz()
  expect(await screen.findByText(/每经过一个 RTT/)).toBeTruthy()

  // 简答（Q4）填写后提交
  fireEvent.change(screen.getByLabelText('Q4 作答'), {
    target: { value: '窗口取 min(rwnd, cwnd)' },
  })
  fireEvent.click(screen.getByRole('button', { name: '提交答卷' }))

  // 提交进行中：按钮变“提交中…”，作答控件已锁定（活草稿没有编辑机会）
  expect(await screen.findByRole('button', { name: '提交中…' })).toBeTruthy()
  expect((screen.getByLabelText('Q4 作答') as HTMLTextAreaElement).disabled).toBe(true)
  expect(
    (screen.getByRole('button', { name: /^指数增长$/ }) as HTMLButtonElement).disabled,
  ).toBe(true)

  release()
  expect(await screen.findByText(deepestText(/待批改 1/))).toBeTruthy()
  expect(screen.getByText('窗口取 min(rwnd, cwnd)')).toBeTruthy()

  // 模拟“提交后草稿被改动”的分叉：手改 answers，submittedAnswers 保持快照
  const draftKey = 'studymate:quiz-draft:qz1'
  const raw = JSON.parse(localStorage.getItem(draftKey)!) as {
    answers: Record<string, { text?: string }>
    submittedAnswers: Record<string, { text?: string }>
  }
  expect(raw.submittedAnswers.q4!.text).toBe('窗口取 min(rwnd, cwnd)')
  raw.answers.q4 = { text: '提交后被篡改的答案' }
  localStorage.setItem(draftKey, JSON.stringify(raw))

  view.unmount()
  renderQuiz()
  expect(await screen.findByText(deepestText(/待批改 1/))).toBeTruthy()
  // 结果页只显示冻结快照，不显示被篡改的活草稿
  expect(screen.getByText('窗口取 min(rwnd, cwnd)')).toBeTruthy()
  expect(screen.queryByText('提交后被篡改的答案')).toBeNull()
})

test('刷新后结果仍在：草稿含 submission 时直接渲染结果页（不依赖重新提交）', async () => {
  localStorage.setItem(RECENT_KEY, 'qz1')
  localStorage.setItem(
    'studymate:quiz-draft:qz1',
    JSON.stringify({
      idempotencyKey: 'key-fixed',
      answers: { q1: { selected_option_ids: ['q1o1'] } },
      submission: quizSubmission,
    }),
  )

  renderQuiz()
  expect(await screen.findByText(deepestText(/待批改 1/))).toBeTruthy()
  // 答错的 Q2 默认展开（反馈可见），答对的 Q1 默认折叠
  expect(screen.getByText(/漏选了快重传/)).toBeTruthy()
  expect(screen.getAllByText('批改反馈').length).toBeGreaterThanOrEqual(2)
  // 提交按钮不再出现（结果页不可重复提交）
  expect(screen.queryByRole('button', { name: '提交答卷' })).toBeNull()
})

test('结果页：题卡左指示条与四种结果对应，汇总行带同色圆点', async () => {
  localStorage.setItem(RECENT_KEY, 'qz1')
  localStorage.setItem(
    'studymate:quiz-draft:qz1',
    JSON.stringify({
      idempotencyKey: 'key-fixed',
      answers: {},
      submission: quizSubmission,
    }),
  )

  renderQuiz()
  expect(await screen.findByText(deepestText(/待批改 1/))).toBeTruthy()

  const rowClass = (label: string) => {
    const chip = screen.getAllByText(label).find((el) => el.closest('button') != null)
    return chip?.closest('button')?.parentElement?.className ?? ''
  }
  expect(rowClass('答对')).toContain('border-l-success')
  expect(rowClass('答错')).toContain('border-l-error')
  expect(rowClass('部分得分')).toContain('border-l-warning')
  expect(rowClass('待批改')).toContain('border-l-untested')

  const dots = Array.from(document.querySelectorAll('span.size-2.rounded-full')).map(
    (el) => el.className,
  )
  expect(dots.some((c) => c.includes('bg-success'))).toBe(true)
  expect(dots.some((c) => c.includes('bg-error'))).toBe(true)
  expect(dots.some((c) => c.includes('bg-warning'))).toBe(true)
  expect(dots.some((c) => c.includes('bg-untested'))).toBe(true)
})

test('出题：默认全选叶子时省略 ids（后端缺省=全部，避开 50 个上限），部分选择才携带', async () => {
  let generated: { knowledge_node_ids?: string[]; question_count?: number; question_types?: string[] } | null =
    null
  server.use(
    http.post('*/api/courses/c1/quiz/generate', async ({ request }) => {
      generated = (await request.json()) as NonNullable<typeof generated>
      return HttpResponse.json(
        { quiz_id: 'qz2', job_id: 'job-ok', status: 'building' },
        { status: 202 },
      )
    }),
  )
  let qz2Calls = 0
  server.use(
    http.get('*/api/quizzes/qz2', () => {
      qz2Calls += 1
      return HttpResponse.json(
        qz2Calls === 1
          ? { ...quizOpen, quiz_id: 'qz2', status: 'building', questions: [] }
          : { ...quizOpen, quiz_id: 'qz2' },
      )
    }),
  )

  renderQuiz()
  expect(await screen.findByText('还没有测验')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '+ 新出题' }))
  // 两个叶子默认勾选，非叶子（拥塞控制）不出现在范围里
  const boxes = screen
    .getAllByRole('checkbox')
    .filter((el) => (el as HTMLInputElement).checked)
  expect(boxes.length).toBeGreaterThanOrEqual(5) // 2 叶子 + 3 题型
  expect(screen.queryByLabelText(/拥塞控制/)).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: '生成测验' }))
  expect(await screen.findByText('正在根据所选知识点出题，完成后自动刷新…')).toBeTruthy()
  expect(generated!.knowledge_node_ids).toBeUndefined()
  expect(generated!.question_types).toHaveLength(3)
  expect(generated!.question_count).toBe(10)
  expect(localStorage.getItem(RECENT_KEY)).toBe('qz2')

  // job-ok 成功（全局 handler）→ 失效 quiz 查询 → building 转 open，题目真实渲染
  expect(await screen.findByText(/每经过一个 RTT/, {}, { timeout: 4000 })).toBeTruthy()
})

test('出题：取消勾选一个叶子后，请求只带剩余叶子 id', async () => {
  let generated: { knowledge_node_ids?: string[] } | null = null
  server.use(
    http.post('*/api/courses/c1/quiz/generate', async ({ request }) => {
      generated = (await request.json()) as NonNullable<typeof generated>
      return HttpResponse.json(
        { quiz_id: 'qz3', job_id: 'job-ok', status: 'building' },
        { status: 202 },
      )
    }),
  )
  server.use(
    http.get('*/api/quizzes/qz3', () =>
      HttpResponse.json({ ...quizOpen, quiz_id: 'qz3', status: 'building' }),
    ),
  )

  renderQuiz()
  await screen.findByText('还没有测验')
  fireEvent.click(screen.getByRole('button', { name: '+ 新出题' }))
  fireEvent.click(screen.getByLabelText('慢启动与拥塞避免')) // 取消 kn2
  fireEvent.click(screen.getByRole('button', { name: '生成测验' }))
  expect(await screen.findByText('正在根据所选知识点出题，完成后自动刷新…')).toBeTruthy()
  expect(generated!.knowledge_node_ids).toEqual(['kn3'])
})
