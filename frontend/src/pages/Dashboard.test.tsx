// 总览：并行卡片独立降级（一个数据源失败不拖垮其余）/ 无计划提示 / 知识框架 404 = 未构建 /
// 今日任务与倒计时取 active 计划 / 薄弱点点击联动掌握度行
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { frameworkActive, masteryStates, planDetailActive } from '../test/fixtures'
import { deepestText } from '../test/matchers'
import { DashboardPage } from './Dashboard'
import { addDaysISO, todayISO } from '../lib/date'

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/courses/c1/']}>
        <Routes>
          <Route path="/courses/:courseId" element={<DashboardPage />} />
          <Route path="/courses/:courseId/plan" element={<div>plan</div>} />
          <Route path="/courses/:courseId/knowledge" element={<div>knowledge</div>} />
          <Route path="/courses/:courseId/review" element={<div>review</div>} />
          <Route path="/courses/:courseId/quiz" element={<div>quiz</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const notFound = () =>
  HttpResponse.json(
    { error: { code: 'RESOURCE_NOT_FOUND', message: 'Knowledge framework not built.' } },
    { status: 404 },
  )

test('倒计时与今日任务取 active 计划：今天只有 t1/t2，勾选完成发 PATCH', async () => {
  let patchBody: { status?: string } | null = null
  server.use(
    http.patch('*/api/tasks/t1', async ({ request }) => {
      patchBody = (await request.json()) as { status?: string }
      return HttpResponse.json({ ...planDetailActive.tasks[0], status: 'completed' })
    }),
  )

  renderDashboard()
  // 考试日 = 今天 + 9
  expect(await screen.findByLabelText('距考试还有 9 天')).toBeTruthy()

  // 今天的两项任务（t1 待开始 / t2 进行中），明天的 t3/t4 不出现在今日卡
  expect(await screen.findByText('Review 慢启动与拥塞避免')).toBeTruthy()
  expect(screen.getByText('Practice 慢启动与拥塞避免')).toBeTruthy()
  expect(screen.queryByText('Review 可靠传输：GBN 与 SR')).toBeNull()
  expect(screen.getByText(deepestText(/合计 60 分钟 · 已完成 0 项/))).toBeTruthy()
  expect(screen.getByText('继续')).toBeTruthy() // t2 进行中 → 继续
  expect(screen.getByText('开始')).toBeTruthy() // t1 待开始 → 开始

  fireEvent.click(screen.getByLabelText('完成 Review 慢启动与拥塞避免'))
  await waitFor(() => expect(patchBody).toEqual({ status: 'completed' }))
})

test('任一数据源失败不影响其余卡片：mastery 500 时今日任务与倒计时照常', async () => {
  server.use(
    http.get('*/api/courses/c1/mastery', () =>
      HttpResponse.json(
        { error: { code: 'INTERNAL_SERVER_ERROR', message: 'boom' } },
        { status: 500 },
      ),
    ),
  )
  renderDashboard()

  // 掌握度卡显示自己的错误
  expect(await screen.findByText('服务器内部错误，请稍后重试')).toBeTruthy()
  // 其余卡片照常；薄弱点卡因掌握度缺失而显示降级文案
  expect(await screen.findByText('Review 慢启动与拥塞避免')).toBeTruthy()
  expect(screen.getByLabelText('距考试还有 9 天')).toBeTruthy()
  expect(screen.getAllByText('暂无掌握度记录').length).toBe(2)
})

test('无计划：倒计时提示设置考试日，今日任务为空态', async () => {
  server.use(http.get('*/api/courses/c1/plans', () => HttpResponse.json([])))
  renderDashboard()

  expect(await screen.findByText('还没有复习计划。')).toBeTruthy()
  expect(screen.getByText('设置考试日并生成计划 →')).toBeTruthy()
  expect(screen.getByText(/今天没有安排任务/)).toBeTruthy()
})

test('知识框架 404 = 未构建（不当作错误）：摘要与掌握度卡显示未构建提示', async () => {
  server.use(http.get('*/api/courses/c1/knowledge', notFound))
  renderDashboard()

  // 头部摘要段显示「知识框架未构建」，掌握度卡仍显示已测验记录并提示无法对比
  expect(await screen.findByText(/3 份资料 · 知识框架未构建/)).toBeTruthy()
  expect(screen.getByText(/估计 0\.42/)).toBeTruthy()
  expect(screen.getByText(/无法对比未测验知识点/)).toBeTruthy()
  expect(screen.getByLabelText('距考试还有 9 天')).toBeTruthy()
})

test('薄弱点点击联动掌握度行高亮（aria-pressed）', async () => {
  renderDashboard()
  // 薄弱点卡：慢启动 估计 0.42 · 依据 3 次作答（文本拆在 <b> 两侧，用整体文本断言）
  await waitFor(() =>
    expect(document.body.textContent).toContain('估计 0.42 · 依据 3 次作答'),
  )
  expect(document.querySelectorAll('[aria-pressed="true"]').length).toBe(0)

  const weakButton = Array.from(document.querySelectorAll('button')).find((b) =>
    b.textContent?.includes('依据 3 次作答'),
  )
  fireEvent.click(weakButton as HTMLElement)
  const pressed = document.querySelectorAll('[aria-pressed="true"]')
  expect(pressed.length).toBe(1)
  expect((pressed[0] as HTMLElement).textContent).toContain('0.42')
})

test('薄弱点联动到未测验节点：自动展开灰条区并高亮对应行', async () => {
  renderDashboard()
  // kn3 未测验，默认折叠成计数行
  await waitFor(() => expect(document.body.textContent).toContain('未测验 1 个（不代表薄弱）'))

  // gap2（未知 gap_type 回退原文 some_future_type）指向 kn3
  const weakGap = Array.from(document.querySelectorAll('button')).find((b) =>
    b.textContent?.includes('some_future_type'),
  )
  expect(weakGap).toBeTruthy()
  fireEvent.click(weakGap as HTMLElement)

  // 联动触发自动展开，目标行（而非折叠行）被高亮
  await waitFor(() => expect(document.body.textContent).toContain('收起未测验'))
  const pressed = document.querySelectorAll('[aria-pressed="true"]')
  expect(pressed.length).toBe(1)
  expect((pressed[0] as HTMLElement).textContent).toContain('可靠传输')
})

test('倒计时时间带：7 列、超载日红条、今天列 accent 边框', async () => {
  const tasks = [
    {
      ...planDetailActive.tasks[0]!,
      scheduled_date: addDaysISO(todayISO(), 0),
      estimated_minutes: 60,
    },
    {
      ...planDetailActive.tasks[0]!,
      id: 'over',
      scheduled_date: addDaysISO(todayISO(), 2),
      estimated_minutes: 90,
    },
  ]
  server.use(
    http.get('*/api/plans/pl1', () =>
      HttpResponse.json({ ...planDetailActive, tasks }),
    ),
  )

  renderDashboard()
  const band = await screen.findByTestId('plan-band')
  expect(within(band).getAllByTestId('plan-band-day')).toHaveLength(7)

  const fills = within(band).getAllByTestId('plan-band-fill')
  expect(fills[0]!.className).toContain('bg-accent')
  expect(fills[2]!.className).toContain('bg-error')

  const today = within(band).getByText('今天')
  const todayCol = today.closest('[data-testid="plan-band-day"]')
  expect(todayCol?.className).toContain('ring-accent')
})

test('薄弱点先于掌握度到达：数据就绪后联动自动补展开（不再静默失效）', async () => {
  // mastery/knowledge 被闸门延迟，wrongbook 立即返回——复现首屏窗口期点击
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  server.use(
    http.get('*/api/courses/c1/mastery', async () => {
      await gate
      return HttpResponse.json(masteryStates)
    }),
    http.get('*/api/courses/c1/knowledge', async () => {
      await gate
      return HttpResponse.json(frameworkActive)
    }),
  )

  renderDashboard()
  // 薄弱点卡先渲染（gap2 → kn3，未测验节点）
  await waitFor(() => expect(document.body.textContent).toContain('some_future_type'))

  // 数据未就绪时点击：此刻 untestedLeaves 还是空的（旧实现会静默失效且无法恢复）
  const weakGap = Array.from(document.querySelectorAll('button')).find((b) =>
    b.textContent?.includes('some_future_type'),
  )
  expect(weakGap).toBeTruthy()
  fireEvent.click(weakGap as HTMLElement)

  // 数据到达后 effect 按 dataUpdatedAt 重算：自动展开灰条区并高亮 kn3
  release()
  await waitFor(() => expect(document.body.textContent).toContain('收起未测验'))
  const pressed = document.querySelectorAll('[aria-pressed="true"]')
  expect(pressed.length).toBe(1)
  expect((pressed[0] as HTMLElement).textContent).toContain('可靠传输')
})
